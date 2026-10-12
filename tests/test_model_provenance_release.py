"""Offline accepted-row model lineage tests; mock origins are not real API data."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import test_live_release
import test_dataset_verification
from email_corpus_forge.contracts import LABELS,digest
from email_corpus_forge.pipeline import create_plan,run_pipeline
from email_corpus_forge.nous_chat import NousChatProvider,MODEL,CANONICAL_MODEL
from email_corpus_forge.nous_roles import RoleRoutedNousProvider,LUNA_MODEL,LUNA_CANONICAL_MODEL
from email_corpus_forge.openai_responses import PrivatePilotAuthorization
from test_openai_responses import OfflineTransport
from test_nous_chat import chat
from test_execution_quality import review
from test_planning import inventory
from email_corpus_forge.ledger import Ledger

ROOT=Path(__file__).resolve().parents[1]
SOL_VERSION=CANONICAL_MODEL
LUNA_VERSION=LUNA_CANONICAL_MODEL


def tool(name):
    spec=importlib.util.spec_from_file_location('test_public_'+name,ROOT/'tools'/f'{name}.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


class ModelProvenanceVerificationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_dataset_verification.DatasetVerificationTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root;self.checker=tool('verify_dataset')
        rows=[json.loads(line) for line in (self.root/'provenance.jsonl').read_text().splitlines()]
        for row in rows:row.update(generation_model=LUNA_MODEL,generation_model_version=LUNA_VERSION,review_models=[MODEL],review_model_versions=[SOL_VERSION])
        self.fixture.write_rows('provenance.jsonl',rows)
        manifest=json.loads((self.root/'manifest.json').read_text())
        manifest.update(model_provenance_version=1,model_provenance_basis='accepted rows from immutable dispatch and raw response evidence')
        manifest['sources'][0].update(role_models={'generation':LUNA_MODEL,'review':MODEL},actual_generation_models=[LUNA_MODEL],actual_generation_model_versions=[LUNA_VERSION],actual_review_models=[MODEL],actual_review_model_versions=[SOL_VERSION])
        (self.root/'manifest.json').write_text(json.dumps(manifest));self.fixture.rehash()

    def test_luna_generation_sol_review_public_projection_verifies(self):
        self.assertTrue(self.checker.verify_dataset(self.root)['verified'])

    def test_rehashed_contradictory_generation_version_rejected(self):
        self.fixture.change('provenance.jsonl',lambda rows:rows[0].update(generation_model_version=SOL_VERSION))
        with self.assertRaises(ValueError):self.checker.verify_dataset(self.root)

    def test_rehashed_missing_model_field_rejected(self):
        self.fixture.change('provenance.jsonl',lambda rows:rows[0].pop('review_model_versions'))
        with self.assertRaises(ValueError):self.checker.verify_dataset(self.root)

    def test_rehashed_luna_review_rejected_even_if_aggregates_rewritten(self):
        self.fixture.change('provenance.jsonl',lambda rows:[r.update(review_models=[LUNA_MODEL],review_model_versions=[LUNA_VERSION]) for r in rows])
        self.fixture.tamper_object('manifest.json',lambda value:value['sources'][0].update(actual_review_models=[LUNA_MODEL],actual_review_model_versions=[LUNA_VERSION]))
        with self.assertRaises(ValueError):self.checker.verify_dataset(self.root)

    def test_rehashed_wrong_source_actual_set_rejected(self):
        self.fixture.tamper_object('manifest.json',lambda value:value['sources'][0].update(actual_generation_models=[MODEL]))
        with self.assertRaises(ValueError):self.checker.verify_dataset(self.root)


class ModelProvenanceAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.helper=test_live_release.LiveReleaseTests();self.helper.setUp();self.addCleanup(self.helper.doCleanups)
        self.root=self.helper.root

    def build_source(self,old_sol=False,unknown=False):
        directory=self.root/'run';source=self.root/'plan.json'
        plan=inventory(1);plan['families'][0]['intended_labels']=[LABELS[0]];source.write_text(json.dumps(plan))
        manifest=create_plan(directory,scenario_plan=source,provider_mode='live',live_provider='nous-chat',generation_model=LUNA_MODEL,variants_per_family=1,max_repairs=0,max_rereviews=0)
        body='Please reply with your thoughts on the map.'
        vector=review();vector['judgments'][LABELS[0]].update(decision='present',evidence=[body])
        if unknown:vector['judgments'][LABELS[0]].update(decision='unknown',evidence=[])
        gen_version=SOL_VERSION if old_sol else LUNA_VERSION
        transport=OfflineTransport([chat(json.dumps({'subject':'Map','body':body}),model=gen_version),chat(json.dumps(vector),model=SOL_VERSION)])
        transport.is_offline_fixture=False  # Explicit fake fresh-origin metadata for disposable tests only.
        auth=PrivatePilotAuthorization(digest(manifest),'offline-only',10000000,True,True,True)
        provider=NousChatProvider(transport,authorization=auth) if old_sol else RoleRoutedNousProvider(transport,authorization=auth)
        run_pipeline(directory,provider)
        self.assertEqual(len(transport.create_calls),2)
        return directory,transport

    def assemble(self,run,out):
        return tool('assemble_model_release').assemble_model_release([run],out,authorization=self.helper.authorization())

    def test_old_actual_sol_generation_is_not_rewritten_to_planned_luna(self):
        run,transport=self.build_source(old_sol=True);out=self.root/'release'
        self.assemble(run,out)
        row=json.loads((out/'provenance.jsonl').read_text())
        self.assertEqual(row['generation_model'],MODEL);self.assertEqual(row['generation_model_version'],SOL_VERSION)
        self.assertEqual(row['review_models'],[MODEL]);self.assertEqual(row['review_model_versions'],[SOL_VERSION])
        source=json.loads((out/'manifest.json').read_text())['sources'][0]
        self.assertEqual(source['role_models'],{'generation':LUNA_MODEL,'review':MODEL})
        self.assertEqual(source['actual_generation_models'],[MODEL])
        self.assertEqual(len(transport.create_calls),2)

    def test_luna_sol_provenance_does_not_change_input_or_label_bytes(self):
        from email_corpus_forge.release import assemble_live_release
        run,transport=self.build_source();base=self.root/'base';out=self.root/'release'
        assemble_live_release([run],base,authorization=self.helper.authorization())
        self.assemble(run,out)
        for name in ('inputs.jsonl','labels.jsonl'):
            self.assertEqual((out/name).read_bytes(),(base/name).read_bytes())
        row=json.loads((out/'provenance.jsonl').read_text())
        self.assertEqual(row['generation_model'],LUNA_MODEL);self.assertEqual(row['generation_model_version'],LUNA_VERSION)
        self.assertEqual(row['review_models'],[MODEL])
        all_text=''.join(p.read_text() for p in out.iterdir() if p.is_file())
        self.assertNotIn(str(self.root),all_text);self.assertNotIn('raw_response',all_text)
        self.assertEqual(len(transport.create_calls),2)
        self.assertTrue(tool('verify_dataset').verify_dataset(out)['verified'])

    def test_missing_raw_or_altered_raw_model_blocks_output(self):
        run,_=self.build_source();raw=next((run/'raw').glob('*-generate.json'));original=raw.read_bytes()
        raw.unlink()
        with self.assertRaises((ValueError,RuntimeError)):self.assemble(run,self.root/'missing')
        self.assertFalse((self.root/'missing').exists())
        raw.write_bytes(original);envelope=json.loads(original);envelope['response']['raw_response']['model']=SOL_VERSION;raw.write_text(json.dumps(envelope))
        with self.assertRaises((ValueError,RuntimeError)):self.assemble(run,self.root/'changed')
        self.assertFalse((self.root/'changed').exists())

    def test_existing_destination_preserved(self):
        run,_=self.build_source();out=self.root/'release';out.mkdir();(out/'marker').write_text('original')
        with self.assertRaises(FileExistsError):self.assemble(run,out)
        self.assertEqual((out/'marker').read_text(),'original')

    def test_duplicate_dispatch_anchor_is_not_silently_chosen(self):
        run,_=self.build_source();manifest=json.loads((run/'manifest.json').read_text())
        ledger=Ledger(run,manifest['cap_micro'])
        dispatched=next(e['data'] for e in ledger.events() if e['kind']=='dispatched' and e['data']['stage']=='generate')
        ledger.append('dispatched',**dispatched)
        with self.assertRaises((ValueError,RuntimeError)):self.assemble(run,self.root/'release')
        self.assertFalse((self.root/'release').exists())

    def test_zero_accepted_source_does_not_claim_observed_model_sets(self):
        run,transport=self.build_source(unknown=True);out=self.root/'release'
        result=self.assemble(run,out)
        self.assertEqual(result['accepted_count'],0)
        source=result['sources'][0]
        for field in ('actual_generation_models','actual_generation_model_versions','actual_review_models','actual_review_model_versions'):
            self.assertEqual(source[field],[])
        self.assertTrue(tool('verify_dataset').verify_dataset(out)['verified'])
        self.assertEqual(len(transport.create_calls),2)


if __name__=='__main__':unittest.main()
