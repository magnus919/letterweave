"""Consistent hashes do not establish terminal or matching review evidence."""
import json
from pathlib import Path
import unittest

import test_model_provenance_release
from email_corpus_forge.contracts import canonical,digest
from email_corpus_forge.ledger import Ledger
from test_execution_quality import review


class ModelReviewEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.helper=test_model_provenance_release.ModelProvenanceAssemblyTests()
        self.helper.setUp();self.addCleanup(self.helper.doCleanups)

    def rewrite_fixture_evidence(self,run,mutate):
        """Construct internally hash-consistent synthetic tampering, never live edits."""
        manifest=json.loads((run/'manifest.json').read_text())
        events=Ledger(run,manifest['cap_micro']).events()
        path=next((run/'raw').glob('*-review.json'));envelope=json.loads(path.read_text())
        mutate(envelope['response']);envelope['response_hash']=digest(envelope['response'])
        path.write_bytes(canonical(envelope)+b'\n')
        for event in events:
            if event['kind'] in {'raw_written','completed'} and event['data'].get('attempt_id')==envelope['attempt_id']:
                event['data']['raw_hash']=digest(envelope)
        previous='0'*64
        for number,event in enumerate(events):
            event.pop('hash');event['previous']=previous;event['sequence']=number
            event['hash']=digest(event);previous=event['hash']
        (run/'ledger.jsonl').write_bytes(b''.join(canonical(event)+b'\n' for event in events))
        # Prove the regression is beyond ordinary hash-chain corruption checks.
        self.assertEqual(len(Ledger(run,manifest['cap_micro']).events()),len(events))

    def test_completed_settled_anchors_do_not_make_uncertain_review_releasable(self):
        run,transport=self.helper.build_source()
        def uncertain(response):
            response['outcome']='uncertain'
            response['raw_response']['choices'][0]['finish_reason']=None
        self.rewrite_fixture_evidence(run,uncertain)
        with self.assertRaises((ValueError,RuntimeError)):
            self.helper.assemble(run,self.helper.root/'release')
        self.assertFalse((self.helper.root/'release').exists())
        self.assertEqual(len(transport.create_calls),2)

    def test_hash_consistent_valid_review_must_match_saved_review_history(self):
        run,transport=self.helper.build_source()
        def alternative(response):
            text=json.dumps(review())
            response['text']=text
            response['raw_response']['choices'][0]['message']['content']=text
        self.rewrite_fixture_evidence(run,alternative)
        with self.assertRaises((ValueError,RuntimeError)):
            self.helper.assemble(run,self.helper.root/'release')
        self.assertFalse((self.helper.root/'release').exists())
        self.assertEqual(len(transport.create_calls),2)

    def test_raw_nonterminal_finish_overrides_stored_completed_content_claim(self):
        run,transport=self.helper.build_source()
        self.rewrite_fixture_evidence(run,lambda response:response['raw_response']['choices'][0].update(finish_reason=None))
        with self.assertRaises((ValueError,RuntimeError)):
            self.helper.assemble(run,self.helper.root/'release')
        self.assertFalse((self.helper.root/'release').exists())
        self.assertEqual(len(transport.create_calls),2)

    def test_raw_usage_must_match_stored_normalized_usage(self):
        run,transport=self.helper.build_source()
        def change_usage(response):
            response['raw_response']['usage']['prompt_tokens']+=1
            response['raw_response']['usage']['total_tokens']+=1
        self.rewrite_fixture_evidence(run,change_usage)
        with self.assertRaises((ValueError,RuntimeError)):
            self.helper.assemble(run,self.helper.root/'release')
        self.assertFalse((self.helper.root/'release').exists())
        self.assertEqual(len(transport.create_calls),2)


if __name__=='__main__':unittest.main()
