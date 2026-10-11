"""Formatting preservation and unavailable-vs-uncertain reporting regressions."""
import json
from pathlib import Path
import tempfile
import unittest

from email_corpus_forge.assessments import validity_assessment
from email_corpus_forge.contracts import LABELS
from email_corpus_forge.pipeline import create_plan, run_pipeline
from email_corpus_forge.providers import FixtureProvider, Response
from email_corpus_forge.relations import fact_preservation, evaluate_relation
from test_execution_quality import review, relation_hypothesis
from test_planning import inventory


class CandidateV03Tests(unittest.TestCase):
    def parent(self):
        return {'content': {'subject': 'Receipt confirmed', 'body': 'Total 51.84. Payment is complete; do not repay.'},
                'reviews': [review([LABELS[1]])]}

    def formatting(self, anchors=True):
        hypothesis = relation_hypothesis()
        hypothesis['operator'] = 'formatting-preserve'
        hypothesis['preserve_facts'] = ['Total 51.84.'] if anchors else []
        return hypothesis

    def test_case_and_whitespace_formatting_with_normalized_anchor_passes(self):
        parent = self.parent()
        child = {'content': {'subject': '  RECEIPT   confirmed ',
                             'body': 'TOTAL  51.84.\nPayment is complete;  do not repay.\t'},
                 'reviews': [review([LABELS[1]])]}
        for anchors in (True, False):
            with self.subTest(anchors=anchors):
                result = evaluate_relation(parent, child, self.formatting(anchors))
                self.assertEqual(result['fact_preservation']['status'], 'pass')
                self.assertEqual(result['result'], 'pass')
                self.assertFalse(result['fact_preservation']['semantic_fact_preservation_established'])

    def test_formatting_cannot_hide_semantic_changes_behind_preserved_anchor(self):
        parent = self.parent()
        bodies = ('Total 51.84. Payment is complete; do repay.',
                  'Total 51.84. Payment is complete; do not repay!',
                  'Total 51.84. Complete is payment; do not repay.',
                  'Total 51.84. Payment is complete; do not repay. Additional charge 9.',
                  'Total 51.84. Payment is incomplete; do not repay.',
                  'Total 58.14. Payment is complete; do not repay.')
        for body in bodies:
            for anchors in (True, False):
                with self.subTest(body=body, anchors=anchors):
                    child = {'content': {'subject': parent['content']['subject'], 'body': body},
                             'reviews': [review([LABELS[1]])]}
                    result = evaluate_relation(parent, child, self.formatting(anchors))
                    self.assertIn(result['fact_preservation']['status'], ('fail', 'indeterminate'))
                    self.assertNotEqual(result['result'], 'pass')

    def test_nonformat_literal_anchor_remains_case_sensitive(self):
        parent = self.parent()
        child = {'content': {'subject': 'Receipt confirmed', 'body': 'TOTAL 51.84. plus offer'},
                 'reviews': [review([LABELS[1]])]}
        hypothesis = relation_hypothesis()
        hypothesis['preserve_facts'] = ['Total 51.84.']
        self.assertEqual(fact_preservation(parent, child, hypothesis)['status'], 'fail')

    def test_null_content_unavailable_but_actual_malformed_content_invalid(self):
        for content in (None,):
            self.assertEqual(validity_assessment({'content': content, 'reviews': []})['content_contract'], 'unavailable')
        for content in ({}, {'subject': 7, 'body': 'text'}, {'subject': '', 'body': ''}):
            with self.subTest(content=content):
                self.assertEqual(validity_assessment({'content': content, 'reviews': []})['content_contract'], 'invalid')

    def test_technical_rereview_failure_does_not_count_as_actual_unknown(self):
        class FailedSecondReview(FixtureProvider):
            def review(self, packet):
                self.calls.append(('review', packet))
                if sum(stage == 'review' for stage, _ in self.calls) == 1:
                    return Response(json.dumps(review()))
                return Response('{}')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.json'
            source.write_text(json.dumps(inventory(1)))
            create_plan(root/'run', scenario_plan=source, variants_per_family=1, max_repairs=0, max_rereviews=1)
            report = run_pipeline(root/'run', FailedSecondReview())
            self.assertEqual(report['diagnostics']['technical_contract_failure'], 1)
            self.assertTrue(all(support['unknown'] == 0 for support in report['per_label_support'].values()))

    def test_actual_unknown_is_reported_separately_from_technical_failure(self):
        class ActualUnknown(FixtureProvider):
            def review(self, packet):
                self.calls.append(('review', packet))
                return Response(json.dumps(review(unknown=[LABELS[0]])))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.json'; source.write_text(json.dumps(inventory(1)))
            create_plan(root/'run', scenario_plan=source, variants_per_family=1, max_repairs=0, max_rereviews=0)
            report = run_pipeline(root/'run', ActualUnknown())
            self.assertEqual(report['diagnostics']['technical_contract_failure'], 0)
            self.assertEqual(report['per_label_support'][LABELS[0]]['unknown'], 1)
            self.assertTrue(all(report['per_label_support'][label]['unknown'] == 0 for label in LABELS[1:]))


if __name__ == '__main__':
    unittest.main()
