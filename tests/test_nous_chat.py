"""Offline Nous contract and pilot integration; no account inference."""
import json
from pathlib import Path
import tempfile
import unittest
from email_corpus_forge.contracts import LABELS,blind_packet,digest
from email_corpus_forge.nous_chat import MODEL,CANONICAL_MODEL,NousChatProvider,SDKNousChatTransport
from email_corpus_forge.openai_responses import PrivatePilotAuthorization
from email_corpus_forge.pipeline import create_plan,run_pipeline,LiveProviderBlocked
from email_corpus_forge.providers import PHRASES
from test_openai_responses import OfflineTransport
from test_planning import inventory
from test_execution_quality import review

def chat(content='{}',finish='stop',model=MODEL,usage=True):
 return {'id':'chatcmpl_offline','model':model,'choices':[{'index':0,'finish_reason':finish,'message':{'role':'assistant','content':content,'refusal':None}}],'usage':{'prompt_tokens':100,'completion_tokens':200,'total_tokens':300,'completion_tokens_details':{'reasoning_tokens':50}} if usage else None}

class NousTests(unittest.TestCase):
 def provider(self,responses,manifest=None):
  t=OfflineTransport(responses);a=PrivatePilotAuthorization(digest(manifest or {}),'offline-test-only',10000000,True,True,True)
  return NousChatProvider(t,authorization=a),t
 def test_wire_blind_schema_exact_alias_and_bounds(self):
  p,t=self.provider([]);r=p.build_request('review',blind_packet({'subject':'Fixture','body':'English fixture'}))
  self.assertEqual(r['model'],MODEL);self.assertEqual(r['max_completion_tokens'],6000);self.assertEqual(r['reasoning_effort'],'low')
  self.assertTrue(r['response_format']['json_schema']['strict']);self.assertFalse(r['stream']);self.assertNotIn('tools',r);self.assertNotIn('service_tier',r)
  self.assertEqual(p.reservation_micro,114000)
  self.assertLess(SDKNousChatTransport.count(None,r),12000)
  with self.assertRaises(ValueError):NousChatProvider(t,max_input_tokens=272000)
 def test_usage_inclusive_canonical_identity_and_conservative_accounting(self):
  p,t=self.provider([]);r=p.normalize_response(chat(model=CANONICAL_MODEL))
  self.assertEqual(r.model,MODEL);self.assertEqual(p.cost_micro(r),2450)
  self.assertEqual(r.raw_response['model'],CANONICAL_MODEL)
  with self.assertRaises(ValueError):p.cost_micro(p.normalize_response(chat(model='openai/gpt-6-luna')))
 def test_terminal_vs_uncertain_missing_usage_and_refusal(self):
  p,t=self.provider([])
  for finish in ('length','content_filter'):
   self.assertEqual(p.normalize_response(chat(finish=finish)).outcome,'incomplete')
  raw=chat(finish=None);raw['choices'][0]['message']['refusal']='partial'
  self.assertEqual(p.normalize_response(raw).outcome,'uncertain')
  raw['choices'][0]['finish_reason']='stop';self.assertEqual(p.normalize_response(raw).outcome,'refusal')
  for raw in (chat(usage=False),{'id':'error','model':MODEL,'choices':[],'usage':None}):
   with self.assertRaises(ValueError):p.cost_micro(p.normalize_response(raw))
 def test_mock_pipeline_manifest_binding_resume_and_mutation_guards(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);s=inventory(1);s['families'][0]['intended_labels']=[LABELS[0]];path=root/'scenarios.json';path.write_text(json.dumps(s))
   m=create_plan(root/'run',scenario_plan=path,provider_mode='live',live_provider='nous-chat',variants_per_family=1,max_repairs=0,max_rereviews=0)
   p,t=self.provider([chat(json.dumps({'subject':'Fixture','body':PHRASES[LABELS[0]]})),chat(json.dumps(review([LABELS[0]])))],m)
   result=run_pipeline(root/'run',p);self.assertEqual(result['counts']['accepted'],1);self.assertEqual(result['budget']['spent_micro'],4900)
   self.assertEqual(run_pipeline(root/'run',p),result);self.assertEqual(len(t.create_calls),2)
   p.max_output_tokens=1
   with self.assertRaises(LiveProviderBlocked):run_pipeline(root/'run',p)
   self.assertEqual(len(t.create_calls),2)
 def test_baseline_excludes_future_mutations_and_controller_metadata(self):
  p,t=self.provider([])
  scenario={'context':'Current context','purpose':'Current purpose','writing_style':'Brief English','topic':'Fictional topic','intended_labels':['promotions/outreach'],'family_id':'secret-controller-id','split':'test','variants':[0,1],'mutations':[{'changed_factors':['FUTURE_SECRET_OPERATION']}],'diagnostic_tags':['future']}
  packet={'scenario':scenario,'variant':0,'content_schema_version':'0.1.0'}
  request=p.build_request('generate',packet);visible=json.loads(request['messages'][1]['content'])
  self.assertEqual(set(visible['scenario']),{'context','purpose','writing_style','topic'})
  for secret in ('FUTURE_SECRET_OPERATION','secret-controller-id','intended_labels','mutations','diagnostic_tags','variants','split'):
   self.assertNotIn(secret,json.dumps(visible))
  self.assertEqual(packet['scenario'],scenario)
  t.responses=[chat()]
  p.prepare('generate',packet);response=p.generate(packet)
  self.assertEqual(response.request_payload,request)
  self.assertNotIn('FUTURE_SECRET_OPERATION',json.dumps(response.request_payload))
 def test_provider_reported_charge_is_checked_separately(self):
  p,t=self.provider([]);raw=chat();raw['usage']['cost']=0.0022
  self.assertEqual(p.cost_micro(p.normalize_response(raw)),2450)
  for charge in (0.003,-1,'NaN','wrong'):
   raw['usage']['cost']=charge
   with self.assertRaises(ValueError):p.cost_micro(p.normalize_response(raw))
 def test_malformed_fields_preserve_full_raw_evidence(self):
  p,t=self.provider([])
  for field in ('usage','details','message'):
   raw=chat()
   if field=='usage':raw['usage']=['malformed']
   elif field=='details':raw['usage']['completion_tokens_details']=['malformed']
   else:raw['choices'][0]['message']=['malformed']
   result=p.normalize_response(raw);self.assertEqual(result.raw_response,raw)
   if field!='message':
    with self.assertRaises(ValueError):p.cost_micro(result)
   else:self.assertEqual(result.outcome,'error')
 def test_transport_route_rejects_proxy_and_consumer(self):
  from unittest.mock import Mock
  for url in ('https://api.openai.com/v1','https://chatgpt.com/backend-api/codex','https://gpuslut.brandyapple.com/v1'):
   c=Mock();c.base_url=url
   with self.assertRaises(ValueError):SDKNousChatTransport(c)
