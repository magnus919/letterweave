"""Offline provider wire-format and pipeline tests; these are not account access proof."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from email_corpus_forge.contracts import LABELS, CONTENT_SCHEMA, REVIEW_SCHEMA, RUBRIC, canonical, digest, blind_packet
from email_corpus_forge.ledger import IntegrityError
from email_corpus_forge.openai_responses import OpenAIResponsesProvider, PrivatePilotAuthorization, SDKResponsesTransport, MODEL
from email_corpus_forge.provider_adapter import DispatchNotAuthorized
from email_corpus_forge.pipeline import create_plan,run_pipeline,status_run,LiveProviderBlocked
from email_corpus_forge.providers import PHRASES
from test_planning import inventory
from test_execution_quality import review


def wire(text='{}',status='completed',output=None,usage=True):
    return {'id':'resp_offline','model':MODEL,'status':status,'error':None,'incomplete_details':None,
            'usage':{'input_tokens':100,'input_tokens_details':{'cached_tokens':0},'output_tokens':200,
                     'output_tokens_details':{'reasoning_tokens':50},'total_tokens':300} if usage else None,
            'output':output if output is not None else [{'type':'reasoning','id':'rs_offline','summary':[]},
                      {'type':'message','id':'msg_offline','role':'assistant','status':'completed',
                       'content':[{'type':'output_text','text':text,'annotations':[]}]}]}


class OfflineTransport:
    is_offline_fixture=True
    def __init__(self,responses,count=100):self.responses=list(responses);self.count_calls=[];self.create_calls=[];self.tokens=count
    def count(self,request):self.count_calls.append(copy.deepcopy(request));return self.tokens
    def create(self,request):
        self.create_calls.append(copy.deepcopy(request));result=self.responses.pop(0)
        if isinstance(result,Exception):raise result
        return result


class ResponsesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.run=self.root/'run'

    def plan(self,cap='10'):
        p=inventory(1);p['families'][0]['intended_labels']=[LABELS[0]]
        path=self.root/'scenarios.json';path.write_text(json.dumps(p))
        return create_plan(self.run,scenario_plan=path,provider_mode='live',variants_per_family=1,
                           max_repairs=0,max_rereviews=0,cap_usd=cap)

    def provider(self,responses,manifest=None,**kwargs):
        authority=PrivatePilotAuthorization(digest(manifest or {}),'offline-test-authority',10000000,
                          api_entitlement_verified=True,billing_verified=True,private_pilot_terms_reviewed=True)
        t=OfflineTransport(responses)
        return OpenAIResponsesProvider(t,authorization=authority,**kwargs),t

    def test_exact_responses_request_and_supported_wire_schema_local_contract(self):
        provider,t=self.provider([])
        packet=blind_packet({'subject':'Fixture','body':'English fixture'})
        request=provider.build_request('review',packet)
        self.assertEqual(request['model'],'gpt-6.1-sol')
        self.assertEqual(request['reasoning'],{'effort':'low'})
        self.assertEqual(request['input'],[{'role':'user','content':canonical(packet).decode()}])
        self.assertEqual(request['text']['format']['type'],'json_schema')
        self.assertTrue(request['text']['format']['strict'])
        self.assertNotIn('allOf',json.dumps(request['text']['format']['schema']))
        self.assertIn('allOf',json.dumps(REVIEW_SCHEMA))
        content=provider.build_request('repair',{'content':None,'failure':'shape','instruction':'repair'})
        self.assertNotIn('anyOf',content['text']['format']['schema'])
        self.assertIn('anyOf',CONTENT_SCHEMA)
        for key in ('store','stream','background'):self.assertIs(request[key],False)
        self.assertEqual(request['truncation'],'disabled');self.assertEqual(request['tools'],[])
        self.assertNotIn('previous_response_id',request);self.assertNotIn('conversation',request)
        packet['leaked_labels']=[]
        with self.assertRaises(ValueError):provider.build_request('review',packet)

    def test_nonterminal_output_cannot_release_uncertain_reservation(self):
        for output in ([{'type':'message','role':'assistant','status':'in_progress','content':[{'type':'refusal','refusal':'partial fixture'}]}], [{'type':'unexpected'}]):
            p,t=self.provider([])
            result=p.normalize_response(wire(status='in_progress',output=output))
            self.assertEqual(result.outcome,'uncertain')

    def test_fixed_rates_and_resume_settings_are_bound(self):
        with self.assertRaises(ValueError):
            OpenAIResponsesProvider(OfflineTransport([]),input_rate_micro_per_million=0,output_rate_micro_per_million=0)
        manifest=self.plan()
        content={'subject':'Fixture','body':PHRASES[LABELS[0]]}
        p,t=self.provider([wire(json.dumps(content)),wire(json.dumps(review([LABELS[0]])))],manifest)
        run_pipeline(self.run,p)
        p.reasoning_effort='medium'
        with self.assertRaises(LiveProviderBlocked):run_pipeline(self.run,p)
        p.reasoning_effort='low'
        p.max_output_tokens=1
        with self.assertRaises(LiveProviderBlocked):run_pipeline(self.run,p)
        p.max_output_tokens=6000
        p.input_rate=0
        with self.assertRaises(LiveProviderBlocked):run_pipeline(self.run,p)
        self.assertEqual(len(t.create_calls),2)

    def test_reasoning_usage_nonfirst_output_and_cost_no_double_charge(self):
        p,t=self.provider([])
        raw=wire('{"subject":"Fixture","body":"Text"}')
        response=p.normalize_response(raw)
        self.assertEqual(response.outcome,'content');self.assertEqual(response.input_tokens,100)
        self.assertEqual(response.reasoning_tokens,50);self.assertEqual(p.cost_micro(response),2200)
        raw['usage']['input_tokens']=999
        self.assertEqual(response.raw_response['usage']['input_tokens'],100)

    def test_private_pilot_runs_mocked_pipeline_and_resume_without_dispatch(self):
        manifest=self.plan()
        content={'subject':'API contract fixture','body':PHRASES[LABELS[0]]}
        p,t=self.provider([wire(json.dumps(content)),wire(json.dumps(review([LABELS[0]])))],manifest)
        result=run_pipeline(self.run,p)
        self.assertEqual(result['counts']['accepted'],1);self.assertEqual(result['budget']['spent_micro'],4400)
        self.assertTrue(result['live_authorized']);self.assertFalse(result['public_release_authorized'])
        self.assertEqual(len(t.count_calls),2);self.assertEqual(len(t.create_calls),2)
        record=json.loads((self.run/'records'/'s00000-v0.json').read_text())
        self.assertEqual(record['content_origin'],'api_contract_fixture')
        self.assertEqual(run_pipeline(self.run,p),result)
        self.assertEqual(len(t.create_calls),2);self.assertEqual(len(t.count_calls),2)
        raw=json.loads((self.run/'raw'/'s00000-v0-generate.json').read_text())
        self.assertEqual(raw['response']['raw_response']['status'],'completed')

    def test_cap_blocks_before_create_and_authority_not_inferred_from_plan(self):
        manifest=self.plan(cap='0.001')
        p,t=self.provider([wire()],manifest)
        result=run_pipeline(self.run,p)
        self.assertEqual(t.create_calls,[]);self.assertEqual(result['processed'],0)
        self.assertEqual(result['budget']['reserved_micro'],0)
        blocked=OpenAIResponsesProvider(t)
        with self.assertRaises(LiveProviderBlocked):run_pipeline(self.run,blocked)
        with self.assertRaises(DispatchNotAuthorized):blocked.prepare('generate',{})
        self.assertEqual(t.create_calls,[])

    def test_manifest_bound_combined_cap_and_independent_readiness(self):
        manifest=self.plan()
        for values in ({'billing_verified':False},{'api_entitlement_verified':False},{'private_pilot_terms_reviewed':False},
                       {'cap_micro':10000001},{'manifest_hash':'wrong'},{'scope':'public_release'}):
            data={'manifest_hash':digest(manifest),'approval_reference':'offline-test-authority','cap_micro':10000000,
                  'api_entitlement_verified':True,'billing_verified':True,'private_pilot_terms_reviewed':True}
            data.update(values);p=OpenAIResponsesProvider(OfflineTransport([]),authorization=PrivatePilotAuthorization(**data))
            with self.subTest(values=values),self.assertRaises(LiveProviderBlocked):run_pipeline(self.run,p)

    def test_refusal_incomplete_failed_are_billed_held_never_repaired(self):
        for mode in ('refusal','incomplete','failed'):
            with tempfile.TemporaryDirectory() as d:
                self.run=Path(d)/'run';manifest=self.plan()
                raw=wire(status='incomplete' if mode=='incomplete' else 'failed' if mode=='failed' else 'completed')
                if mode=='refusal':raw['output'][1]['content']=[{'type':'refusal','refusal':'Offline refusal fixture'}]
                if mode=='incomplete':raw['incomplete_details']={'reason':'max_output_tokens'}
                if mode=='failed':raw['error']={'code':'server_error','message':'Offline fixture'}
                p,t=self.provider([raw],manifest);result=run_pipeline(self.run,p)
                self.assertEqual(result['counts']['held'],1);self.assertEqual(result['budget']['spent_micro'],2200)
                self.assertEqual(len(t.create_calls),1);self.assertEqual(result['repair_count'],0)
                self.assertEqual(run_pipeline(self.run,p),result);self.assertEqual(len(t.create_calls),1)

    def test_missing_usage_timeout_http_and_nonterminal_keep_reservation(self):
        for raw in (wire(usage=False),TimeoutError('offline transport uncertainty'),
                    {'id':None,'model':MODEL,'status':'http_error','usage':None,'output':[],'error':{'status_code':401}},
                    wire(status='in_progress')):
            with tempfile.TemporaryDirectory() as d:
                self.run=Path(d)/'run';manifest=self.plan();p,t=self.provider([raw],manifest)
                try:run_pipeline(self.run,p)
                except IntegrityError:pass
                result=status_run(self.run)
                self.assertEqual(result['processed'],0);self.assertGreater(result['budget']['reserved_micro'],0)
                self.assertEqual(len(t.create_calls),1)
                try:run_pipeline(self.run,p)
                except IntegrityError:pass
                self.assertEqual(len(t.create_calls),1)

    def test_usage_overlimit_invalid_reasoning_and_wrong_model_fail_closed(self):
        for change in (lambda x:x['usage']['output_tokens_details'].update(reasoning_tokens=201),
                       lambda x:x['usage'].update(input_tokens=12001,total_tokens=12201),
                       lambda x:x.update(model='wrong-model'),lambda x:x['usage'].update(total_tokens=5)):
            raw=wire();change(raw);p,_=self.provider([]);response=p.normalize_response(raw)
            with self.assertRaises(ValueError):p.cost_micro(response)

    def test_input_count_ceiling_prevents_create_and_unsupported_effort(self):
        p,t=self.provider([]);t.tokens=12001
        with self.assertRaises(ValueError):p.prepare('generate',{})
        self.assertEqual(t.create_calls,[])
        with self.assertRaises(ValueError):OpenAIResponsesProvider(t,reasoning_effort='minimal')

    def test_sdk_options_official_route_no_hidden_retries_and_http_error_sanitized(self):
        client=Mock();client.base_url='https://api.openai.com/v1/'
        transport=SDKResponsesTransport(client)
        client.with_options.assert_called_once_with(max_retries=0,timeout=60)
        request={'model':MODEL,'input':'fixture','store':False,'text':{'format':{}}}
        copied=client.with_options.return_value;copied.responses.input_tokens.count.return_value.input_tokens=100
        self.assertEqual(transport.count(request),100)
        self.assertNotIn('store',copied.responses.input_tokens.count.call_args.kwargs)
        failure=RuntimeError('must not persist private SDK error text');failure.status_code=401;failure.request_id='req_offline'
        copied.responses.create.side_effect=failure
        result=transport.create(request)
        self.assertEqual(result['error'],{'status_code':401,'type':'RuntimeError'})
        self.assertNotIn('must not persist',json.dumps(result))
        for url in ('https://chatgpt.com/backend-api/codex','https://proxy.invalid/v1','http://api.openai.com/v1','https://user:pass@api.openai.com/v1'):
            client.base_url=url
            with self.assertRaises(ValueError):SDKResponsesTransport(client)


if __name__=='__main__':unittest.main()
