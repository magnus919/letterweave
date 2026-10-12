"""Standalone checker fixtures are software tests, never a corpus."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('standalone_dataset_verification',ROOT/'tools/verify_dataset.py')
checker=importlib.util.module_from_spec(spec);spec.loader.exec_module(checker)


class DatasetVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.sourcehash='a'*64
        inputs=[{'subject':'Fixture','body':'Offline software test text.'} for _ in range(2)]
        labels=[{'row':n,'id':'r'+str(n),'labels':[], 'decisions':{l:'absent' for l in checker.LABELS}} for n in range(2)]
        provenance=[{'row':n,'id':'r'+str(n),'family_id':'f','split':'development_planned','slice':'ordinary','variant':n,
                     'parent_id':None,'lineage_root':'r0','source_manifest_hash':self.sourcehash,
                     'controlled_transition_included':False,'pool':'off_target'} for n in range(2)]
        for name,rows in [('inputs.jsonl',inputs),('labels.jsonl',labels),('provenance.jsonl',provenance)]:
            self.write_rows(name,rows)
        rubric={'version':'0.4.0','purpose':'Offline software test rubric.'}
        manifest={'contract_version':'0.4.0','rubric_hash':hashlib.sha256(checker.canonical(rubric)).hexdigest(),'kind':'fresh_synthetic_machine_labeled_not_gold','gold_labels':False,
                  'semantic_equivalence_established':False,'license':'MIT','rights_holder':'Example author',
                  'terms_evidence':'Offline test assertion','publication_reference':'test','sources':[{'manifest_hash':self.sourcehash,'requested_candidates':2,'family_count':1}],
                  'accepted_count':2,'excluded_count':0,'source_candidate_count':2,'source_family_count':1,'controlled_transition_count':0}
        (self.root/'manifest.json').write_text(json.dumps(manifest))
        (self.root/'taxonomy.json').write_text(json.dumps({'version':'0.4.0','labels':sorted(checker.LABELS),'rubric':rubric}))
        (self.root/'DATA_LICENSE.txt').write_text((ROOT/'LICENSE').read_text())
        (self.root/'DATA_CARD.md').write_text('Synthetic machine-labeled, not gold. Offline fixture only.')
        self.rehash()

    def write_rows(self,name,rows):
        (self.root/name).write_text(''.join(json.dumps(row)+'\n' for row in rows))

    def change(self,name,mutate):
        rows=[json.loads(line) for line in (self.root/name).read_text().splitlines()];mutate(rows);self.write_rows(name,rows);self.rehash()

    def rehash(self):
        (self.root/'checksums.json').write_text(json.dumps({name:hashlib.sha256((self.root/name).read_bytes()).hexdigest() for name in checker.PAYLOAD}))

    def test_valid_binary_all_negative_fixture_verifies_without_gold_claim(self):
        result=checker.verify_dataset(self.root)
        self.assertEqual(result['accepted_count'],2);self.assertFalse(result['semantic_quality_verified'])

    def test_corrupted_checksum_rejected(self):
        (self.root/'DATA_CARD.md').write_text('altered')
        with self.assertRaises(ValueError):checker.verify_dataset(self.root)

    def test_rehashed_misaligned_rows_rejected(self):
        self.change('labels.jsonl',lambda rows:rows[1].update(row=0))
        with self.assertRaises(ValueError):checker.verify_dataset(self.root)

    def test_rehashed_unknown_decision_rejected(self):
        self.change('labels.jsonl',lambda rows:rows[0]['decisions'].update(correspondence='unknown'))
        with self.assertRaises(ValueError):checker.verify_dataset(self.root)

    def test_rehashed_family_split_leak_rejected(self):
        self.change('provenance.jsonl',lambda rows:rows[1].update(split='test_planned'))
        with self.assertRaises(ValueError):checker.verify_dataset(self.root)

    def test_rehashed_unapproved_source_hash_rejected(self):
        self.change('provenance.jsonl',lambda rows:rows[0].update(source_manifest_hash='b'*64))
        with self.assertRaises(ValueError):checker.verify_dataset(self.root)

    def test_rehashed_input_metadata_and_secret_rejected(self):
        self.change('inputs.jsonl',lambda rows:rows[0].update(intended_labels=[]))
        with self.assertRaises(ValueError):checker.verify_dataset(self.root)
        self.change('inputs.jsonl',lambda rows:rows[0].pop('intended_labels'))
        self.change('inputs.jsonl',lambda rows:rows[0].update(body='Bearer '+('a'*30)))
        with self.assertRaises(ValueError):checker.verify_dataset(self.root)

    def test_extra_payload_and_symlink_rejected(self):
        (self.root/'raw.json').write_text('{}')
        with self.assertRaises(ValueError):checker.verify_dataset(self.root)
        (self.root/'raw.json').unlink();(self.root/'inputs.jsonl').unlink();(self.root/'inputs.jsonl').symlink_to(ROOT/'LICENSE')
        with self.assertRaises(ValueError):checker.verify_dataset(self.root)

    def tamper_object(self,name,mutate):
        value=json.loads((self.root/name).read_text());mutate(value)
        (self.root/name).write_text(json.dumps(value));self.rehash()

    def test_rehashed_rubric_tamper_rejected(self):
        self.tamper_object('taxonomy.json',lambda value:value['rubric'].update(purpose='Changed label semantics'))
        with self.assertRaisesRegex(ValueError,'rubric hash'):checker.verify_dataset(self.root)

    def test_rehashed_source_aggregate_counts_rejected(self):
        for field in ('requested_candidates','family_count'):
            original=json.loads((self.root/'manifest.json').read_text())
            self.tamper_object('manifest.json',lambda value:value['sources'][0].update({field:99}))
            with self.assertRaisesRegex(ValueError,'source aggregate'):checker.verify_dataset(self.root)
            (self.root/'manifest.json').write_text(json.dumps(original));self.rehash()

    def test_rehashed_controlled_count_rejected(self):
        self.tamper_object('manifest.json',lambda value:value.update(controlled_transition_count=1))
        with self.assertRaisesRegex(ValueError,'controlled transition count'):checker.verify_dataset(self.root)

    def test_boolean_source_count_and_nonboolean_controlled_flag_rejected(self):
        original=json.loads((self.root/'manifest.json').read_text())
        self.tamper_object('manifest.json',lambda value:value['sources'][0].update(family_count=True))
        with self.assertRaisesRegex(ValueError,'invalid source count'):checker.verify_dataset(self.root)
        (self.root/'manifest.json').write_text(json.dumps(original));self.rehash()
        self.change('provenance.jsonl',lambda rows:rows[0].update(controlled_transition_included=1))
        with self.assertRaisesRegex(ValueError,'invalid controlled transition flag'):checker.verify_dataset(self.root)

    def test_rehashed_self_parent_controlled_record_rejected(self):
        self.change('provenance.jsonl',lambda rows:rows[1].update(parent_id='r1',controlled_transition_included=True))
        self.tamper_object('manifest.json',lambda value:value.update(controlled_transition_count=1))
        with self.assertRaisesRegex(ValueError,'self-parent'):checker.verify_dataset(self.root)

    def test_rehashed_two_record_cycle_rejected(self):
        def cycle(rows):
            rows[0].update(variant=1,parent_id='r1',controlled_transition_included=True)
            rows[1].update(variant=2,parent_id='r0',controlled_transition_included=True)
        self.change('provenance.jsonl',cycle)
        self.tamper_object('manifest.json',lambda value:value.update(controlled_transition_count=2))
        with self.assertRaisesRegex(ValueError,'variant lineage'):checker.verify_dataset(self.root)

    def test_valid_controlled_parent_child_passes(self):
        self.change('provenance.jsonl',lambda rows:rows[1].update(parent_id='r0',controlled_transition_included=True))
        self.tamper_object('manifest.json',lambda value:value.update(controlled_transition_count=1))
        self.assertTrue(checker.verify_dataset(self.root)['verified'])

    def test_boolean_variant_and_inconsistent_lineage_root_rejected(self):
        original=[json.loads(line) for line in (self.root/'provenance.jsonl').read_text().splitlines()]
        self.change('provenance.jsonl',lambda rows:rows[1].update(variant=True))
        with self.assertRaisesRegex(ValueError,'variant number'):checker.verify_dataset(self.root)
        self.write_rows('provenance.jsonl',original);self.rehash()
        self.change('provenance.jsonl',lambda rows:rows[1].update(parent_id='r0',lineage_root='other'))
        with self.assertRaisesRegex(ValueError,'root leakage'):checker.verify_dataset(self.root)

    def test_missing_excluded_parent_legal_when_not_controlled(self):
        self.change('provenance.jsonl',lambda rows:rows[1].update(parent_id='excluded-parent',controlled_transition_included=False))
        self.assertTrue(checker.verify_dataset(self.root)['verified'])


if __name__=='__main__':unittest.main()
