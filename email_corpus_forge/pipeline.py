"""Resumable offline pilot orchestration with immutable evidence."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import random
import shutil
import tempfile
from dataclasses import asdict
from .contracts import (ANCHORS, LABELS, VERSION, RUBRIC, ContractError, blind_packet,
                        canonical, digest, review_disposition, reviewed_labels,
                        validate_content, validate_review, write_contracts)
from .ledger import IntegrityError, Ledger, exclusive_lock, write_once
from .providers import FixtureProvider, Provider, Response
from .planning import configure_plan
from .relations import evaluate_relation, mutation_applicability
from .assessments import review_projection, validity_assessment, record_projection
from .duplicates import near_duplicates
from .openai_responses import OpenAIResponsesProvider
from .provider_adapter import DispatchNotAuthorized


class PendingOutcome(RuntimeError):
    pass


class BudgetBlocked(RuntimeError):
    pass


class LiveProviderBlocked(RuntimeError):
    pass


class ProviderContentUnavailable(ContractError):
    pass


def _response_content(response):
    if response.get('outcome','content') != 'content':
        raise ProviderContentUnavailable('provider terminal outcome: '+str(response.get('outcome')))
    return json.loads(response['text'])


def code_fingerprint() -> str:
    root = Path(__file__).parent
    return digest({str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(root.rglob("*")) if p.is_file() and p.suffix in {".py", ".json"}})


def create_plan(run_dir: Path, seed: int = 17, **configuration) -> dict:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(run_dir / ".run.lock", nonblocking=True):
        if (run_dir / "manifest.json").exists():
            raise FileExistsError("run already planned; use status/run to resume")
        cases = [("single", [label]) for label in LABELS]
        pairs = [(a, b) for i, a in enumerate(LABELS) for b in LABELS[i + 1:]][:11]
        cases += [("overlap", list(pair)) for pair in pairs]
        cases += [("no_match_candidate", []), ("no_match_candidate", []),
                  ("missing_context", []), ("missing_context", []),
                  ("near_negative", [LABELS[0]]), ("near_negative", [LABELS[6]])]
        family_indices = list(range(24))
        random.Random(seed).shuffle(family_indices)
        split_by_index = {i: "train_fixture" if n < 16 else "development_fixture" if n < 20 else "test_fixture"
                          for n, i in enumerate(family_indices)}
        topics = ["maps", "gardens", "books", "music", "bicycles", "ceramics", "weather", "rivers",
                  "parks", "bridges", "theater", "baking", "travel", "robots", "photography", "boats",
                  "trails", "astronomy", "architecture", "poetry", "painting", "knitting", "games", "crafts"]
        scenarios = [{"family_id": f"f{i:02d}", "case": case, "intended_labels": labels,
                      "topic": topics[i], "split": split_by_index[i], "variants": list(range(5))}
                     for i, (case, labels) in enumerate(cases)]
        settings = configure_plan(scenarios, seed=seed, **configuration)
        scenarios = settings["scenarios"]
        manifest = {
            "contract_version": VERSION, "mode": "fixture_only", "dataset_kind": "software_fixture_not_corpus",
            "seed": seed, "family_count": 24, "message_count": 120, "scenarios": scenarios,
            "model": "fixture-v1", "provider": "fixture", "cap_micro": 10_000_000,
            "max_repairs": 12, "max_rereviews": 12, "terms_status": "unresolved", "live_authorized": False,
            "code_fingerprint": code_fingerprint(), "python_version": platform.python_version(),
            "rubric_hash": digest(RUBRIC), "split_purpose": "development leakage fixture only",
            "coverage": {label: {"positive_families": sum(label in s["intended_labels"] for s in scenarios),
                                 "negative_families": sum(label not in s["intended_labels"] for s in scenarios),
                                 "near_negative_families": sum(s["case"] == "near_negative" and label in s["intended_labels"] for s in scenarios),
                                 "basis": "intended-label hypotheses; absence is not validated negative coverage",
                                 "actual_semantic_coverage": "not established"}
                         for label in LABELS},
        }
        manifest.update(settings)
        manifest["split_purpose"] = "fixture development only" if settings["provider_mode"] == "fixture" else "planned family partition; no generated corpus"
        write_contracts(run_dir / "contracts")
        manifest["contract_hashes"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in sorted((run_dir / "contracts").glob("*.json"))}
        write_once(run_dir / "manifest.json", manifest)
        Ledger(run_dir, manifest["cap_micro"]).append("planned", manifest_hash=digest(manifest))
        return manifest


def load_manifest(run_dir: Path) -> dict:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    events = Ledger(run_dir, manifest["cap_micro"]).events()
    planned = [e for e in events if e["kind"] == "planned"]
    if len(planned) != 1 or planned[0]["data"]["manifest_hash"] != digest(manifest):
        raise IntegrityError("manifest changed or unanchored")
    if manifest["code_fingerprint"] != code_fingerprint() or manifest["rubric_hash"] != digest(RUBRIC):
        raise IntegrityError("code or rubric changed; create a new run")
    if manifest["python_version"].split(".")[:2] != platform.python_version().split(".")[:2]:
        raise IntegrityError("Python minor version changed; create a new run")
    for name, expected in manifest["contract_hashes"].items():
        if hashlib.sha256((run_dir / "contracts" / name).read_bytes()).hexdigest() != expected:
            raise IntegrityError("frozen contract changed")
    if manifest["live_authorized"] is not False:
        raise LiveProviderBlocked("live execution is not authorized")
    return manifest


def _raw(run_dir: Path, ledger: Ledger, attempt_id: str, *, events: list[dict] | None = None) -> dict:
    path = run_dir / "raw" / f"{attempt_id}.json"
    envelope = json.loads(path.read_text())
    if digest(envelope["response"]) != envelope["response_hash"]:
        raise IntegrityError("raw response hash mismatch")
    anchor = [e for e in (events if events is not None else ledger.attempt_events(attempt_id)) if e["kind"] in {"raw_written", "completed"}
              and e["data"]["attempt_id"] == attempt_id]
    if anchor and any(e["data"]["raw_hash"] != digest(envelope) for e in anchor):
        raise IntegrityError("raw evidence changed")
    return envelope


def _call(run_dir: Path, ledger: Ledger, provider: Provider, attempt_id: str, stage: str, packet: dict) -> dict:
    if stage == "mutate" and hasattr(provider, "mutation_operators") and packet["operation"]["operator"] not in provider.mutation_operators:
        raise ContractError("unsupported fixture mutation operator; no dispatch")
    events = ledger.attempt_events(attempt_id)
    raw_path = run_dir / "raw" / f"{attempt_id}.json"
    if any(e["kind"] == "completed" for e in events):
        return _response_content(_raw(run_dir, ledger, attempt_id)["response"])
    if raw_path.exists():
        envelope = _raw(run_dir, ledger, attempt_id)
        if envelope["packet_hash"] != digest(packet) and stage not in {"review", "rereview", "repair_review"}:
            raise IntegrityError("request changed on recovery")
    else:
        if any(e["kind"] == "dispatched" for e in events):
            raise PendingOutcome(f"{attempt_id}: uncertain result; reservation retained; no automatic retry")
        if hasattr(provider,'prepare'):
            provider.prepare(stage,packet)
        if not ledger.reserve(attempt_id, provider.reservation_micro):
            raise BudgetBlocked("cost cap stops request before dispatch")
        ledger.append("dispatched", attempt_id=attempt_id, stage=stage, packet_hash=digest(packet),
                      provider=provider.name, model=provider.model)
        try:
            response = getattr(provider, "review" if stage in {"review", "rereview", "repair_review"} else stage)(packet)
        except Exception as exc:
            # No assumption that a transport exception implies unbilled failure.
            ledger.append("uncertain", attempt_id=attempt_id, error_type=type(exc).__name__)
            raise PendingOutcome(f"{attempt_id}: provider outcome uncertain") from exc
        if not isinstance(response, Response):
            ledger.append("uncertain", attempt_id=attempt_id, error_type="invalid_response_envelope")
            raise PendingOutcome("provider returned no usable usage envelope")
        payload = asdict(response)
        envelope = {"attempt_id": attempt_id, "stage": stage, "packet": packet,
                    "packet_hash": digest(packet), "response": payload, "response_hash": digest(payload)}
        write_once(raw_path, envelope)
        ledger.append("raw_written", attempt_id=attempt_id, raw_hash=digest(envelope))
    response = envelope["response"]
    if response["model"] != provider.model:
        raise IntegrityError("unexpected response model; reservation retained")
    for key in ("input_tokens", "output_tokens", "reasoning_tokens"):
        if type(response[key]) is not int or response[key] < 0:
            raise IntegrityError("missing or invalid usage; reservation retained")
    if response["reasoning_tokens"] > response["output_tokens"]:
        raise IntegrityError("reasoning exceeds inclusive output usage")
    if response.get('outcome') == 'uncertain':
        raise PendingOutcome('nonterminal or HTTP response; reservation retained; no automatic retry')
    # Inclusive output usage accounts for reasoning exactly once.
    actual_micro = provider.cost_micro(Response(**response)) if hasattr(provider, "cost_micro") else response["input_tokens"] * 2 + response["output_tokens"] * 10
    ledger.settle(attempt_id, actual_micro)
    ledger.append("completed", attempt_id=attempt_id, raw_hash=digest(envelope))
    return _response_content(response)


def _save_record(run_dir: Path, ledger: Ledger, record: dict) -> None:
    write_once(run_dir / "records" / f"{record['id']}.json", record)
    ledger.append("record_saved", record_id=record["id"], record_hash=digest(record))


def _records(run_dir: Path, ledger: Ledger) -> list[dict]:
    anchors = {e["data"]["record_id"]: e["data"]["record_hash"]
               for e in ledger.events() if e["kind"] == "record_saved"}
    records = []
    for record_id in anchors:
        if not (run_dir / "records" / f"{record_id}.json").is_file():
            raise IntegrityError("ledger-anchored record is missing; do not regenerate")
    for p in sorted((run_dir / "records").glob("*.json")):
        record = json.loads(p.read_text())
        if record["id"] in anchors and anchors[record["id"]] != digest(record):
            raise IntegrityError("saved record changed")
        if record["id"] not in anchors:
            # Recover a crash after a fully written result but before its ledger event.
            ledger.append("record_saved", record_id=record["id"], record_hash=digest(record))
        records.append(record)
    return records


def _verify_raw_evidence(run_dir: Path, ledger: Ledger) -> None:
    events = ledger.events()
    anchored = {e["data"]["attempt_id"] for e in events
                if e["kind"] in {"raw_written", "completed"}}
    by_attempt = {}
    for event in events:
        attempt = event['data'].get('attempt_id')
        if attempt is not None:
            by_attempt.setdefault(attempt, []).append(event)
    for attempt_id in anchored:
        if not (run_dir / "raw" / f"{attempt_id}.json").is_file():
            raise IntegrityError("ledger-anchored raw evidence is missing; do not regenerate")
        _raw(run_dir, ledger, attempt_id, events=by_attempt[attempt_id])


def _quality_records(run_dir: Path, ledger: Ledger, records: list[dict], manifest: dict):
    by_id = {r['id']: r for r in records}
    anchors = {e['data']['record_id']: e['data']['relation_hash'] for e in ledger.events() if e['kind'] == 'relation_saved'}
    for rid in anchors:
        if not (run_dir / 'relations' / f'{rid}.json').is_file():
            raise IntegrityError('ledger-anchored relation is missing')
    relations = []
    quarantine = set()
    expected_ids = set()
    for record in records:
        hypothesis = record.get('mutation_hypothesis')
        if not hypothesis:
            continue
        rid = record['id']
        expected_ids.add(rid)
        parent = by_id.get(record['parent_id'])
        if parent is None:
            raise IntegrityError('mutation parent record missing')
        if parent is not None and (parent['family_id'] != record['family_id'] or parent['split'] != record['split']):
            raise IntegrityError('mutation parent crosses family or split')
        relation = {'id': rid, 'parent_id': record['parent_id'], 'family_id': record['family_id'],
                    'split': record['split'], 'operator': hypothesis['operator'],
                    'operator_version': hypothesis['operator_version'], 'hypothesis_hash': digest(hypothesis),
                    **evaluate_relation(parent, record, hypothesis)}
        path = run_dir / 'relations' / f'{rid}.json'
        if path.exists():
            stored = json.loads(path.read_text())
            if digest(stored) != digest(relation) or (rid in anchors and anchors[rid] != digest(stored)):
                raise IntegrityError('relation evidence changed')
        else:
            write_once(path, relation)
        if rid not in anchors:
            ledger.append('relation_saved', record_id=rid, relation_hash=digest(relation))
        relations.append(relation)
        # Transformation failure excludes controlled pairs, not defensible standalone labels.
    if set(anchors) - expected_ids or any(p.stem not in expected_ids for p in (run_dir / 'relations').glob('*.json')):
        raise IntegrityError('relation evidence has no matching mutation record')
    duplicate_report = near_duplicates(records, manifest['near_duplicates'])
    quarantine.update(duplicate_report['quarantine_ids'])
    # A descendant of a quarantined transformation cannot silently bypass lineage diagnostics.
    for record in sorted(records, key=lambda r: (r['family_id'], r['variant'])):
        if record.get('parent_id') in quarantine:
            quarantine.add(record['id'])
    effective = []
    relation_by_id={r['id']:r for r in relations}
    for record in records:
        record = dict(record)
        projection=record_projection(record)
        record.update(projection)
        record['reviewed_labels']=projection['final_labels'] if record.get('reviews') else None
        record['assessment']=validity_assessment(record)
        relation=relation_by_id.get(record['id'])
        record['controlled_transition_included']=bool(relation and relation['local_checks_pass'])
        if record['id'] in quarantine and record['disposition'] == 'accepted':
            record['original_disposition'] = 'accepted'
            record['disposition'] = 'held'
            record['quarantine_reason'] = 'relation failure/indeterminate or lexical duplicate/coverage limitation'
        effective.append(record)
    effective_by_id={r['id']:r for r in effective}
    controlled={r['id']:r['controlled_transition_included'] for r in effective}
    for record in sorted(effective,key=lambda r:(r['family_id'],r['variant'])):
        parent_id=record.get('parent_id')
        if parent_id and (record['disposition']!='accepted' or effective_by_id[parent_id]['disposition']!='accepted'
                          or record['assessment']['pool']!='on_target' or effective_by_id[parent_id]['assessment']['pool']!='on_target'):
            record['controlled_transition_included']=False
            record['controlled_exclusion']='endpoint excluded or off-target; standalone labels remain separate'
            controlled[record['id']]=False
        if parent_id and by_id[parent_id].get('parent_id') and not controlled.get(parent_id,False):
            record['controlled_transition_included']=False
            record['controlled_exclusion']='ancestor transformation excluded'
            controlled[record['id']]=False
    return effective, relations, duplicate_report


def run_pipeline(run_dir: Path, provider: Provider | None = None) -> dict:
    run_dir = Path(run_dir)
    provider = provider or FixtureProvider()
    if not provider.is_fixture and not isinstance(provider,OpenAIResponsesProvider):
        raise LiveProviderBlocked("provider is not an authorized private-pilot Responses adapter")
    with exclusive_lock(run_dir / ".run.lock", nonblocking=True):
        manifest = load_manifest(run_dir)
        if provider.is_fixture:
            if manifest["mode"] != "fixture_only" or manifest["provider_mode"] != "fixture":
                raise LiveProviderBlocked("live plan requires independently verified private-pilot authorization")
        else:
            try:provider.assert_run_authorized(manifest)
            except DispatchNotAuthorized as exc:raise LiveProviderBlocked(str(exc)) from exc
        ledger = Ledger(run_dir, manifest["cap_micro"])
        if not provider.is_fixture:
            authority = {'manifest_hash':digest(manifest),'approval_reference':provider.authorization.approval_reference,
                         'cap_micro':provider.authorization.cap_micro,'model':provider.model,'provider':provider.name,'settings':provider.settings(),
                         'content_origin':'api_contract_fixture' if getattr(provider.transport,'is_offline_fixture',False) else 'fresh_synthetic_private'}
            prior = [e['data'] for e in ledger.events() if e['kind']=='private_pilot_authorized']
            if prior and prior != [authority]:raise IntegrityError('private pilot authority changed on resume')
            if not prior:ledger.append('private_pilot_authorized',**authority)
        _verify_raw_evidence(run_dir, ledger)
        records = _records(run_dir, ledger)
        _quality_records(run_dir, ledger, records, manifest)
        done = {r["id"] for r in records}
        hashes = {digest(r["content"]): r["id"] for r in records if r["disposition"] == "accepted"}
        repair_requests = {e["data"]["record_id"] for e in ledger.events() if e["kind"] == "repair_requested"}
        rereview_attempts = {e["data"]["attempt_id"] for e in ledger.events()
                            if e["kind"] == "dispatched" and e["data"]["stage"] == "rereview"}
        families = list(manifest["scenarios"])
        random.Random(manifest["seed"] + 1).shuffle(families)
        # Earlier parent indices always complete first; review packets remain stateless and blind.
        jobs = [(s, v) for s in families for v in sorted(s["variants"])]
        by_id = {r['id']: r for r in records}
        for scenario, variant in jobs:
            record_id = f"{scenario['family_id']}-v{variant}"
            if record_id in done:
                continue
            hypothesis = next((m for m in scenario["mutations"] if m["variant"] == variant), None)
            parent_id = f"{scenario['family_id']}-v{hypothesis['parent_variant']}" if hypothesis else None
            applicability = mutation_applicability(by_id.get(parent_id), hypothesis) if hypothesis else None
            if hypothesis and applicability['status'] != 'applicable':
                record = {'id':record_id,'family_id':scenario['family_id'],'split':scenario['split'],'content':None,
                          'intended_labels':scenario['intended_labels'],'reviews':[],'reviewed_labels':None,
                          'disposition':'held','reason':'mutation skipped: '+applicability['status'],
                          'generation_skipped':True,'mutation_applicability':applicability,'review_resource':'not_required',
                          'original_error':None,'repair_parent':None,'kind':'software_fixture_not_corpus' if provider.is_fixture else 'private_synthetic_quality_pilot',
                          'schema_version':VERSION,'content_origin':'not_generated','slice':scenario['slice'],
                          'diagnostic_tags':scenario['diagnostic_tags'],'mutation_hypothesis':hypothesis,'variant':variant,
                          'parent_id':parent_id,'lineage_root':f"{scenario['family_id']}-v0",'generation_stage':'skipped'}
                _save_record(run_dir,ledger,record);by_id[record_id]=record;done.add(record_id)
                continue
            review_failure=None
            review_resource='not_requested'
            original_error = None
            repair_parent = None
            reviews = []
            content = None
            reason = "complete isolated automated review"
            disposition = "held"
            try:
                try:
                    if hypothesis:
                        parent = by_id.get(parent_id)
                        if parent is None or parent['content'] is None:
                            raise ContractError("mutation parent content unavailable")
                        validate_content(parent['content'])
                        packet = {"parent_content": parent['content'],
                                  "operation": {k: hypothesis[k] for k in ("operator", "operator_version", "changed_factors", "rationale", "preserve_facts") if k in hypothesis},
                                  "content_schema_version": VERSION}
                        content = _call(run_dir, ledger, provider, record_id + "-mutate", "mutate", packet)
                    else:
                        content = _call(run_dir, ledger, provider, record_id + "-generate", "generate",
                                        {"scenario": scenario, "variant": variant, "content_schema_version": VERSION})
                    validate_content(content)
                except (ContractError, json.JSONDecodeError) as exc:
                    original_error = str(exc)
                    if isinstance(exc,ProviderContentUnavailable):
                        raise
                    if hypothesis and content is None:
                        raise
                    if record_id not in repair_requests and len(repair_requests) >= manifest["max_repairs"]:
                        raise ContractError("malformed content; repair allowance exhausted") from exc
                    repair_parent = record_id + ("-mutate" if hypothesis else "-generate")
                    if record_id not in repair_requests:
                        ledger.append("repair_requested", record_id=record_id, parent_attempt=repair_parent,
                                      reason="malformed content only", family_id=scenario["family_id"], split=scenario["split"])
                        repair_requests.add(record_id)
                    content = _call(run_dir, ledger, provider, record_id + "-repair", "repair",
                                    {"content": content, "failure": original_error,
                                     "instruction": "Repair malformed content only; do not seek label agreement."})
                    validate_content(content)
                stage = "repair_review" if repair_parent else "review"
                review = _call(run_dir, ledger, provider, record_id + "-" + stage, stage, blind_packet(content))
                validate_review(review, content)
                reviews.append(review)
                disposition = review_disposition(review)
                mismatched = not hypothesis and set(reviewed_labels(review)) != set(scenario["intended_labels"])
                if mismatched:
                    ledger.append("diagnosis",record_id=record_id,category="scenario_intent_disagreement",label_validity=disposition)
                if disposition == "held" or mismatched:
                    ledger.append("flagged",record_id=record_id,category="semantic_uncertainty" if disposition=="held" else "scenario_diagnosis")
                    second_id=record_id+"-rereview"
                    allocated=record_id in manifest['rereview_allocation']
                    if second_id in rereview_attempts or allocated and len(rereview_attempts)<manifest['max_rereviews']:
                        review_resource='rereview_completed'
                        rereview_attempts.add(second_id)
                        second=_call(run_dir,ledger,provider,second_id,"rereview",blind_packet(content))
                        validate_review(second,content);reviews.append(second)
                        disposition=review_projection(reviews)['label_validity']
                        reason='persistent uncertainty or review disagreement' if disposition=='held' else 'complete isolated automated review'
                    else:
                        review_resource='unallocated_or_exhausted'
                        reason='label uncertainty; rereview unavailable under frozen allocation' if disposition=='held' else 'defensible labels; off-target diagnosis; rereview unavailable under frozen allocation'
                projection=review_projection(reviews)
                disposition=projection['label_validity']
                if disposition == "accepted" and digest(content) in hashes:
                    disposition, reason = "rejected", "exact duplicate content"
                if disposition == "accepted":
                    hashes[digest(content)] = record_id
            except (PendingOutcome, BudgetBlocked):
                return status_run(run_dir, check_manifest=False)
            except (ContractError, json.JSONDecodeError) as exc:
                review_failure=str(exc) if content is not None else None
                if review_failure:review_resource="rereview_failed" if reviews else "review_failed"
                disposition, reason = "held", "contract failure: " + str(exc)
            record = {"id": record_id, "family_id": scenario["family_id"], "split": scenario["split"],
                      "content": content, "intended_labels": scenario["intended_labels"], "reviews": reviews,
                      "reviewed_labels": review_projection(reviews)["final_labels"] if reviews else None,
                      "review_resource":review_resource, "review_failure":review_failure, "mutation_applicability":applicability,
                      "disposition": disposition, "reason": reason, "original_error": original_error,
                      "repair_parent": repair_parent, "kind": "software_fixture_not_corpus" if provider.is_fixture else "private_synthetic_quality_pilot", "schema_version": VERSION,
                      "content_origin": "software_fixture" if provider.is_fixture else authority["content_origin"], "slice": scenario["slice"],
                      "diagnostic_tags": scenario["diagnostic_tags"],
                      "mutation_hypothesis": next((m for m in scenario["mutations"] if m["variant"] == variant), None),
                      "variant": variant, "parent_id": parent_id, "lineage_root": f"{scenario['family_id']}-v0",
                      "generation_stage": "mutate" if hypothesis else "generate"}
            _save_record(run_dir, ledger, record)
            by_id[record_id] = record
        return status_run(run_dir, check_manifest=False)


def status_run(run_dir: Path, *, check_manifest: bool = True) -> dict:
    run_dir = Path(run_dir)
    manifest = load_manifest(run_dir) if check_manifest else json.loads((run_dir / "manifest.json").read_text())
    ledger = Ledger(run_dir, manifest["cap_micro"])
    _verify_raw_evidence(run_dir, ledger)
    records = _records(run_dir, ledger)
    records, relations, duplicate_report = _quality_records(run_dir, ledger, records, manifest)
    counts = {k: sum(r["disposition"] == k for r in records) for k in ("accepted", "held", "rejected")}
    settled = {e["data"]["attempt_id"] for e in ledger.events() if e["kind"] == "settled"}
    dispatched = {e["data"]["attempt_id"] for e in ledger.events() if e["kind"] == "dispatched"}
    label_support = {}
    for label in LABELS:
        accepted = [r for r in records if r["disposition"] == "accepted"]
        positive = [r for r in accepted if label in r["reviewed_labels"]]
        negative = [r for r in accepted if label not in r["reviewed_labels"]]
        label_support[label] = {"positive": len(positive), "negative": len(negative),
                                "positive_families": len({r["family_id"] for r in positive}),
                                "negative_families": len({r["family_id"] for r in negative}),
                                "unknown": sum(r.get("content") is not None and bool(r["reviews"]) and not r.get("review_failure") and r["final_judgments"][label]["decision"] == "unknown" for r in records),
                                "technical_unavailable": sum(r.get("content") is None or not r["reviews"] or bool(r.get("review_failure")) for r in records),
                                "denominator": manifest["message_count"]}
    return {"kind": manifest["dataset_kind"], "provider_mode": manifest["provider_mode"],
            "requested_candidates": manifest["requested_candidates"], "topup_policy": manifest["topup_policy"],
            "budget_estimate": manifest["budget_estimate"], "status": "complete" if len(records) == manifest["message_count"] else "stopped",
            "counts": counts, "processed": len(records),
            "original_denominator": manifest["message_count"], "family_denominator": manifest["family_count"],
            "unattempted": manifest["message_count"] - len(records),
            "rates_on_original": {k: v / manifest["message_count"] for k, v in counts.items()},
            "pending_attempts": sorted(dispatched - settled), "budget": ledger.balance(),
            "repair_count": len({e["data"]["record_id"] for e in ledger.events() if e["kind"] == "repair_requested"}),
            "rereview_count": len({e["data"]["attempt_id"] for e in ledger.events()
                                    if e["kind"] == "dispatched" and e["data"]["stage"] == "rereview"}),
            "all_negative_accepted": sum(r["disposition"] == "accepted" and r["reviewed_labels"] == [] for r in records),
            "original_malformed": sum(r["original_error"] is not None for r in records),
            "original_malformed_rate": sum(r["original_error"] is not None for r in records) / manifest["message_count"],
            "per_label_support": label_support,
            "diagnostics": {"technical_contract_failure": sum(r["reason"].startswith("contract failure:") for r in records),
                            "missing_context": sum(any("context" in j["reason"].lower() and j["decision"] == "unknown"
                                                        for j in r["final_judgments"].values()) for r in records if r["reviews"]),
                            "pending_technical_outcome": len(dispatched - settled)},
            "live_authorized": any(e['kind']=='private_pilot_authorized' for e in ledger.events()),
            "public_release_authorized": False,
            "slice_counts": {slice_name: {d: sum(r.get("slice", "ordinary") == slice_name and r["disposition"] == d for r in records)
                                            for d in counts} for slice_name in ("ordinary", "challenge", "uncertainty")},
            "planned_coverage": manifest["coverage"],
            "operator_counts": {operator: {d: sum(r.get("mutation_hypothesis") is not None and r["mutation_hypothesis"]["operator"] == operator and r["disposition"] == d for r in records)
                                             for d in counts} for operator in sorted({r["mutation_hypothesis"]["operator"] for r in records if r.get("mutation_hypothesis")})},
            "relation_counts": {d: sum(r['result'] == d for r in relations) for d in ('pass', 'fail', 'indeterminate')},
            "near_duplicates": duplicate_report,
            "pool_counts": {p:sum(r["assessment"]["pool"]==p for r in records) for p in ("on_target","off_target","unresolved")},
            "generated_candidates":sum(r.get("content") is not None for r in records),
            "skipped_mutations":sum(bool(r.get("generation_skipped")) for r in records),
            "controlled_transition_count":sum(r["controlled_transition_included"] for r in records),
            "review_resource_counts":{x:sum(r.get("review_resource")==x for r in records) for x in ("not_requested","rereview_completed","unallocated_or_exhausted","rereview_failed","review_failed","not_required")},
            "mutation_relation_status": "mechanical relation checks; not semantic quality evidence"}


def export_run(run_dir: Path, out_dir: Path) -> dict:
    run_dir, out_dir = Path(run_dir), Path(out_dir)
    with exclusive_lock(run_dir / ".run.lock", nonblocking=True), exclusive_lock(out_dir.parent / ("." + out_dir.name + ".export.lock"), nonblocking=True):
        manifest = load_manifest(run_dir)
        ledger = Ledger(run_dir, manifest["cap_micro"])
        if manifest["mode"] != "fixture_only":
            raise LiveProviderBlocked("live corpus export is disabled")
        records = _records(run_dir, ledger)
        records, relations, duplicate_report = _quality_records(run_dir, ledger, records, manifest)
        _verify_raw_evidence(run_dir, ledger)
        # Verify all evidence, including rejected/held candidates.
        for path in (run_dir / "raw").glob("*.json"):
            _raw(run_dir, ledger, path.stem)
        report = status_run(run_dir, check_manifest=False)
        if report["pending_attempts"]:
            raise PendingOutcome("cannot export while outcomes or usage remain uncertain")
        if report["processed"] != manifest["message_count"]:
            raise IntegrityError("incomplete fixture run cannot be exported")
        if out_dir.exists():
            raise FileExistsError("export destination exists; immutable bundles are never overwritten")
        out_dir.parent.mkdir(parents=True, exist_ok=True)
        temp = Path(tempfile.mkdtemp(prefix=".export-", dir=out_dir.parent))
        try:
            accepted = [r for r in records if r["disposition"] == "accepted"]
            def jsonl(name: str, values: list[dict]):
                with (temp / name).open("wb") as out:
                    for value in values:
                        out.write(canonical(value) + b"\n")
                    out.flush()
                    os.fsync(out.fileno())
            # Rows align by ordinal via a separate index; content contains no metadata.
            jsonl("inputs.jsonl", [validate_content(r["content"]) for r in accepted])
            jsonl("labels.jsonl", [{"row": n, "id": r["id"], "labels": r["reviewed_labels"],
                                    "judgments": r["final_judgments"], "first_pass_judgments":r["first_pass_judgments"],
                                    "latest_judgments":r["latest_judgments"],"pool":r["assessment"]["pool"]} for n, r in enumerate(accepted)])
            jsonl("provenance.jsonl", [{"row": n, **{k: r[k] for k in ("id", "family_id", "split", "intended_labels", "repair_parent", "kind", "content_origin", "slice", "diagnostic_tags", "variant", "mutation_hypothesis", "parent_id", "lineage_root", "generation_stage")}}
                                       for n, r in enumerate(accepted)])
            jsonl("relations.jsonl", relations)
            jsonl("pools.jsonl", [{"id":r["id"],"assessment":r["assessment"],"controlled_transition_included":r["controlled_transition_included"]} for r in records])
            jsonl("review-histories.jsonl", [{"id":r["id"],"reviews":r["reviews"],"first_pass_judgments":r["first_pass_judgments"],"latest_judgments":r["latest_judgments"],"final_judgments":r["final_judgments"]} for r in records])
            jsonl("diagnostics.jsonl", [r for r in records if r["disposition"] != "accepted"])
            for name, value in (("manifest", manifest), ("report", report)):
                write_once(temp / f"{name}.json", value)
            shutil.copytree(run_dir / "contracts", temp / "contracts")
            (temp / "FIXTURE_ONLY.txt").write_text("Software test fixtures. Not a generated corpus, not gold labels, not publication-ready.\n")
            hashes = {str(p.relative_to(temp)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(temp.rglob("*")) if p.is_file()}
            write_once(temp / "checksums.json", hashes)
            os.rename(temp, out_dir)
        finally:
            if temp.exists():
                shutil.rmtree(temp)
        ledger.append("exported", destination=str(out_dir), checksums_hash=digest(hashes))
        return report
