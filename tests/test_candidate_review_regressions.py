"""Independent offline regressions for candidate 0.2 review findings."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from email_corpus_forge.assessments import record_projection
from email_corpus_forge.cli import main
from email_corpus_forge.contracts import LABELS
from email_corpus_forge.duplicates import validate_settings
from email_corpus_forge.ledger import Ledger
from email_corpus_forge.pipeline import _quality_records, create_plan, run_pipeline
from email_corpus_forge.providers import FixtureProvider, Response
from email_corpus_forge.relations import evaluate_relation, mutation_applicability
from test_execution_quality import review, relation_hypothesis
from test_planning import inventory


class IndependentCandidateRegressions(unittest.TestCase):
    def payment(self, body):
        return {'content': {'subject': 'Payment', 'body': body},
                'reviews': [review([LABELS[1]])]}

    def test_reordered_payment_facts_do_not_pass_any_preserve_operator(self):
        parent = self.payment('Alice paid Bob.')
        child = self.payment('Bob paid Alice.')
        for operator in ('arbitrary-rewrite', 'formatting-preserve'):
            hypothesis = relation_hypothesis()
            hypothesis['operator'] = operator
            result = evaluate_relation(parent, child, hypothesis)
            with self.subTest(operator=operator):
                self.assertEqual(result['label_relation'], 'pass')
                self.assertEqual(result['fact_preservation']['status'], 'fail' if operator == 'formatting-preserve' else 'indeterminate')
                self.assertFalse(result['local_checks_pass'])

    def test_declared_order_preserving_formatting_still_passes(self):
        parent = self.payment('Alice paid Bob.')
        child = self.payment('\nALICE paid Bob.\n')
        hypothesis = relation_hypothesis()
        hypothesis['operator'] = 'formatting-preserve'
        result = evaluate_relation(parent, child, hypothesis)
        self.assertEqual(result['result'], 'pass')
        self.assertFalse(result['fact_preservation']['semantic_fact_preservation_established'])

    def test_duplicate_quarantine_excludes_both_controlled_endpoints(self):
        parent = {**self.payment('Alice paid Bob.'), 'id': 'a-v0', 'family_id': 'a',
                  'split': 'train', 'variant': 0, 'parent_id': None,
                  'disposition': 'accepted', 'reason': 'complete',
                  'intended_labels': [LABELS[1]]}
        child = copy.deepcopy(parent)
        child.update(id='a-v1', variant=1, parent_id='a-v0')
        child['content']['body'] = '\nALICE paid Bob.\n'
        hypothesis = relation_hypothesis()
        hypothesis['operator'] = 'formatting-preserve'
        child['mutation_hypothesis'] = hypothesis
        duplicate = copy.deepcopy(parent)
        duplicate.update(id='b-v0', family_id='b', split='test')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            effective, relations, duplicates = _quality_records(root, Ledger(root),
                [parent, child, duplicate], {'near_duplicates': validate_settings({'enabled': True})})
        self.assertEqual(relations[0]['result'], 'pass')
        self.assertEqual(set(duplicates['quarantine_ids']), {'a-v0', 'a-v1', 'b-v0'})
        self.assertTrue(all(r['disposition'] == 'held' for r in effective))
        self.assertFalse(any(r['controlled_transition_included'] for r in effective))
        self.assertEqual(child['disposition'], 'accepted')

    def test_nested_rereview_allocation_returns_controlled_cli_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = inventory(1)
            value['rereview_allocation'] = [[]]
            source = root / 'plan.json'
            source.write_text(json.dumps(value))
            with patch('builtins.print'):
                result = main(['plan', '--run', str(root / 'run'), '--scenario-plan', str(source),
                    '--variants-per-family', '1', '--max-repairs', '0', '--max-rereviews', '1'])
            self.assertEqual(result, 2)
            self.assertFalse((root / 'run' / 'manifest.json').exists())

    def test_failed_review_projection_cannot_enable_mutation(self):
        parent = self.payment('Alice paid Bob.')
        parent['review_failure'] = 'malformed second response'
        projected = record_projection(parent)
        self.assertEqual(projected['label_validity'], 'held')
        self.assertEqual(projected['final_labels'], [])
        self.assertTrue(all(j['decision'] == 'unknown' for j in projected['final_judgments'].values()))
        self.assertEqual(projected['first_pass_judgments'][LABELS[1]]['decision'], 'present')
        self.assertEqual(mutation_applicability(parent, relation_hypothesis(add=[LABELS[4]]))['status'],
                         'indeterminate')

    def test_malformed_allocated_second_review_holds_final_projection_and_resume(self):
        class MalformedSecond(FixtureProvider):
            def review(self, packet):
                self.calls.append(('review', packet))
                count = sum(stage == 'review' for stage, _ in self.calls)
                return Response(json.dumps(review()) if count == 1 else '{}')

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = inventory(1)
            value['rereview_allocation'] = ['s00000-v0']
            source = root / 'plan.json'
            source.write_text(json.dumps(value))
            run = root / 'run'
            create_plan(run, scenario_plan=source, variants_per_family=1, max_repairs=0, max_rereviews=1)
            provider = MalformedSecond()
            result = run_pipeline(run, provider)
            saved = json.loads((run / 'records' / 's00000-v0.json').read_text())
            projected = record_projection(saved)
            self.assertEqual(result['counts'], {'accepted': 0, 'held': 1, 'rejected': 0})
            self.assertTrue(saved['review_failure'])
            self.assertEqual(len(saved['reviews']), 1)
            self.assertEqual(projected['label_validity'], 'held')
            self.assertTrue(all(j['decision'] == 'unknown' for j in projected['final_judgments'].values()))
            self.assertTrue(all(j['decision'] == 'absent' for j in projected['first_pass_judgments'].values()))
            resumed = MalformedSecond()
            self.assertEqual(run_pipeline(run, resumed), result)
            self.assertEqual(resumed.calls, [])


if __name__ == '__main__':
    unittest.main()
