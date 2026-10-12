"""Independent offline role-route and dispatch-binding specifications."""
import copy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from email_corpus_forge.contracts import blind_packet,digest
from email_corpus_forge.nous_roles import RoleRoutedNousProvider,LunaNousChatProvider,LUNA_MODEL,LUNA_CANONICAL_MODEL,ROLE_MODELS
from email_corpus_forge.nous_chat import MODEL as SOL_MODEL,CANONICAL_MODEL
from email_corpus_forge.openai_responses import PrivatePilotAuthorization
from email_corpus_forge.provider_adapter import DispatchNotAuthorized
from test_openai_responses import OfflineTransport
from test_nous_chat import chat
from email_corpus_forge.pipeline import _call,PendingOutcome
from email_corpus_forge.ledger import Ledger,IntegrityError,write_once


class NousRoleTests(unittest.TestCase):
    def generation(self):
        return {'scenario':{'context':'Example request','purpose':'Direct reply','writing_style':'Brief English','topic':'Maps'},'variant':0,'content_schema_version':'0.4.0'}
    def review(self):return blind_packet({'subject':'Appointment','body':'Please confirm.'})
    def provider(self,responses=(),manifest=None):
        transport=OfflineTransport(list(responses))
        auth=PrivatePilotAuthorization(digest(manifest or {}),'offline role approval',25000000,True,True,True,approved_cap_micro=25000000)
        return RoleRoutedNousProvider(transport,authorization=auth),transport

    def test_each_stage_selects_exact_ordinary_role_and_no_tools(self):
        p,_=self.provider()
        for stage in ('generate','mutate','repair','review','rereview','repair_review'):
            packet=self.review() if 'review' in stage else {'parent_content':{'subject':'A','body':'B'},'operation':{},'content_schema_version':'0.4.0'} if stage=='mutate' else self.generation()
            request=p.build_request(stage,packet)
            expected=SOL_MODEL if 'review' in stage else LUNA_MODEL
            self.assertEqual(request['model'],expected);self.assertEqual(p.model_for_stage(stage),expected)
            self.assertEqual(request['reasoning_effort'],'low');self.assertNotIn('tools',request)
        with self.assertRaises(DispatchNotAuthorized):p.model_for_stage('search')

    def test_exact_manifest_registry_required_even_with_valid_hash(self):
        valid={'provider_mode':'live','provider':'nous-chat','model':SOL_MODEL,'role_models':dict(ROLE_MODELS),'cap_micro':25000000}
        p,_=self.provider(manifest=valid);p.assert_run_authorized(valid)
        for changes in ({'role_models':{'generation':SOL_MODEL,'review':LUNA_MODEL}}, {'role_models':{}}, {'model':LUNA_MODEL}, {'provider':'other'}):
            manifest={**valid,**changes};p,_=self.provider(manifest=manifest)
            with self.assertRaises(DispatchNotAuthorized):p.assert_run_authorized(manifest)

    def test_prepared_packet_cannot_be_changed_or_reused(self):
        p,t=self.provider([chat(model=LUNA_MODEL)])
        packet=self.generation();p.prepare('generate',packet)
        self.assertEqual(p.model,LUNA_MODEL)
        changed=copy.deepcopy(packet);changed['scenario']['purpose']='different'
        with self.assertRaises(DispatchNotAuthorized):p.generate(changed)
        with self.assertRaises(DispatchNotAuthorized):p.prepare('review',self.review())
        self.assertEqual(t.create_calls,[])
        result=p.generate(packet);self.assertEqual(result.model,LUNA_MODEL)
        self.assertEqual(t.create_calls[0]['model'],LUNA_MODEL)
        self.assertEqual(p.model,SOL_MODEL)
        with self.assertRaises(DispatchNotAuthorized):p.generate(packet)
        self.assertEqual(len(t.create_calls),1)

    def test_review_cannot_execute_prepared_generation(self):
        p,t=self.provider();p.prepare('generate',self.generation())
        with self.assertRaises(DispatchNotAuthorized):p.review(self.review())
        self.assertEqual(t.create_calls,[])

    def test_mutated_child_settings_transport_or_dispatch_identity_fail_before_create(self):
        for mutation in ('rate','transport','dispatch_model'):
            p,t=self.provider();p.prepare('generate',self.generation())
            if mutation=='rate':p._children['generation'].output_rate=1
            elif mutation=='transport':p._children['generation'].transport=OfflineTransport([])
            else:p.model=SOL_MODEL
            with self.assertRaises(DispatchNotAuthorized):p.generate(self.generation())
            self.assertEqual(t.create_calls,[])

    def test_canonical_luna_identity_is_normalized_but_raw_evidence_unchanged(self):
        raw=chat(model=LUNA_CANONICAL_MODEL)
        p,t=self.provider([raw]);packet=self.generation();p.prepare('generate',packet)
        response=p.generate(packet)
        self.assertEqual(response.model,LUNA_MODEL);self.assertEqual(response.raw_response['model'],LUNA_CANONICAL_MODEL)
        self.assertEqual(response.request_payload['model'],LUNA_MODEL)
        self.assertEqual(p.cost_micro(response),123)

    def test_carried_sol_usage_keeps_sol_price_after_luna_route_selected(self):
        p,_=self.provider();sol=p._children['review'].normalize_response(chat(model=CANONICAL_MODEL))
        p.prepare('generate',self.generation())
        self.assertEqual(p.model,LUNA_MODEL);self.assertEqual(p.cost_micro(sol),2450)
        self.assertEqual(sol.raw_response['model'],CANONICAL_MODEL)

    def test_unknown_finish_preserves_uncertainty_and_real_identity(self):
        raw=chat(model=LUNA_CANONICAL_MODEL,finish=None)
        p,_=self.provider([raw]);packet=self.generation();p.prepare('generate',packet)
        response=p.generate(packet)
        self.assertEqual(response.outcome,'uncertain');self.assertEqual(response.raw_response,raw)
        self.assertEqual(response.model,LUNA_MODEL)

    def test_malicious_mismatched_model_never_rewritten_as_luna(self):
        raw=chat(model='unauthorized/model')
        p,_=self.provider([raw]);packet=self.generation();p.prepare('generate',packet)
        response=p.generate(packet)
        self.assertEqual(response.model,'unauthorized/model');self.assertEqual(response.raw_response['model'],'unauthorized/model')
        with self.assertRaises(ValueError):p.cost_micro(response)

    def test_luna_rejects_review_and_unapproved_reasoning(self):
        p,t=self.provider()
        with self.assertRaises(DispatchNotAuthorized):p._children['generation'].build_request('review',self.review())
        with self.assertRaises(ValueError):LunaNousChatProvider(t,reasoning_effort='medium')

    def test_ledger_luna_then_sol_dispatches_settle_with_actual_stage_identity(self):
        p,t=self.provider([chat(model=LUNA_CANONICAL_MODEL),chat(model=CANONICAL_MODEL)])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);ledger=Ledger(root)
            _call(root,ledger,p,'generation','generate',self.generation())
            self.assertEqual(p.model,SOL_MODEL)
            _call(root,ledger,p,'review','review',self.review())
            self.assertEqual(ledger.balance()['spent_micro'],123+2450)
            self.assertEqual(ledger.balance()['reserved_micro'],0)
            dispatches={e['data']['attempt_id']:e['data']['model'] for e in ledger.events() if e['kind']=='dispatched'}
            self.assertEqual(dispatches,{'generation':LUNA_MODEL,'review':SOL_MODEL})
            for attempt,model in dispatches.items():
                envelope=json.loads((root/'raw'/f'{attempt}.json').read_text())
                self.assertEqual(envelope['response']['model'],model)
            self.assertEqual([request['model'] for request in t.create_calls],[LUNA_MODEL,SOL_MODEL])

    def test_carried_unsettled_sol_generation_recovers_without_network_at_sol_price(self):
        p,t=self.provider()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);ledger=Ledger(root);packet=self.generation()
            response=p._children['review'].normalize_response(chat(model=CANONICAL_MODEL))
            payload=asdict(response)
            envelope={'attempt_id':'old-sol','stage':'generate','packet':packet,'packet_hash':digest(packet),
                      'response':payload,'response_hash':digest(payload)}
            ledger.reserve('old-sol',114000)
            ledger.append('dispatched',attempt_id='old-sol',stage='generate',packet_hash=digest(packet),provider='nous-chat',model=SOL_MODEL)
            write_once(root/'raw/old-sol.json',envelope)
            ledger.append('raw_written',attempt_id='old-sol',raw_hash=digest(envelope))
            self.assertEqual(_call(root,ledger,p,'old-sol','generate',packet),{})
            self.assertEqual(ledger.balance()['spent_micro'],2450)
            self.assertEqual(ledger.balance()['reserved_micro'],0)
            self.assertEqual(t.create_calls,[])
            self.assertEqual(t.count_calls,[])

    def test_uncertain_or_wrong_model_dispatch_keeps_reservation_and_raw_evidence(self):
        for raw,error in ((chat(model=LUNA_MODEL,finish=None),PendingOutcome),
                          (chat(model=SOL_MODEL),IntegrityError)):
            with self.subTest(raw_model=raw['model']),tempfile.TemporaryDirectory() as directory:
                p,t=self.provider([raw]);root=Path(directory);ledger=Ledger(root)
                with self.assertRaises(error):_call(root,ledger,p,'attempt','generate',self.generation())
                self.assertEqual(ledger.balance()['spent_micro'],0)
                self.assertEqual(ledger.balance()['reserved_micro'],5700)
                self.assertTrue((root/'raw/attempt.json').is_file())
                with self.assertRaises(error):_call(root,ledger,p,'attempt','generate',self.generation())
                self.assertEqual(len(t.create_calls),1)


if __name__=='__main__':unittest.main()
