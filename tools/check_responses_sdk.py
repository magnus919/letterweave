"""Verify installed SDK wire integration using httpx.MockTransport, never sockets."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import httpx
from openai import OpenAI
from email_corpus_forge.openai_responses import MODEL, OpenAIResponsesProvider, PrivatePilotAuthorization, SDKResponsesTransport


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--out",type=Path,default=Path("docs/responses-sdk-verification.json"));args=parser.parse_args()
    requests=[]
    mode=['success']
    def handler(request):
        payload=json.loads(request.content)
        requests.append({'path':request.url.path,'payload':payload})
        if request.url.path=='/v1/responses/input_tokens':
            return httpx.Response(200,json={'object':'response.input_tokens','input_tokens':100})
        assert request.url.path=='/v1/responses'
        if mode[0]=='429':
            return httpx.Response(429,headers={'x-request-id':'offline-error'},json={'error':{'message':'offline fixture','type':'rate_limit_error','code':'rate_limit_exceeded'}})
        if mode[0]=='timeout':
            raise httpx.ReadTimeout('offline fixture',request=request)
        return httpx.Response(200,json={'id':'resp_offline','object':'response','created_at':1,'model':MODEL,'status':'completed','error':None,'incomplete_details':None,
            'output':[{'id':'msg_offline','type':'message','role':'assistant','status':'completed','content':[{'type':'output_text','text':'{"subject":"Fixture","body":"English text"}','annotations':[]}]}],
            'usage':{'input_tokens':100,'output_tokens':200,'total_tokens':300,'input_tokens_details':{'cached_tokens':0},'output_tokens_details':{'reasoning_tokens':50}}})
    client=OpenAI(api_key='offline-placeholder',http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    transport=SDKResponsesTransport(client,offline_test_transport=True)
    auth=PrivatePilotAuthorization('offline','offline-test-only',10000000,True,True,True)
    provider=OpenAIResponsesProvider(transport,authorization=auth)
    try:
        provider.prepare('generate',{'instruction':'Offline fixture'})
        response=provider.generate({'instruction':'Offline fixture'})
        assert response.outcome=='content' and provider.cost_micro(response)==2200
        assert len(requests)==2 and requests[0]['path']=='/v1/responses/input_tokens'
        assert requests[1]['payload']['model']==MODEL
        assert requests[1]['payload']['text']['format']['strict'] is True
        mode[0]='429'
        raw=transport.create(provider.build_request('generate',{}))
        assert len(requests)==3 and raw['usage'] is None and raw['error']['status_code']==429
        mode[0]='timeout'
        try:transport.create(provider.build_request('generate',{}))
        except Exception as error:assert type(error).__name__=='APITimeoutError'
        else:raise AssertionError('timeout not propagated')
        assert len(requests)==4
        evidence={'scope':'installed SDK with in-memory HTTP fixtures; not API entitlement proof','openai_sdk_version':importlib.metadata.version('openai'),'httpx_version':importlib.metadata.version('httpx'),'socket_requests':0,'billable_inference_requests':0,'mock_requests':4,'implicit_retries':0,'success_usage_verified':True,'reasoning_inclusive_cost_micro':2200,'http_error_sanitized':True,'timeout_propagated':True}
        args.out.write_text(json.dumps(evidence,indent=2)+'\n')
        print(json.dumps(evidence))
    finally:client.close()

if __name__=='__main__':main()
