"""Bounded critical mutation audit, entirely offline in disposable copies."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MUTATIONS = [
    ('release_rights_gate_removed', 'release.py', 'if self.dataset_release_approved is not True or self.redistribution_rights_confirmed is not True:', 'if False:', 'test_live_release.LiveReleaseTests.test_unapproved_dataset_or_unconfirmed_rights_rejected'),
    ('release_privacy_gate_removed', 'release.py', 'if _PRIVATE.search(value) or _SECRET.search(value):', 'if False:', 'test_live_release.LiveReleaseTests.test_private_path_and_secret_shaped_reader_content_rejected'),
    ('release_qa_exclusions_removed', 'release.py', 'blocked=qa|quarantine', 'blocked=quarantine', 'test_live_release.LiveReleaseTests.test_explicit_qa_exclusion_omits_content_and_reports_count'),
    ('live_export_enabled', 'pipeline.py', 'if manifest["mode"] != "fixture_only":', 'if False:', 'test_release_guards.ReleaseGuardTests.test_reviewed_live_plan_still_cannot_export_or_change_evidence'),
    ('fixture_marker_gold_claim', 'pipeline.py', 'Software test fixtures. Not a generated corpus, not gold labels, not publication-ready.', 'Validated corpus with gold labels.', 'test_release_guards.ReleaseGuardTests.test_fixture_export_is_explicitly_fixture_only'),
    ("typography_byte_budget_removed", "typography.py", "len(value.encode('utf-8'))>limit", "False", "test_typography.TypographyTests.test_utf8_byte_limits_and_emoji_rejection"),
    ("split_contraction_guard_removed", "typography.py", "return not broken_apostrophe_fragments(content)", "return True", "test_typography.TypographyTests.test_newline_split_contractions_are_errors_not_rewritten"),
    ("parent_possessive_guard_removed", "nous_chat.py", "if broken_apostrophe_fragments(content, packet['parent_content']):", "if False:", "test_typography.TypographyTests.test_parent_possessive_newline_corruption_keeps_raw_usage"),
    ('format_punctuation_erased', 'relations.py', 're.sub(r"\\s+", " ", text.casefold()).strip()', 're.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()', 'test_typography.TypographyTests.test_case_whitespace_equivalence_never_erases_punctuation_or_meaning'),
    ("candidate_noop_success_allowed", "relations.py", "result='fail' if applicable['status']=='inapplicable' or change=='no_op' or facts['status']=='fail' or label_result=='fail' else 'pass' if applicable['status']=='applicable' and change=='changed' and facts['status']=='pass' and label_result=='pass' else 'indeterminate'", "result='fail' if applicable['status']=='inapplicable' or facts['status']=='fail' or label_result=='fail' else 'pass' if applicable['status']=='applicable' and change!='indeterminate' and facts['status']=='pass' and label_result=='pass' else 'indeterminate'", "test_candidate_v02.CandidateTests.test_identical_content_never_successful_even_when_labels_preserved"),
    ("intent_replaces_observed_labels", "assessments.py", "observed = set(final['final_labels'])", "observed = set(record.get('intended_labels', []))", "test_candidate_v02.CandidateTests.test_off_target_labels_are_valid_independent_of_intent"),
    ("intent_mismatch_circular_hold", "assessments.py", "'label_validity': projected['label_validity'],", "'label_validity': 'held' if adherence['status'] == 'off_target' else projected['label_validity'],", "test_candidate_v02.CandidateTests.test_off_target_labels_are_valid_independent_of_intent"),
    ("first_review_projection_restored", "assessments.py", "'final_judgments': final,", "'final_judgments': first,", "test_candidate_v02.CandidateTests.test_history_unknown_preserved_and_first_pass_separate"),
    ("mutation_predispatch_applicability_removed", "pipeline.py", "if hypothesis and applicability['status'] != 'applicable':", "if False:", "test_candidate_v02.CandidateTests.test_inapplicable_baseline_skips_variant_without_paid_stage"),
    ("frozen_rereview_allocation_ignored", "pipeline.py", "allocated=record_id in manifest['rereview_allocation']", "allocated=True", "test_candidate_v02.CandidateTests.test_frozen_allocation_validation_and_no_intent_hold"),
    ("baseline_future_metadata_restored", "provider_adapter.py", "('context', 'purpose', 'writing_style', 'topic')", "('context', 'purpose', 'writing_style', 'topic', 'mutations')", "test_nous_chat.NousTests.test_baseline_excludes_future_mutations_and_controller_metadata"),
    ("responses_rate_guard_removed", "openai_responses.py", "raise ValueError('this provider requires fixed published standard rates; overrides unsupported')", "pass", "test_openai_responses.ResponsesTests.test_fixed_rates_and_resume_settings_are_bound"),
    ("nonterminal_precedence_removed", "openai_responses.py", "if status not in {'completed','incomplete','failed','cancelled'}:outcome='uncertain'", "if False:outcome='uncertain'", "test_openai_responses.ResponsesTests.test_nonterminal_output_cannot_release_uncertain_reservation"),
    ("ledger_nested_cache_alias", "ledger.py", 'data = json.loads(canonical(data))  # Detach caller-owned nested values before caching.', 'data = data', "test_execution_quality.QualityTests.test_cached_append_detaches_nested_caller_data"),
    ("relation_add_guard_removed", "relations.py", "elif label in hypothesis['add_labels']:", 'elif False:', "test_execution_quality.QualityTests.test_add_remove_preserve_uncertainty_and_collateral_effects"),
    ("collateral_change_ignored", "relations.py", "result='pass' if before==after else 'fail'", "result='pass'", "test_execution_quality.QualityTests.test_add_remove_preserve_uncertainty_and_collateral_effects"),
    ("same_family_dedup_exemption_removed", "duplicates.py", "if pair['cross_family']:", 'if True:', "test_execution_quality.QualityTests.test_duplicate_cross_family_clusters_and_same_family_exemption"),
    ("dedup_family_quarantine_removed", "duplicates.py", "r['family_id'] in families", "r['id'] in quarantine", "test_execution_quality.QualityTests.test_duplicate_cross_family_clusters_and_same_family_exemption"),
    ("relation_delete_regenerated", "pipeline.py", "if not (run_dir / 'relations' / f'{rid}.json').is_file():", 'if False:', "test_execution_quality.QualityTests.test_missing_relation_evidence_blocks_resume_before_calls"),
    ("live_adapter_guard_removed", "provider_adapter.py", "raise DispatchNotAuthorized('live terms, billing, provider integration and explicit spend authorization unresolved')", 'return None', "test_execution_quality.AdapterTests.test_blind_request_and_explicit_inclusive_usage_cost"),
    ("casefold_id_guard_removed", "planning.py", 'or fid.casefold() in ids:', 'or fid in ids:', "test_planning.PlanningTests.test_casefolded_family_ids_rejected_on_all_platforms"),
    ("candidate_consistency_removed", "planning.py", 'requested_candidates is not None and integer(requested_candidates, \'requested_candidates\', minimum=1) != requested', 'False', "test_planning.PlanningTests.test_count_consistency_rejects_before_manifest"),
    ("semantic_clone_guard_removed", "planning.py", 'if semantic_key in semantics:', 'if False:', "test_planning.PlanningTests.test_topic_and_id_renaming_not_diversity"),
    ("manifest_hash_guard_removed", "pipeline.py", 'if len(planned) != 1 or planned[0]["data"]["manifest_hash"] != digest(manifest):', 'if False:', "test_planning.PlanningTests.test_manifest_mutation_and_source_change_resume_invariants"),
    ("reasoning_budget_omitted", "planning.py", "totals['visible_output_tokens'] + totals['reasoning_tokens']", "totals['visible_output_tokens']", "test_planning.PlanningTests.test_case_specific_budget_reasoning_and_optional_bounds"),
    ("unknown_becomes_accepted", "contracts.py", 'j["decision"] == "unknown"', 'j["decision"] == "absent"', "test_contracts.ReviewTests.test_all_unknown_vector_is_held"),
    ("all_negative_rejected", "contracts.py", 'return "accepted"', 'return "held"', "test_contracts.ReviewTests.test_all_negative_is_valid_and_accepted_without_spans"),
    ("positive_without_evidence", "contracts.py", 'if item["decision"] == "present" and not item["evidence"]:', 'if False:', "test_contracts.ReviewTests.test_positive_needs_literal_span_and_labels_remain_separate"),
    ("budget_guard_removed", "ledger.py", 'if committed + amount_micro > self.cap_micro:', 'if False:', "test_ledger.LedgerTests.test_cap_refuses_request_without_changing_balance"),
    ("usage_mutation_allowed", "ledger.py", 'if settlements[attempt_id] != actual_micro:', 'if False:', "test_ledger.LedgerTests.test_already_settled_usage_cannot_be_changed"),
]


def main():
    outcomes = []
    for name, module, before, after, test in MUTATIONS:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "email_corpus_forge", root / "email_corpus_forge", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(ROOT / "tests", root / "tests", ignore=shutil.ignore_patterns("__pycache__"))
            path = root / "email_corpus_forge" / module
            source = path.read_text()
            if source.count(before) != 1:
                raise RuntimeError(f"mutation target drift: {name}")
            path.write_text(source.replace(before, after))
            result = subprocess.run([sys.executable, "-m", "unittest", test], cwd=root / "tests", env={**__import__('os').environ, "PYTHONPATH": str(root)}, capture_output=True, text=True)
            killed = result.returncode != 0 and ("FAIL:" in result.stderr or "ERROR:" in result.stderr) and "Ran 1 test" in result.stderr
            outcomes.append({"mutation": name, "test": test, "killed": killed, "exit_code": result.returncode})
    print(json.dumps(outcomes, indent=2))
    return 0 if all(item["killed"] for item in outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
