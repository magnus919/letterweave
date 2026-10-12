"""Offline immutable dataset assembly with dispatch-anchored public model provenance."""
from contextlib import ExitStack
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from email_corpus_forge.contracts import canonical, digest
from email_corpus_forge.ledger import Ledger, IntegrityError, exclusive_lock
from email_corpus_forge.pipeline import load_manifest
from email_corpus_forge.nous_chat import NousChatProvider
from email_corpus_forge.nous_roles import LunaNousChatProvider
from email_corpus_forge.release import (DatasetReleaseAuthorization, assemble_live_release,
                                       _public, _rename_new_directory)

FILES = {'inputs.jsonl', 'labels.jsonl', 'provenance.jsonl', 'manifest.json',
         'taxonomy.json', 'DATA_LICENSE.txt', 'DATA_CARD.md', 'checksums.json'}
VERSIONS = {'openai/gpt-6-luna-20260922': 'openai/gpt-6-luna',
            'openai/gpt-6.1-sol-20260929': 'openai/gpt-6.1-sol'}
REVIEW_STAGES = {'review', 'rereview', 'repair_review'}
BASIS = 'accepted rows from immutable dispatch and raw response evidence'


def _snapshot(root):
    # Locks contain no source evidence and may already be created by read helpers.
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and not p.name.endswith('.lock')}


def _rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def _check_files(root):
    if {p.name for p in root.iterdir()} != FILES or any(not p.is_file() or p.is_symlink() for p in root.iterdir()):
        raise IntegrityError('release must contain exactly eight regular files')
    hashes = json.loads((root / 'checksums.json').read_text())
    expected = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                for name in FILES - {'checksums.json'}}
    if hashes != expected:
        raise IntegrityError('release checksums do not match exact file set')


def _attempt(root, attempt_id, stage, events):
    these = [e for e in events if e['data'].get('attempt_id') == attempt_id]
    dispatches = [e['data'] for e in these if e['kind'] == 'dispatched']
    if len(dispatches) != 1 or dispatches[0].get('stage') != stage:
        raise IntegrityError('missing or ambiguous immutable stage dispatch')
    envelope = json.loads((root / 'raw' / (attempt_id + '.json')).read_text())
    anchors = [e['data'] for e in these if e['kind'] in {'raw_written', 'completed'}]
    if ({e['kind'] for e in these} & {'raw_written', 'completed', 'settled'}) != {'raw_written', 'completed', 'settled'}:
        raise IntegrityError('accepted row requires completed, settled, anchored raw evidence')
    if any(a.get('raw_hash') != digest(envelope) for a in anchors):
        raise IntegrityError('raw hash anchor mismatch')
    d = dispatches[0]
    response = envelope['response']
    if (response.get('outcome') != 'content' or
            response.get('provider_status') != 'completed' or
            not isinstance(response.get('text'), str) or not response['text'].strip()):
        raise IntegrityError('accepted evidence requires completed nonempty content response')
    if (envelope.get('attempt_id') != attempt_id or envelope.get('stage') != stage or
            envelope.get('packet_hash') != digest(envelope['packet']) or
            d.get('packet_hash') != envelope['packet_hash'] or
            envelope.get('response_hash') != digest(response) or
            response.get('model') != d.get('model')):
        raise IntegrityError('raw envelope differs from immutable dispatch')
    alias = response['model']
    adapters = {'openai/gpt-6.1-sol': NousChatProvider,
                'openai/gpt-6-luna': LunaNousChatProvider}
    if alias not in adapters:
        raise IntegrityError('actual response model has no verified normalization adapter')
    try:
        request=response.get('request_payload') or {}
        messages=request.get('messages') or []
        profile='compact'
        if messages:
            header=messages[0].get('content','')
            if 'Generation profile mail-realism-v2.' in header:profile='mail-realism-v2'
            elif 'Generation profile mail-realism-v1.' in header:profile='mail-realism-v1'
        normalized = adapters[alias](None,content_profile=profile).normalize_response(response.get('raw_response'))
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise IntegrityError('original provider response cannot be normalized') from exc
    fields = ('model', 'text', 'outcome', 'provider_status',
              'input_tokens', 'output_tokens', 'reasoning_tokens')
    if any(getattr(normalized, field) != response.get(field) for field in fields):
        raise IntegrityError('stored normalized response differs from original provider evidence')
    version = (response.get('raw_response') or {}).get('model')
    if not isinstance(alias, str) or not alias or not isinstance(version, str) or not version:
        raise IntegrityError('actual model identity absent')
    if VERSIONS.get(version, version) != alias:
        raise IntegrityError('raw model version does not match normalized dispatch alias')
    request = response.get('request_payload')
    if not isinstance(request, dict) or request.get('model') != alias:
        raise IntegrityError('actual request wire model does not match dispatch')
    _public(alias); _public(version)
    return alias, version, envelope


def _assemble_model_release(run_dirs, out_dir, *, authorization, qa_exclusions=None, external_guard=None):
    """Create a new sanitized release; never modify a source or existing release."""
    if not isinstance(authorization, DatasetReleaseAuthorization):
        raise ValueError('explicit dataset release authorization required')
    authorization.check()
    roots = sorted({Path(p).resolve() for p in run_dirs}, key=str)
    out = Path(out_dir).resolve()
    if not roots or any(out == r or r in out.parents for r in roots):
        raise ValueError('destination must be outside every source')
    if out.exists() or out.is_symlink():
        raise FileExistsError('immutable release destination exists')
    out.parent.mkdir(parents=True, exist_ok=True)
    with ExitStack() as locks:
        for root in roots:
            locks.enter_context(exclusive_lock(root / '.run.lock', nonblocking=True))
        before = {root: _snapshot(root) for root in roots}
    work = Path(tempfile.mkdtemp(prefix='.model-release-', dir=out.parent))
    try:
        base = work / 'base'
        assemble_live_release(roots, base, authorization=authorization, qa_exclusions=qa_exclusions)
        _check_files(base)
        candidate = work / 'enriched'
        shutil.copytree(base, candidate)
        provenance = _rows(base / 'provenance.jsonl')
        inputs = _rows(base / 'inputs.jsonl')
        labels = _rows(base / 'labels.jsonl')
        manifest = json.loads((base / 'manifest.json').read_text())
        if external_guard and external_guard['count']:
            manifest['external_unresolved_attempt_count'] = external_guard['count']
            manifest['external_unresolved_reservations_micro'] = external_guard['reservation_micro']
        if not (len(provenance) == len(inputs) == len(labels) == manifest['accepted_count']):
            raise IntegrityError('accepted projection lengths differ')
        with ExitStack() as locks:
            for root in roots:
                locks.enter_context(exclusive_lock(root / '.run.lock', nonblocking=True))
            source_data = {}
            for root in roots:
                if _snapshot(root) != before[root]:
                    raise IntegrityError('source evidence changed during base assembly')
                m = load_manifest(root)
                ledger = Ledger(root, m['cap_micro'])
                events = ledger.events()
                h = digest(m)
                if h in source_data:
                    raise IntegrityError('ambiguous source manifest hash')
                source_data[h] = (root, m, events)
            for n, row in enumerate(provenance):
                if row['row'] != n or labels[n]['row'] != n or row['id'] != labels[n]['id']:
                    raise IntegrityError('row identity alignment mismatch')
                root, m, events = source_data[row['source_manifest_hash']]
                rid = row['id']
                record = json.loads((root / 'records' / (rid + '.json')).read_text())
                saved = [e['data'] for e in events if e['kind'] == 'record_saved' and e['data'].get('record_id') == rid]
                if len(saved) != 1 or saved[0].get('record_hash') != digest(record):
                    raise IntegrityError('accepted record lacks exact immutable anchor')
                if record.get('content_origin') != 'fresh_synthetic_private' or record.get('content') != inputs[n]:
                    raise IntegrityError('accepted row has no matching generated content')
                generations = [(s, rid + '-' + s) for s in ('generate', 'mutate')
                               if any(e['kind'] == 'dispatched' and e['data'].get('attempt_id') == rid + '-' + s for e in events)]
                if len(generations) != 1:
                    raise IntegrityError('accepted record generation identity ambiguous or absent')
                stage, aid = generations[0]
                alias, version, envelope = _attempt(root, aid, stage, events)
                # Repaired content requires a separately specified provenance policy.
                if json.loads(envelope['response']['text']) != inputs[n]:
                    raise IntegrityError('accepted content differs from generation/mutation evidence')
                row['generation_model'], row['generation_model_version'] = alias, version
                reviews = []
                paid_review_history = []
                for e in events:
                    if e['kind'] != 'dispatched':
                        continue
                    d = e['data']; s = d.get('stage'); a = d.get('attempt_id')
                    if s in REVIEW_STAGES and a == rid + '-' + s:
                        ra, rv, re = _attempt(root, a, s, events)
                        if {k: re['packet'].get(k) for k in ('subject', 'body')} != inputs[n]:
                            raise IntegrityError('review evidence does not review accepted content')
                        try:
                            paid_review = json.loads(re['response']['text'])
                        except (ValueError, TypeError) as exc:
                            raise IntegrityError('paid review response is not valid JSON') from exc
                        paid_review_history.append(paid_review)
                        reviews.append((ra, rv))
                if not reviews:
                    raise IntegrityError('accepted row has no actual paid review evidence')
                if paid_review_history != record.get('reviews'):
                    raise IntegrityError('paid review responses differ from saved ordered review history')
                row['review_models'] = sorted({a for a, _ in reviews})
                row['review_model_versions'] = sorted({v for _, v in reviews})
            for source in manifest['sources']:
                _, m, _ = source_data[source['manifest_hash']]
                source['role_models'] = m.get('role_models', {'generation': m['model'], 'review': m['model']})
                accepted = [r for r in provenance if r['source_manifest_hash'] == source['manifest_hash']]
                source['actual_generation_models'] = sorted({r['generation_model'] for r in accepted})
                source['actual_generation_model_versions'] = sorted({r['generation_model_version'] for r in accepted})
                source['actual_review_models'] = sorted({v for r in accepted for v in r['review_models']})
                source['actual_review_model_versions'] = sorted({v for r in accepted for v in r['review_model_versions']})
            manifest['model_provenance_version'] = 1
            manifest['model_provenance_basis'] = BASIS
            _public(provenance); _public(manifest)
            (candidate / 'provenance.jsonl').write_bytes(b''.join(canonical(r) + b'\n' for r in provenance))
            (candidate / 'manifest.json').write_bytes(canonical(manifest) + b'\n')
            for name in FILES - {'provenance.jsonl', 'manifest.json', 'checksums.json'}:
                if (candidate / name).read_bytes() != (base / name).read_bytes():
                    raise IntegrityError('base public projection changed')
            old = _rows(base / 'provenance.jsonl')
            fields = {'generation_model', 'generation_model_version', 'review_models', 'review_model_versions'}
            if [{k: v for k, v in r.items() if k not in fields} for r in provenance] != old:
                raise IntegrityError('labels or lineage provenance changed')
            for file in candidate.iterdir():
                _public(file.read_text())
            checksums = {name: hashlib.sha256((candidate / name).read_bytes()).hexdigest()
                         for name in sorted(FILES - {'checksums.json'})}
            (candidate / 'checksums.json').write_bytes(canonical(checksums) + b'\n')
            _check_files(candidate)
            for root in roots:
                if _snapshot(root) != before[root]:
                    raise IntegrityError('source evidence changed during enrichment')
            if external_guard:
                current = _validate_external_refs(roots)
                if current != external_guard['summary']:
                    raise IntegrityError('external uncertainty declarations changed')
                for external, snapshot in external_guard['snapshots'].items():
                    if _snapshot(external) != snapshot:
                        raise IntegrityError('external uncertainty evidence changed')
            _rename_new_directory(candidate, out)
        return manifest
    finally:
        shutil.rmtree(work)



def _external_refs(roots):
    refs = []
    required = {'attempt_id', 'record_id', 'reservation_micro', 'source_run',
                'source_manifest_hash', 'source_ledger_sha256', 'source_raw_sha256', 'packet_hash'}
    for root in roots:
        manifest = json.loads((root / 'manifest.json').read_text())
        declared = manifest.get('external_uncertainties', [])
        if not isinstance(declared, list):
            raise IntegrityError('external uncertainties must be a list')
        for ref in declared:
            if not isinstance(ref, dict) or set(ref) != required:
                raise IntegrityError('external uncertainty reference shape invalid')
            if any(not isinstance(ref[k], str) or not ref[k] for k in required - {'reservation_micro'}):
                raise IntegrityError('external uncertainty identity invalid')
            relative = Path(ref['source_run'])
            if relative.is_absolute():
                raise IntegrityError('external source reference must be relative')
            external = (root / relative).resolve()
            if not external.is_dir():
                raise IntegrityError('external uncertainty source missing')
            for k in ('attempt_id', 'record_id'):
                if Path(ref[k]).name != ref[k] or ref[k] in {'.', '..'}:
                    raise IntegrityError('external evidence identifier is not a file stem')
            refs.append((root, external, ref))
    return refs


def _validate_external_refs(roots):
    seen = {}; declared = _external_refs(roots)
    for root, external, ref in declared:
        aid = ref['attempt_id']; rid = ref['record_id']
        if type(ref['reservation_micro']) is not int or ref['reservation_micro'] != 5700:
            raise IntegrityError('external Luna reservation must remain exactly 5700 micro')
        key = (external.resolve(), aid)
        if key in seen:
            raise IntegrityError('duplicate external uncertainty reference')
        seen[key] = ref
        old = json.loads((external / 'manifest.json').read_text())
        if digest(old) != ref['source_manifest_hash']:
            raise IntegrityError('external source manifest hash changed')
        rawpath = external / 'raw' / (aid + '.json')
        for path, field in ((external / 'ledger.jsonl', 'source_ledger_sha256'), (rawpath, 'source_raw_sha256')):
            if hashlib.sha256(path.read_bytes()).hexdigest() != ref[field]:
                raise IntegrityError('external source file hash changed')
        events = Ledger(external, old['cap_micro']).events()
        plans = [e['data'] for e in events if e['kind'] == 'planned']
        if len(plans) != 1 or plans[0].get('manifest_hash') != digest(old):
            raise IntegrityError('external manifest lacks immutable planned anchor')
        these = [e for e in events if e['data'].get('attempt_id') == aid]
        reservations = [e['data'] for e in these if e['kind'] == 'reserved']
        dispatches = [e['data'] for e in these if e['kind'] == 'dispatched']
        if len(reservations) != 1 or type(reservations[0].get('amount_micro')) is not int or reservations[0]['amount_micro'] != 5700:
            raise IntegrityError('external unresolved reservation changed')
        if len(dispatches) != 1 or dispatches[0].get('packet_hash') != ref['packet_hash'] or dispatches[0].get('model') != 'openai/gpt-6-luna':
            raise IntegrityError('external dispatch identity changed')
        if any(e['kind'] in {'settled', 'completed'} for e in these):
            raise IntegrityError('external reference no longer describes an unresolved attempt')
        raw = json.loads(rawpath.read_text()); response = raw['response']
        anchors = [e['data'] for e in these if e['kind'] == 'raw_written']
        if len(anchors) != 1 or anchors[0].get('raw_hash') != digest(raw):
            raise IntegrityError('external raw response lacks exact immutable anchor')
        if (raw.get('attempt_id') != aid or raw.get('stage') != dispatches[0].get('stage') or
                raw.get('packet_hash') != ref['packet_hash'] or digest(raw['packet']) != ref['packet_hash'] or
                raw.get('response_hash') != digest(response) or response.get('model') != dispatches[0]['model']):
            raise IntegrityError('external raw envelope identity changed')
        if response.get('outcome') != 'uncertain' or all(type(response.get(k)) is int and response[k] >= 0 for k in ('input_tokens', 'output_tokens', 'reasoning_tokens')):
            raise IntegrityError('external uncertainty must retain unusable usage')
        normalized = LunaNousChatProvider(None).normalize_response(response.get('raw_response'))
        if any(getattr(normalized, k) != response.get(k) for k in ('model', 'text', 'outcome', 'provider_status', 'input_tokens', 'output_tokens', 'reasoning_tokens')):
            raise IntegrityError('external original raw response does not reconcile')
        record = json.loads((root / 'records' / (rid + '.json')).read_text())
        if (record.get('id') != rid or record.get('disposition') != 'held' or record.get('content') is not None or
                record.get('content_origin') != 'not_generated' or record.get('external_uncertainty_ref') != ref or
                record.get('reviews') != [] or record.get('generation_skipped') is not True):
            raise IntegrityError('external uncertainty slot must stay held and not generated')
        saved = [e['data'] for e in Ledger(root, json.loads((root / 'manifest.json').read_text())['cap_micro']).events()
                 if e['kind'] == 'record_saved' and e['data'].get('record_id') == rid]
        if len(saved) != 1 or saved[0].get('record_hash') != digest(record):
            raise IntegrityError('external uncertainty slot lacks immutable record anchor')
    return {'count': len(seen), 'reservation_micro': sum(r['reservation_micro'] for r in seen.values())}


def validate_external_uncertainties(run_dirs, *, already_locked_run_dirs=()):
    """Offline guard; callers may declare selected-source locks already held.

    External evidence locks are always acquired here, even if an external root
    also happens to appear among the selected roots.
    """
    roots = sorted({Path(p).resolve() for p in run_dirs}, key=str)
    already_locked = {Path(p).resolve() for p in already_locked_run_dirs}
    if not already_locked <= set(roots):
        raise ValueError('already-held locks must belong to selected source roots')
    external = {e for _, e, _ in _external_refs(roots)}
    with ExitStack() as locks:
        for root in sorted((set(roots) - already_locked) | external, key=str):
            locks.enter_context(exclusive_lock(root / '.run.lock', nonblocking=True))
        return _validate_external_refs(roots)


def assemble_model_release(run_dirs, out_dir, *, authorization, qa_exclusions=None):
    roots = sorted({Path(p).resolve() for p in run_dirs}, key=str)
    external = {e for _, e, _ in _external_refs(roots)}
    if any(Path(out_dir).resolve() == e or e in Path(out_dir).resolve().parents for e in external):
        raise ValueError('release destination cannot be inside external evidence')
    with ExitStack() as locks:
        # The base assembler obtains selected-source locks itself; retain only
        # separate external locks throughout that call, avoiding self-deadlock.
        for root in sorted(external - set(roots), key=str):
            locks.enter_context(exclusive_lock(root / '.run.lock', nonblocking=True))
        with ExitStack() as selected_locks:
            for root in roots:
                selected_locks.enter_context(exclusive_lock(root / '.run.lock', nonblocking=True))
            summary = _validate_external_refs(roots)
            snapshots = {e: _snapshot(e) for e in external}
        guard = {'summary': summary, 'snapshots': snapshots, **summary}
        return _assemble_model_release(roots, out_dir, authorization=authorization,
                                       qa_exclusions=qa_exclusions, external_guard=guard)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', nargs='+', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--authorization', required=True, type=Path)
    parser.add_argument('--qa-exclusions', type=Path)
    args = parser.parse_args()
    authorization = DatasetReleaseAuthorization(**json.loads(args.authorization.read_text()))
    exclusions = json.loads(args.qa_exclusions.read_text()) if args.qa_exclusions else []
    if not isinstance(exclusions, list) or any(not isinstance(x, str) for x in exclusions):
        raise ValueError('QA exclusions must be a JSON list of record IDs')
    result = assemble_model_release(args.runs, args.out, authorization=authorization, qa_exclusions=exclusions)
    print(json.dumps({'accepted_count': result['accepted_count'], 'model_provenance_version': 1}))


if __name__ == '__main__':
    main()
