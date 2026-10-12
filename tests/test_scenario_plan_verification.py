"""Rehashed tampering tests for public design hypotheses, never corpus data."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('public_plan_verifier',ROOT/'tools/verify_scenario_plans.py')
checker=importlib.util.module_from_spec(spec);spec.loader.exec_module(checker)


class ScenarioPlanVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'plans'
        shutil.copytree(ROOT/'scenario-plans/letterweave-0.1.0',self.root)

    def load(self,name):return json.loads((self.root/name).read_text())
    def save(self,name,value): (self.root/name).write_text(json.dumps(value))
    def rehash(self,stratum):
        meta=self.load('plan-checksums.json');meta['plans'][stratum]['canonical_sha256']=checker.digest(self.load(stratum+'-inventory.json'));self.save('plan-checksums.json',meta)

    def test_published_design_counts_verify_without_independence_claim(self):
        result=checker.verify_plans(self.root)
        self.assertEqual((result['planned_families'],result['planned_candidates']),(900,1000))
        self.assertFalse(result['semantic_diversity_verified']);self.assertFalse(result['gold_labels'])

    def test_inventory_edit_without_canonical_hash_update_rejected(self):
        plan=self.load('ordinary-inventory.json');plan['families'][0]['topic']='Changed topic';self.save('ordinary-inventory.json',plan)
        with self.assertRaisesRegex(ValueError,'canonical inventory hash'):checker.verify_plans(self.root)

    def test_rehashed_cross_stratum_family_duplicate_rejected(self):
        ordinary=self.load('ordinary-inventory.json');challenge=self.load('challenge-inventory.json')
        challenge['families'][0]['family_id']=ordinary['families'][0]['family_id'].upper();self.save('challenge-inventory.json',challenge);self.rehash('challenge')
        with self.assertRaisesRegex(ValueError,'duplicate family across strata'):checker.verify_plans(self.root)

    def test_rehashed_semantic_clone_with_fresh_id_rejected(self):
        ordinary=self.load('ordinary-inventory.json');challenge=self.load('challenge-inventory.json')
        for key in ('context','purpose','writing_style'):
            challenge['families'][0][key]='  '+ordinary['families'][0][key].upper().replace(' ','  ')+'  '
        self.save('challenge-inventory.json',challenge);self.rehash('challenge')
        with self.assertRaisesRegex(ValueError,'design clone across strata'):checker.verify_plans(self.root)

    def test_rehashed_actual_family_count_mismatch_rejected(self):
        ordinary=self.load('ordinary-inventory.json');ordinary['families'].pop();self.save('ordinary-inventory.json',ordinary);self.rehash('ordinary')
        with self.assertRaisesRegex(ValueError,'actual family count'):checker.verify_plans(self.root)

    def test_rehashed_controlled_variant_missing_rejected(self):
        challenge=self.load('challenge-inventory.json');challenge['families'][0]['mutations']=[];self.save('challenge-inventory.json',challenge);self.rehash('challenge')
        with self.assertRaisesRegex(ValueError,'controlled variant count'):checker.verify_plans(self.root)

    def test_boolean_variant_count_does_not_equal_integer_one(self):
        meta=self.load('plan-checksums.json');meta['plans']['ordinary']['variants_per_family']=True;self.save('plan-checksums.json',meta)
        with self.assertRaisesRegex(ValueError,'declared stratum counts'):checker.verify_plans(self.root)

    def test_rehashed_private_path_and_credential_text_rejected(self):
        original=self.load('ordinary-inventory.json')
        for text in ('/Users/example/private/notes','Bearer '+('a'*30)):
            plan=json.loads(json.dumps(original));plan['families'][0]['context']=text;self.save('ordinary-inventory.json',plan);self.rehash('ordinary')
            with self.assertRaisesRegex(ValueError,'private path or credential'):checker.verify_plans(self.root)


if __name__=='__main__':unittest.main()
