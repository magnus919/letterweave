"""External unresolved evidence fixtures are disposable and never real API calls."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import test_live_release
import test_model_provenance_release
from email_corpus_forge.contracts import LABELS,canonical,digest
from email_corpus_forge.ledger import Ledger,IntegrityError,write_once,exclusive_lock
from email_corpus_forge.pipeline import create_plan,run_pipeline
from email_corpus_forge.nous_roles import RoleRoutedNousProvider,LUNA_MODEL,LUNA_CANONICAL_MODEL
from email_corpus_forge.nous_chat import CANONICAL_MODEL
from email_corpus_forge.openai_responses import PrivatePilotAuthorization
from test_openai_responses import OfflineTransport
from test_nous_chat import chat
from test_execution_quality import review
from test_planning import inventory


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def rewrite_chain(run,events):
    previous='0'*64
    for n,event in enumerate(events):
        event.pop('hash',None);event['sequence']=n;event['previous']=previous
        event['hash']=digest(event);previous=event['hash']
    (run/'ledger.jsonl').write_bytes(b''.join(canonical(e)+b'\n' for e in events))


class ExternalUncertaintyTests(unittest.TestCase):
    def setUp(self):
        self.helper=test_live_release.LiveReleaseTests();self.helper.setUp();self.addCleanup(self.helper.doCleanups)
        self.root=self.helper.root;self.original=self.root/'original';self.new=self.root/'partition'
        source=self.root/'plan.json';source.write_text(json.dumps(inventory(2)))
        options=dict(scenario_plan=source,provider_mode='live',live_provider='nous-chat',generation_model=LUNA_MODEL,variants_per_family=1,max_repairs=0,max_rereviews=0)
        original_manifest=create_plan(self.original,**options)
        body='Please reply about the map.';vector=review();vector['judgments'][LABELS[0]].update(decision='present',evidence=[body])
        error={'id':'offline401','model':LUNA_MODEL,'choices':[],'usage':None,'error':{'status_code':401,'type':'offline'}}
        transport=OfflineTransport([chat(json.dumps({'subject':'Map','body':body}),model=LUNA_CANONICAL_MODEL),chat(json.dumps(vector),model=CANONICAL_MODEL),error])
        transport.is_offline_fixture=False
        auth=PrivatePilotAuthorization(digest(original_manifest),'offline external test',10000000,True,True,True)
        with self.assertRaises(IntegrityError):run_pipeline(self.original,RoleRoutedNousProvider(transport,authorization=auth))
        original_ledger=Ledger(self.original,original_manifest['cap_micro']);events=original_ledger.events()
        settled={e['data']['attempt_id'] for e in events if e['kind']=='settled'}
        pending=next(e['data'] for e in events if e['kind']=='dispatched' and e['data']['attempt_id'] not in settled)
        attempt=pending['attempt_id'];raw=self.original/'raw'/f'{attempt}.json';record_id=attempt.removesuffix('-generate')
        self.ref={'attempt_id':attempt,'record_id':record_id,'reservation_micro':5700,'source_run':'../original',
                  'source_manifest_hash':digest(original_manifest),'source_ledger_sha256':sha(self.original/'ledger.jsonl'),
                  'source_raw_sha256':sha(raw),'packet_hash':pending['packet_hash']}
        new_manifest=create_plan(self.new,**options);new_manifest['external_uncertainties']=[self.ref]
        (self.new/'manifest.json').write_bytes(canonical(new_manifest)+b'\n')
        new_ledger=Ledger(self.new,new_manifest['cap_micro']);new_events=new_ledger.events();new_events[0]['data']['manifest_hash']=digest(new_manifest);rewrite_chain(self.new,new_events)
        new_ledger=Ledger(self.new,new_manifest['cap_micro'])
        for event in events:
            if event['kind']=='planned' or event['data'].get('attempt_id')==attempt:continue
            data=copy.deepcopy(event['data'])
            if event['kind']=='private_pilot_authorized':data['manifest_hash']=digest(new_manifest)
            new_ledger.append(event['kind'],**data)
        shutil.copytree(self.original/'records',self.new/'records')
        (self.new/'raw').mkdir()
        for path in (self.original/'raw').glob('*.json'):
            if path!=raw:shutil.copy2(path,self.new/'raw'/path.name)
        accepted=json.loads(next((self.new/'records').glob('*.json')).read_text())
        scenario=next(s for s in new_manifest['scenarios'] if record_id.startswith(s['family_id']+'-'))
        held={**accepted,'id':record_id,'family_id':scenario['family_id'],'split':scenario['split'],'content':None,
              'intended_labels':scenario['intended_labels'],'reviews':[],'reviewed_labels':None,'disposition':'held',
              'reason':'external unresolved outcome; no retry','generation_skipped':True,'content_origin':'not_generated',
              'external_uncertainty_ref':self.ref,'lineage_root':record_id,'parent_id':None,'variant':0}
        write_once(self.new/'records'/f'{record_id}.json',held);new_ledger.append('record_saved',record_id=record_id,record_hash=digest(held))
        self.original_bytes={p:p.read_bytes() for p in self.original.rglob('*') if p.is_file() and p.name not in {'.run.lock','.ledger.lock'}}

    def assemble(self):
        return test_model_provenance_release.tool('assemble_model_release').assemble_model_release([self.new],self.root/'release',authorization=self.helper.authorization())

    def mutate_reference(self,mutate):
        manifest=json.loads((self.new/'manifest.json').read_text());mutate(manifest['external_uncertainties'])
        (self.new/'manifest.json').write_bytes(canonical(manifest)+b'\n')
        events=Ledger(self.new,manifest['cap_micro']).events();events[0]['data']['manifest_hash']=digest(manifest)
        held_path=self.new/'records'/f"{self.ref['record_id']}.json"
        held=json.loads(held_path.read_text());held['external_uncertainty_ref']=manifest['external_uncertainties'][0]
        held_path.write_bytes(canonical(held)+b'\n')
        for event in events:
            if event['kind']=='record_saved' and event['data']['record_id']==held['id']:
                event['data']['record_hash']=digest(held)
        rewrite_chain(self.new,events)

    def test_valid_release_counts_unknown_and_preserves_original_bytes(self):
        result=self.assemble()
        self.assertEqual(result['accepted_count'],1);self.assertEqual(result['source_candidate_count'],2)
        self.assertEqual(result['external_unresolved_attempt_count'],1);self.assertEqual(result['external_unresolved_reservations_micro'],5700)
        self.assertTrue(all(p.read_bytes()==data for p,data in self.original_bytes.items()))
        self.assertTrue(test_model_provenance_release.tool('verify_dataset').verify_dataset(self.root/'release')['verified'])

    def test_reanchored_reference_hash_tamper_rejected(self):
        self.mutate_reference(lambda refs:refs[0].update(source_raw_sha256='0'*64))
        with self.assertRaises((ValueError,RuntimeError)):self.assemble()

    def test_duplicate_reference_rejected_even_when_manifest_reanchored(self):
        self.mutate_reference(lambda refs:refs.append(copy.deepcopy(refs[0])))
        with self.assertRaises((ValueError,RuntimeError)):self.assemble()

    def test_reference_reservation_mismatch_rejected(self):
        self.mutate_reference(lambda refs:refs[0].update(reservation_micro=5699))
        with self.assertRaises((ValueError,RuntimeError)):self.assemble()

    def test_original_settled_after_snapshot_rejected(self):
        ledger=Ledger(self.original);ledger.settle(self.ref['attempt_id'],0)
        self.mutate_reference(lambda refs:refs[0].update(source_ledger_sha256=sha(self.original/'ledger.jsonl')))
        with self.assertRaises((ValueError,RuntimeError)):self.assemble()

    def rehash_release(self):
        directory=self.root/'release';checker=test_model_provenance_release.tool('verify_dataset')
        (directory/'checksums.json').write_text(json.dumps({name:sha(directory/name) for name in checker.PAYLOAD}))

    def test_public_verifier_missing_external_pair_rejected(self):
        self.assemble();directory=self.root/'release'
        manifest=json.loads((directory/'manifest.json').read_text());manifest.pop('external_unresolved_reservations_micro')
        (directory/'manifest.json').write_text(json.dumps(manifest));self.rehash_release()
        with self.assertRaises(ValueError):test_model_provenance_release.tool('verify_dataset').verify_dataset(directory)

    def test_public_verifier_boolean_external_count_rejected(self):
        self.assemble();directory=self.root/'release'
        manifest=json.loads((directory/'manifest.json').read_text());manifest['external_unresolved_attempt_count']=True
        (directory/'manifest.json').write_text(json.dumps(manifest));self.rehash_release()
        with self.assertRaises(ValueError):test_model_provenance_release.tool('verify_dataset').verify_dataset(directory)

    def test_guard_works_under_active_selected_run_lock(self):
        wrapper=test_model_provenance_release.tool('assemble_model_release')
        with exclusive_lock(self.new/'.run.lock',nonblocking=True):
            result=wrapper.validate_external_uncertainties([self.new],already_locked_run_dirs=[self.new])
        self.assertEqual(result,{'count':1,'reservation_micro':5700})
        self.assertTrue(all(p.read_bytes()==data for p,data in self.original_bytes.items()))

    def test_lock_exemption_outside_selected_runs_rejected(self):
        wrapper=test_model_provenance_release.tool('assemble_model_release')
        with self.assertRaises((ValueError,RuntimeError)):
            wrapper.validate_external_uncertainties([self.new],already_locked_run_dirs=[self.original])


if __name__=='__main__':unittest.main()
