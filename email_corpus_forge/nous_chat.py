"""Nous Portal Chat Completions adaptation; injected existing client, no auth refresh."""
import json
from urllib.parse import urlsplit
from .contracts import canonical, CONTENT_SCHEMA
from .planning import integer
from .provider_adapter import ContractProviderAdapter, DispatchNotAuthorized
from .openai_responses import OpenAIResponsesProvider, PrivatePilotAuthorization, supported_schema
from .providers import Response
from dataclasses import replace
from .typography import SUBJECT_PATTERN, BODY_PATTERN, profile_valid, broken_apostrophe_fragments

MODEL='openai/gpt-6.1-sol'
CANONICAL_MODEL='openai/gpt-6.1-sol-20260929'

class SDKNousChatTransport:
    def __init__(self,client,*,offline_test_transport=False,timeout_seconds=60):
        u=urlsplit(str(client.base_url))
        if u.scheme!='https' or u.hostname!='inference-api.nousresearch.com' or u.port not in (None,443) or u.path.rstrip('/')!='/v1' or u.username or u.password or u.query or u.fragment:
            raise ValueError('only verified Nous inference route supported')
        self.client=client.with_options(max_retries=0,timeout=timeout_seconds)
        self.is_offline_fixture=offline_test_transport is True
    def count(self,request):
        # Conservative local byte envelope; not an exact provider token count.
        metadata={k:v for k,v in request.items() if k!='messages'}
        # Count actual unwrapped content bytes, explicit schema/metadata bytes and
        # 1024 additional framing bytes. JSON outer escaping is not model text.
        return sum(len(m['content'].encode('utf-8'))+len(m['role'].encode('utf-8')) for m in request['messages'])+len(canonical(metadata))+1024
    def create(self,request):
        try:r=self.client.chat.completions.create(**request)
        except Exception as e:
            status=getattr(e,'status_code',None)
            if type(status) is int:return {'id':getattr(e,'request_id',None),'model':MODEL,'choices':[], 'usage':None,'error':{'status_code':status,'type':type(e).__name__}}
            raise
        return r.model_dump(mode='json') if hasattr(r,'model_dump') else r

class NousChatProvider(OpenAIResponsesProvider):
    name='nous-chat'
    def __init__(self,transport,*,authorization=None,reasoning_effort='low',max_input_tokens=12000,max_output_tokens=6000):
        if reasoning_effort not in {'low','medium','high','xhigh','max'}:raise ValueError('unsupported Sol reasoning effort')
        # Reserve prompt + worst-case cache write additively; no cache discount assumed.
        ContractProviderAdapter.__init__(self,MODEL,input_rate_micro_per_million=4500000,output_rate_micro_per_million=10000000,max_input_tokens=max_input_tokens,max_output_tokens=max_output_tokens)
        if max_input_tokens>12000 or max_output_tokens>6000:raise ValueError('bounded private pilot ceilings exceeded')
        self.transport,self.authorization,self.reasoning_effort=transport,authorization,reasoning_effort
        self._prepared={};self._frozen_settings=self.settings();self._frozen_reservation=self.reservation_micro
    def settings(self):
        return {'model':self.model,'input_rate_micro_per_million':self.input_rate,'output_rate_micro_per_million':self.output_rate,'max_input_tokens':self.max_input_tokens,'max_output_tokens':self.max_output_tokens,'reasoning_effort':self.reasoning_effort,'billing_basis':'conservative prompt plus cache-write envelope; output includes reasoning','input_count_basis':'unwrapped message UTF8 bytes plus explicit nonmessage metadata/schema bytes plus1024 framing; not exact tokenizer count','service_tier':'ordinary model alias; no batch/fast/flex override','content_profile':'English typography preserved; UTF8 subject160/body2200 byte limits; no silent normalization'}
    def _authorize(self):
        if not isinstance(self.authorization,PrivatePilotAuthorization):raise DispatchNotAuthorized('private pilot authorization absent')
        self.authorization.check()
        if self.settings()!=self._frozen_settings or self.reservation_micro!=self._frozen_reservation or self.model!=MODEL or (self.input_rate,self.output_rate)!=(4500000,10000000):raise DispatchNotAuthorized('provider settings/reservation changed')
    def assert_run_authorized(self,manifest):
        self._authorize();self.authorization.check(manifest)
        if manifest['provider_mode']!='live' or manifest['model']!=MODEL or manifest['provider']!=self.name:raise DispatchNotAuthorized('manifest does not select exact Nous Sol route')
    def build_request(self,stage,packet):
        c=ContractProviderAdapter.build_request(self,stage,packet)
        wire_input=c['input']
        if stage in {'review','rereview','repair_review'}:
            # Schema already supplied once in response_format, not duplicated in text.
            wire_input={k:v for k,v in wire_input.items() if k!='output_schema'}
        schema=c['output_schema']
        if stage in {'generate','mutate'}:
            schema=json.loads(canonical(CONTENT_SCHEMA))
            schema['properties']['subject'].update(maxLength=160,pattern=SUBJECT_PATTERN)
            schema['properties']['body'].update(maxLength=2200,pattern=BODY_PATTERN)
        instructions=c['instructions']
        if stage in {'generate','mutate'}:
            instructions+=' Preserve curly and straight apostrophes, possessives, quotes, dashes and ellipses; never replace punctuation with whitespace or line breaks. Subject <=160 UTF-8 bytes and body <=2200 UTF-8 bytes; do not truncate or normalize parent text to force a label.'
        return {'model':MODEL,'messages':[{'role':'system','content':instructions},{'role':'user','content':canonical(wire_input).decode()}], 'response_format':{'type':'json_schema','json_schema':{'name':'email_review' if stage in {'review','rereview','repair_review'} else 'email_content','strict':True,'schema':supported_schema(schema)}},'reasoning_effort':self.reasoning_effort,'max_completion_tokens':self.max_output_tokens,'stream':False}
    def normalize_response(self,raw):
        if type(raw) is not dict:raise ValueError('invalid chat envelope')
        raw=json.loads(canonical(raw));usage=raw.get('usage');usage=usage if isinstance(usage,dict) else {}
        details=usage.get('completion_tokens_details');details=details if isinstance(details,dict) else {}
        choices=raw.get('choices');text='';outcome='uncertain';status='unknown'
        if isinstance(choices,list) and len(choices)==1 and isinstance(choices[0],dict):
            c=choices[0];finish=c.get('finish_reason');m=c.get('message');m=m if isinstance(m,dict) else {}
            if finish in {'stop','length','content_filter','tool_calls','function_call'}:
                status='completed' if finish=='stop' else 'incomplete';outcome='content' if finish=='stop' else 'incomplete'
                if m.get('refusal'):outcome='refusal'
                if m.get('role')!='assistant' or m.get('tool_calls') or m.get('function_call'):outcome='error'
                if isinstance(m.get('content'),str):text=m['content']
                elif outcome=='content':outcome='error'
            if outcome=='content' and (not text or raw.get('error')):outcome='error'
        values={'input_tokens':usage.get('prompt_tokens'),'output_tokens':usage.get('completion_tokens'),'reasoning_tokens':details.get('reasoning_tokens')}
        if all(type(values[k]) is int for k in ('input_tokens','output_tokens')) and usage.get('total_tokens')!=values['input_tokens']+values['output_tokens']:values={k:None for k in values}
        if outcome=='content':
            try:
                generated=json.loads(text)
                if isinstance(generated,dict) and set(generated)=={'subject','body'}:
                    if not profile_valid(generated):outcome='error'
            except (ValueError,TypeError):pass  # malformed JSON handled by content contract
        model=raw.get('model');model=MODEL if model==CANONICAL_MODEL else model
        return Response(text=text,model=model,request_id=raw.get('id'),**values,provider_status=status,outcome=outcome,raw_response=raw)

    def _execute(self, stage, packet):
        response=super()._execute(stage,packet)
        if stage=='mutate' and response.outcome=='content':
            try:
                content=json.loads(response.text)
                if broken_apostrophe_fragments(content, packet['parent_content']):
                    # Keep immutable raw text, usage and request; reject rather than repair.
                    response=replace(response,outcome='error')
            except (ValueError,TypeError,KeyError):pass  # content contract handles malformed JSON
        return response

    def cost_micro(self,response):
        from decimal import Decimal,InvalidOperation,ROUND_CEILING
        estimate=super().cost_micro(response)
        usage=(response.raw_response or {}).get('usage')
        if isinstance(usage,dict) and usage.get('cost') is not None:
            try:amount=Decimal(str(usage['cost']))
            except InvalidOperation as e:raise ValueError('invalid provider charge') from e
            if not amount.is_finite() or amount<0:raise ValueError('invalid provider charge')
            billed=int((amount*1000000).to_integral_value(rounding=ROUND_CEILING))
            if billed>estimate:raise ValueError('provider reported charge exceeds conservative envelope')
        return estimate
