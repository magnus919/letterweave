"""Installed SDK Nous wire verification using in-memory HTTP only."""
import importlib.metadata,json,argparse
from pathlib import Path
import httpx
from openai import OpenAI
from email_corpus_forge.nous_chat import MODEL,NousChatProvider,SDKNousChatTransport
from email_corpus_forge.openai_responses import PrivatePilotAuthorization

def main():
 parser=argparse.ArgumentParser();parser.add_argument("--out",type=Path,default=Path("docs/nous-sdk-verification.json"));args=parser.parse_args()
 calls=[];mode=['success']
 def handler(request):
  calls.append(json.loads(request.content));assert request.url.path=='/v1/chat/completions'
  if mode[0]=='429':return httpx.Response(429,json={'error':{'message':'offline fixture','type':'rate_limit_error'}})
  return httpx.Response(200,json={'id':'chatcmpl_offline','object':'chat.completion','created':1,'model':MODEL,'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'{"subject":"Fixture","body":"English text"}','refusal':None}}],'usage':{'prompt_tokens':100,'completion_tokens':200,'total_tokens':300,'completion_tokens_details':{'reasoning_tokens':50}}})
 client=OpenAI(api_key='offline-placeholder',base_url='https://inference-api.nousresearch.com/v1',http_client=httpx.Client(transport=httpx.MockTransport(handler)))
 try:
  t=SDKNousChatTransport(client,offline_test_transport=True);p=NousChatProvider(t,authorization=PrivatePilotAuthorization('offline','offline-test-only',10000000,True,True,True))
  p.prepare('generate',{'instruction':'Offline fixture'});r=p.generate({'instruction':'Offline fixture'})
  assert r.outcome=='content' and p.cost_micro(r)==2450
  assert calls[0]['model']==MODEL and calls[0]['max_completion_tokens']==6000 and calls[0]['response_format']['json_schema']['strict'] is True
  mode[0]='429';raw=t.create(p.build_request('generate',{}));assert raw['error']['status_code']==429 and raw['usage'] is None and len(calls)==2
  e={'scope':'installed SDK with in-memory HTTP; not inference proof','openai_sdk_version':importlib.metadata.version('openai'),'model':MODEL,'mock_requests':2,'socket_requests':0,'implicit_retries':0,'strict_schema_wire_verified':True,'usage_reasoning_inclusive_verified':True,'conservative_usage_cost_micro':2450,'input_count_method':p.settings()['input_count_basis']}
  args.out.write_text(json.dumps(e,indent=2)+'\n');print(json.dumps(e))
 finally:client.close()
if __name__=='__main__':main()
