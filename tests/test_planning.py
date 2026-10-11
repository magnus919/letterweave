"""Independent scenario count, lineage, budget and fail-closed acceptance criteria."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from email_corpus_forge.cli import main
from email_corpus_forge.contracts import LABELS
from email_corpus_forge.ledger import IntegrityError
from email_corpus_forge.pipeline import create_plan, load_manifest, run_pipeline, status_run, LiveProviderBlocked
from email_corpus_forge.planning import dollars_to_micro, stable_split
from email_corpus_forge.providers import FixtureProvider


def inventory(count=3):
    # Mechanical validator inputs, not genuine scenario diversity or corpus data.
    return {'schema_version': 1, 'diversity': {'description': 'Software-only planning stress inputs; semantics unverified'},
            'families': [{'family_id': f's{i:05d}', 'case': 'single', 'intended_labels': [LABELS[i % 7]],
                          'topic': f'fixture {i}', 'context': f'Artificial situation {i}',
                          'purpose': 'Test planner count', 'writing_style': 'Mechanical', 'slice': 'challenge'}
                         for i in range(count)]}


def mutation():
    return {'variant': 1, 'parent_variant': 0, 'operator': 'formatting-preserve', 'operator_version': '1',
            'changed_factors': ['surface spelling'], 'relation': 'preserve', 'add_labels': [], 'remove_labels': [],
            'invariant_labels': list(LABELS), 'uncertain_labels': [], 'rationale': 'Hypothesis, not oracle',
            'context_sufficiency': 'sufficient'}


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'scenarios.json'

    def plan(self, value=None, **options):
        self.source.write_text(json.dumps(value or inventory()))
        return create_plan(self.root / 'run', scenario_plan=self.source, max_repairs=0, max_rereviews=0, **options)

    def test_ten_thousand_candidates_plan_only(self):
        p = self.plan(inventory(2000), family_count=2000, variants_per_family=5, requested_candidates=10000,
                      provider_mode='live', cap_usd='125.50')
        self.assertEqual(p['message_count'], 10000)
        self.assertEqual(len(p['scenarios']), 2000)
        self.assertEqual(p['cap_micro'], 125500000)
        self.assertEqual(p['content_origin'], 'not_generated')
        self.assertFalse(p['scenario_diversity']['semantic_quality_verified'])
        report = status_run(self.root / 'run')
        self.assertEqual(report['requested_candidates'], 10000)
        self.assertEqual(report['processed'], 0)
        self.assertEqual(report['unattempted'], 10000)
        provider = FixtureProvider()
        with self.assertRaises(LiveProviderBlocked):
            run_pipeline(self.root / 'run', provider)
        self.assertEqual(provider.calls, [])
        self.assertFalse((self.root / 'run' / 'raw').exists())

    def test_fifty_thousand_candidate_plan_has_many_explicit_families(self):
        p = self.plan(inventory(10000), variants_per_family=5, requested_candidates=50000,
                      provider_mode='live')
        self.assertEqual(p['family_count'], 10000)
        self.assertEqual(p['requested_candidates'], 50000)
        self.assertEqual(len({s['family_id'] for s in p['scenarios']}), 10000)
        self.assertEqual(p['budget_estimate']['status'], 'token assumptions absent; dollar estimate unavailable')
        self.assertFalse((self.root / 'run' / 'raw').exists())

    def test_count_consistency_rejects_before_manifest(self):
        with self.assertRaises(ValueError):
            self.plan(family_count=4)
        self.assertFalse((self.root / 'run' / 'manifest.json').exists())
        with self.assertRaises(ValueError):
            self.plan(requested_candidates=16)
        self.assertFalse((self.root / 'run' / 'manifest.json').exists())

    def test_no_implicit_family_expansion(self):
        with self.assertRaises(ValueError):
            create_plan(self.root / 'run', family_count=2000)
        with self.assertRaises(ValueError):
            create_plan(self.root / 'other', provider_mode='live')

    def test_topic_and_id_renaming_not_diversity(self):
        value = inventory()
        value['families'][1].update({k: value['families'][0][k] for k in ('context', 'purpose', 'writing_style')})
        with self.assertRaises(ValueError):
            self.plan(value)

    def test_casefolded_family_ids_rejected_on_all_platforms(self):
        for first, second in [('A', 'a'), ('a', 'A')]:
            value = inventory(2)
            value['families'][0]['family_id'] = first
            value['families'][1]['family_id'] = second
            with self.subTest(first=first), self.assertRaises(ValueError):
                self.plan(value)
            self.assertFalse((self.root / 'run' / 'manifest.json').exists())

    def test_plan_validation_and_limits(self):
        mutations = [lambda p: p['families'][0].update(family_id='../unsafe'),
                     lambda p: p['families'][0].update(case='overlap'),
                     lambda p: p['families'][0].update(slice=[]),
                     lambda p: p['families'][0].update(intended_labels=[[]]),
                     lambda p: p.update(schema_version=True),
                     lambda p: p.update(coverage={'minimum_positive_families': {LABELS[6]: 1}})]
        for change in mutations:
            value = inventory(); change(value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.plan(value)
        for options in ({'seed': True}, {'variants_per_family': 0}, {'variants_per_family': 400000},
                        {'cap_usd': 'NaN'}, {'requested_candidates': True}, {'family_count': False}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.plan(**options)

    def test_stable_splits_order_extension_and_lineage(self):
        original = inventory()
        original['families'][0]['mutations'] = [mutation()]
        first = self.plan(original)
        self.source.write_text(json.dumps(inventory(4)))
        second = create_plan(self.root / 'second', scenario_plan=self.source, max_repairs=0, max_rereviews=0)
        self.assertEqual({s['family_id']: s['split'] for s in first['scenarios']},
                         {s['family_id']: s['split'] for s in second['scenarios'][:3]})
        self.assertEqual(first['scenarios'][0]['mutations'][0]['parent_variant'], 0)
        self.assertEqual(first['scenarios'][0]['split'], stable_split(17, 's00000'))
        original['families'].reverse()
        self.source.write_text(json.dumps(original))
        third = create_plan(self.root / 'third', scenario_plan=self.source, max_repairs=0, max_rereviews=0)
        self.assertEqual(first['scenarios'], third['scenarios'])

    def test_mutation_partition_and_parent_range(self):
        for field, value in [('parent_variant', 1), ('variant', 5), ('invariant_labels', []),
                             ('add_labels', [LABELS[0]]), ('relation', []), ('context_sufficiency', [])]:
            p = inventory(); m = mutation(); m[field] = value; p['families'][0]['mutations'] = [m]
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.plan(p)

    def test_manifest_mutation_and_source_change_resume_invariants(self):
        p = self.plan()
        self.source.write_text('{}')
        self.assertEqual(load_manifest(self.root / 'run'), p)  # Frozen manifest needs no external input.
        path = self.root / 'run' / 'manifest.json'
        p['cap_micro'] += 1; path.write_text(json.dumps(p))
        with self.assertRaises(IntegrityError):
            run_pipeline(self.root / 'run')

    def test_case_specific_budget_reasoning_and_optional_bounds(self):
        p = inventory(2)
        p['families'][1].update(case='overlap', intended_labels=list(LABELS[:2]))
        profiles = {case: {stage: {'input_tokens': k * 10, 'visible_output_tokens': k * 20, 'reasoning_tokens': k * 30}
                          for stage in ('generate', 'review', 'repair', 'repair_review', 'rereview')}
                    for case, k in [('single', 1), ('overlap', 2)]}
        p['token_budget'] = {'case_profiles': profiles,
                             'scenario_design_tokens': {'input_tokens': 10, 'visible_output_tokens': 20, 'reasoning_tokens': 30},
                             'rates_micro_usd_per_million_tokens': {'input': 2000000, 'output_including_reasoning': 10000000}}
        self.source.write_text(json.dumps(p))
        plan = create_plan(self.root / 'run', scenario_plan=self.source, variants_per_family=2,
                           max_repairs=1, max_rereviews=1, cap_usd='0.001')
        e = plan['budget_estimate']
        self.assertEqual(e['totals'], {'input_tokens': 190, 'visible_output_tokens': 380, 'reasoning_tokens': 570})
        self.assertEqual(e['billed_output_tokens'], 950)
        self.assertEqual(e['estimated_upper_micro'], 9880)
        self.assertTrue(e['envelope_exceeds_cap'])  # Advisory planning flag; never a permission to spend.
        self.assertEqual(plan['token_budget_assumptions'], p['token_budget'])

    def test_no_topup_and_provenance_separate_from_review(self):
        p = inventory(1); p['families'][0].update(case='missing_context', intended_labels=[], mutations=[mutation()])
        self.plan(p, variants_per_family=2)
        provider = FixtureProvider()
        report = run_pipeline(self.root / 'run', provider)
        self.assertEqual(report['requested_candidates'], 2)
        self.assertEqual(report['processed'], 2)
        self.assertEqual(report['counts'], {'accepted': 0, 'held': 2, 'rejected': 0})
        self.assertEqual(sum(stage == 'generate' for stage, _ in provider.calls), 1)
        self.assertEqual(sum(stage == 'mutate' for stage, _ in provider.calls), 0)
        self.assertEqual(report['slice_counts']['challenge']['held'], 2)
        for stage, packet in provider.calls:
            if stage == 'review':
                self.assertEqual(set(packet), {'record_id', 'rubric', 'subject', 'body', 'output_schema'})
        record = json.loads((self.root / 'run' / 'records' / 's00000-v1.json').read_text())
        self.assertEqual(record['mutation_hypothesis']['parent_variant'], 0)
        relation = json.loads((self.root / 'run' / 'relations' / 's00000-v1.json').read_text())
        self.assertEqual(relation['result'], 'indeterminate')

    def test_cli_controls_and_invalid_exit(self):
        self.source.write_text(json.dumps(inventory(2)))
        with patch('builtins.print'):
            code = main(['plan', '--run', str(self.root / 'run'), '--scenario-plan', str(self.source),
                         '--families', '2', '--variants-per-family', '3', '--requested-candidates', '6',
                         '--cap-usd', '2.50', '--max-repairs', '0', '--max-rereviews', '0', '--provider-mode', 'live'])
            self.assertEqual(code, 0)
            self.assertEqual(main(['run', '--run', str(self.root / 'run')]), 2)
        p = load_manifest(self.root / 'run')
        self.assertEqual(p['message_count'], 6)
        self.assertEqual(p['cap_micro'], 2500000)

    def test_cap_precision(self):
        self.assertEqual(dollars_to_micro('0.000001'), 1)
        for value in ('-1', '1e2', '0.0000001', 'Infinity', '1000001', 10, True):
            with self.assertRaises(ValueError):
                dollars_to_micro(value)


if __name__ == '__main__':
    unittest.main()
