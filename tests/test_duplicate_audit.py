"""Full-batch duplicate audit includes held and within-family fixture content."""
import unittest
from email_corpus_forge.duplicates import near_duplicates, validate_settings


def row(rid, family, body, disposition='held', subject=''):
    return {'id': rid, 'family_id': family, 'split': 'fixture',
            'disposition': disposition, 'reason': 'semantic uncertainty',
            'content': {'subject': subject, 'body': body}}


class DuplicateAuditTests(unittest.TestCase):
    def audit(self, rows, **settings):
        return near_duplicates(rows, validate_settings({'enabled': True, **settings}))

    def test_held_same_family_short_exact_is_reported_without_quarantine(self):
        report = self.audit([row('a', 'one', 'Meet Tuesday'), row('b', 'one', 'Meet Tuesday')])
        self.assertEqual(len(report['exact_pairs']), 1)
        self.assertEqual(len(report['normalized_exact_pairs']), 1)
        self.assertEqual(len(report['lexical_pairs']), 1)
        self.assertFalse(report['lexical_pairs'][0]['cross_family'])
        self.assertEqual(report['lexical_pairs'][0]['lexical_method'], 'bigram')
        self.assertEqual(report['short_records_audited'], 2)
        self.assertEqual(report['short_records_skipped'], 0)
        self.assertEqual(report['quarantine_ids'], [])

    def test_case_punctuation_normalized_match_is_not_literal_exact(self):
        report = self.audit([row('a', 'one', 'Meet Tuesday!'), row('b', 'two', 'meet TUESDAY?')])
        self.assertEqual(report['exact_pairs'], [])
        self.assertEqual(len(report['normalized_exact_pairs']), 1)
        self.assertEqual(report['quarantine_ids'], ['a', 'b'])

    def test_short_unigram_and_nonexact_bigram_are_audited(self):
        unigram = self.audit([row('a', 'one', 'Hello'), row('b', 'one', 'hello!')])
        self.assertEqual(unigram['lexical_pairs'][0]['lexical_method'], 'unigram')
        bigram = self.audit([row('a', 'one', 'alpha beta gamma'),
                             row('b', 'one', 'alpha beta gamma delta')], jaccard_ppm=500000)
        self.assertEqual(bigram['normalized_exact_pairs'], [])
        self.assertEqual(len(bigram['lexical_pairs']), 1)
        self.assertEqual(bigram['lexical_pairs'][0]['lexical_method'], 'bigram')
        self.assertEqual(bigram['quarantine_ids'], [])

    def test_pair_limits_are_honest_without_same_family_match_quarantine(self):
        rows = [row(str(n), 'one', 'hello there') for n in range(4)]
        report = self.audit(rows, max_edges=1)
        for field in ('exact_pairs', 'normalized_exact_pairs', 'lexical_pairs'):
            self.assertEqual(len(report[field]), 1)
        self.assertFalse(report['pair_lists_complete'])
        self.assertTrue(report['audit_limited_ids'])
        self.assertEqual(report['quarantine_ids'], [])

    def test_candidate_and_index_bounds_mark_incomplete_coverage(self):
        rows = [row(str(n), str(n), 'hello there') for n in range(5)]
        report = self.audit(rows, candidate_limit=1)
        self.assertLessEqual(report['comparisons'], len(rows))
        self.assertFalse(report['pair_lists_complete'])
        self.assertTrue(report['coverage_limited_ids'])
        self.assertLessEqual(report['exact_index_entries'], 100000)
        self.assertLessEqual(report['indexed_shingles'], 250000)

    def test_noncontent_is_counted_as_unreadable_not_silently_accepted(self):
        broken = row('b', 'two', 'unused'); broken['content'] = None
        report = self.audit([row('a', 'one', 'valid fixture'), broken])
        self.assertEqual(report['content_records_audited'], 1)
        self.assertEqual(report['unreadable_content_ids'], ['b'])


if __name__ == '__main__':
    unittest.main()
