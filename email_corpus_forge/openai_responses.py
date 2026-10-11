"""OpenAI Responses SDK integration; private pilot authorization is separate from planning."""
from dataclasses import dataclass, replace
import json
from urllib.parse import urlsplit

from .contracts import canonical, digest
from .planning import integer
from .provider_adapter import ContractProviderAdapter, DispatchNotAuthorized
from .providers import Response

MODEL = 'gpt-6.1-sol'


@dataclass(frozen=True)
class PrivatePilotAuthorization:
    manifest_hash: str
    approval_reference: str
    cap_micro: int
    api_entitlement_verified: bool = False
    billing_verified: bool = False
    private_pilot_terms_reviewed: bool = False
    scope: str = 'private_synthetic_quality_pilot'
    approved_cap_micro: int = 10_000_000

    def check(self, manifest=None):
        if (self.scope != 'private_synthetic_quality_pilot' or not self.approval_reference or
                type(self.cap_micro) is not int or type(self.approved_cap_micro) is not int or
                not 0 < self.cap_micro <= self.approved_cap_micro <= 30_000_000 or
                any(x is not True for x in (self.api_entitlement_verified, self.billing_verified, self.private_pilot_terms_reviewed))):
            raise DispatchNotAuthorized('private pilot API entitlement, billing or scope/terms readiness unresolved')
        if manifest is not None and (self.manifest_hash != digest(manifest) or manifest['cap_micro'] > self.cap_micro):
            raise DispatchNotAuthorized('authorization does not bind this manifest and combined cap')


def supported_schema(schema, *, root=True):
    """Project predicates unsupported on the wire remain enforced locally."""
    if isinstance(schema, list):
        return [supported_schema(x, root=False) for x in schema]
    if not isinstance(schema, dict):
        return schema
    result = {k: supported_schema(v, root=False) for k, v in schema.items()
              if k not in {'$schema', 'allOf', 'if', 'then', 'else', 'maxLength'} and not (root and k == 'anyOf')}
    if 'enum' in result and 'type' not in result:
        result['type'] = 'string'
    return result


class SDKResponsesTransport:
    """Use an injected OpenAI SDK client; never reads credentials or creates accounts."""
    def __init__(self, client, *, timeout_seconds=60, offline_test_transport=False):
        url = urlsplit(str(client.base_url))
        if url.scheme != 'https' or url.hostname != 'api.openai.com' or url.port not in (None,443) or url.path.rstrip('/') != '/v1' or url.username or url.password or url.query or url.fragment:
            raise ValueError('only the official OpenAI API route is supported; consumer/proxy routes rejected')
        self.is_offline_fixture = offline_test_transport is True
        self.client = client.with_options(max_retries=0, timeout=timeout_seconds)

    def count(self, request):
        keys = {'model','input','instructions','reasoning','text','truncation'}
        response = self.client.responses.input_tokens.count(**{k:v for k,v in request.items() if k in keys})
        return response.input_tokens

    def create(self, request):
        try:
            response = self.client.responses.create(**request)
        except Exception as error:
            # HTTP errors have no confirmed usage. Never persist SDK headers, keys or messages.
            status = getattr(error, 'status_code', None)
            if type(status) is int:
                return {'id': getattr(error,'request_id',None), 'status':'http_error', 'model':MODEL,
                        'usage':None, 'output':[], 'error':{'status_code':status,'type':type(error).__name__}}
            raise
        return response.model_dump(mode='json') if hasattr(response,'model_dump') else response


class OpenAIResponsesProvider(ContractProviderAdapter):
    name = 'openai-responses'
    is_fixture = False

    def __init__(self, transport, *, authorization=None, reasoning_effort='low',
                 max_input_tokens=12000, max_output_tokens=6000,
                 input_rate_micro_per_million=2000000, output_rate_micro_per_million=10000000):
        if (type(input_rate_micro_per_million) is not int or type(output_rate_micro_per_million) is not int or
                (input_rate_micro_per_million,output_rate_micro_per_million) != (2000000,10000000)):
            raise ValueError('this provider requires fixed published standard rates; overrides unsupported')
        if not isinstance(reasoning_effort,str) or reasoning_effort not in {'low','medium','high','xhigh','max'}:
            raise ValueError('unsupported GPT-6.1 Sol reasoning effort')
        super().__init__(MODEL,input_rate_micro_per_million=input_rate_micro_per_million,
                         output_rate_micro_per_million=output_rate_micro_per_million,
                         max_input_tokens=max_input_tokens,max_output_tokens=max_output_tokens)
        self.transport, self.authorization, self.reasoning_effort = transport, authorization, reasoning_effort
        self._prepared = {}
        self._frozen_settings = self.settings()
        self._frozen_reservation = self.reservation_micro

    def assert_run_authorized(self, manifest):
        self._authorize()
        self.authorization.check(manifest)
        if manifest['provider_mode'] != 'live' or manifest['model'] != MODEL or manifest['provider'] != self.name:
            raise DispatchNotAuthorized('manifest model/provider differs from authorized private pilot')

    def _authorize(self):
        if not isinstance(self.authorization, PrivatePilotAuthorization):
            raise DispatchNotAuthorized('explicit private pilot authorization absent')
        self.authorization.check()
        if self.settings() != self._frozen_settings or self.reservation_micro != self._frozen_reservation:
            raise DispatchNotAuthorized('provider settings or reservation changed')
        if (self.input_rate,self.output_rate) != (2000000,10000000):
            raise DispatchNotAuthorized('provider pricing changed')

    def settings(self):
        return {'input_rate_micro_per_million':self.input_rate,'output_rate_micro_per_million':self.output_rate,
                'max_input_tokens':self.max_input_tokens,'max_output_tokens':self.max_output_tokens,
                'reasoning_effort':self.reasoning_effort,'service_tier':'default'}

    def build_request(self, stage, packet):
        contract = super().build_request(stage,packet)
        request = {'model':MODEL,'instructions':contract['instructions'],
                   'input':[{'role':'user','content':canonical(contract['input']).decode()}],
                   'text':{'format':{'type':'json_schema','name':'email_review' if stage in {'review','rereview','repair_review'} else 'email_content',
                                    'strict':True,'schema':supported_schema(contract['output_schema'])}},
                   'reasoning':{'effort':self.reasoning_effort},'max_output_tokens':self.max_output_tokens,
                   'service_tier':'default','store':False,'stream':False,'background':False,'truncation':'disabled','tools':[]}
        return json.loads(canonical(request))

    def prepare(self, stage, packet):
        self._authorize()
        request = self.build_request(stage,packet)
        count = self.transport.count(request)
        integer(count,'verified request input count',minimum=1,maximum=self.max_input_tokens)
        self._prepared[(stage,digest(packet))] = request

    def _execute(self, stage, packet):
        self._authorize()
        key = (stage,digest(packet))
        if key not in self._prepared:
            raise DispatchNotAuthorized('request must be token-counted before reservation and dispatch')
        request = self._prepared.pop(key)
        response=self.normalize_response(self.transport.create(request))
        return replace(response,request_payload=json.loads(canonical(request)))

    def generate(self, packet):return self._execute('generate',packet)
    def mutate(self, packet):return self._execute('mutate',packet)
    def repair(self, packet):return self._execute('repair',packet)
    def review(self, packet):
        # Pipeline uses stage-specific preparation; packet itself contains no controller stage.
        keys=[stage for stage in ('review','rereview','repair_review') if (stage,digest(packet)) in self._prepared]
        if len(keys)!=1:raise DispatchNotAuthorized('ambiguous/unprepared review request')
        return self._execute(keys[0],packet)

    def normalize_response(self, raw):
        if type(raw) is not dict:
            raise ValueError('invalid Responses envelope')
        raw=json.loads(canonical(raw))
        status=raw.get('status')
        usage=raw.get('usage')
        values = {'input_tokens':None,'output_tokens':None,'reasoning_tokens':None}
        if isinstance(usage,dict):
            values['input_tokens']=usage.get('input_tokens')
            values['output_tokens']=usage.get('output_tokens')
            details=usage.get('output_tokens_details')
            values['reasoning_tokens']=details.get('reasoning_tokens') if isinstance(details,dict) else None
        if not isinstance(status,str):status='unknown'
        outcome='content' if status=='completed' else 'incomplete' if status=='incomplete' else 'error' if status in {'failed','cancelled'} else 'uncertain'
        parts=[]
        refused=False
        output=raw.get('output',[])
        if not isinstance(output,list):outcome='error';output=[]
        for item in output:
            if not isinstance(item,dict):outcome='error';continue
            if item.get('type')=='reasoning':continue
            if item.get('type')!='message' or item.get('role')!='assistant':outcome='error';continue
            if item.get('status')!='completed' and status=='completed':outcome='incomplete'
            content=item.get('content',[])
            if not isinstance(content,list):outcome='error';continue
            for chunk in content:
                if not isinstance(chunk,dict):outcome='error';continue
                if chunk.get('type')=='refusal':refused=True
                elif chunk.get('type')=='output_text' and isinstance(chunk.get('text'),str):parts.append(chunk['text'])
                else:outcome='error'
        if refused:outcome='refusal'
        if outcome=='content' and (not parts or raw.get('error') is not None):outcome='error'
        if status not in {'completed','incomplete','failed','cancelled'}:outcome='uncertain'
        if isinstance(usage,dict) and all(type(values[k]) is int for k in ('input_tokens','output_tokens')) and usage.get('total_tokens') != values['input_tokens']+values['output_tokens']:
            values={k:None for k in values}
        return Response(text=''.join(parts),model=raw.get('model'),request_id=raw.get('id'),**values,
                        provider_status=status,outcome=outcome,raw_response=raw)

    def cost_micro(self,response):
        # Refusals/incomplete responses may still have billed usage; text can be empty.
        if response.model != self.model or not isinstance(response.request_id,str) or not response.request_id:
            raise ValueError('response identity invalid')
        for key,maximum in (('input_tokens',self.max_input_tokens),('output_tokens',self.max_output_tokens),('reasoning_tokens',self.max_output_tokens)):
            integer(getattr(response,key),key,maximum=maximum)
        if response.reasoning_tokens>response.output_tokens:raise ValueError('invalid reasoning count')
        return self._price(response.input_tokens,response.output_tokens)
