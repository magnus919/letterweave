"""Authorized ordinary Nous role routes; no credentials or retry policy added."""
from dataclasses import replace

from .contracts import digest
from .nous_chat import NousChatProvider, MODEL as SOL_MODEL
from .openai_responses import PrivatePilotAuthorization
from .provider_adapter import ContractProviderAdapter, DispatchNotAuthorized

LUNA_MODEL = 'openai/gpt-6-luna'
LUNA_CANONICAL_MODEL = 'openai/gpt-6-luna-20260922'
ROLE_MODELS = {'generation': LUNA_MODEL, 'review': SOL_MODEL}
_STAGE_ROLES = {'generate': 'generation', 'mutate': 'generation',
                'repair': 'generation', 'review': 'review',
                'rereview': 'review', 'repair_review': 'review'}


class LunaNousChatProvider(NousChatProvider):
    """Luna uses the established Chat schema/profile with its own wire identity."""
    def __init__(self, transport, *, authorization=None, reasoning_effort='low',
                 max_input_tokens=12000, max_output_tokens=6000, content_profile="compact"):
        self.content_profile=content_profile
        if content_profile not in {'compact','mail-realism-v1'}:raise ValueError('unknown content profile')
        if reasoning_effort != 'low':
            raise ValueError('this authorization selects ordinary Luna with low reasoning')
        ContractProviderAdapter.__init__(
            self, LUNA_MODEL, input_rate_micro_per_million=225000,
            output_rate_micro_per_million=500000,
            max_input_tokens=max_input_tokens, max_output_tokens=max_output_tokens)
        if max_input_tokens > (24000 if content_profile=='mail-realism-v1' else 12000) or max_output_tokens > 6000:
            raise ValueError('bounded private pilot ceilings exceeded')
        self.transport, self.authorization = transport, authorization
        self.reasoning_effort = reasoning_effort
        self._prepared = {}
        self._frozen_settings = self.settings()
        self._frozen_reservation = self.reservation_micro

    def _authorize(self):
        if not isinstance(self.authorization, PrivatePilotAuthorization):
            raise DispatchNotAuthorized('private pilot authorization absent')
        self.authorization.check()
        if (self.settings() != self._frozen_settings or
                self.reservation_micro != self._frozen_reservation or
                self.model != LUNA_MODEL or
                (self.input_rate, self.output_rate) != (225000, 500000)):
            raise DispatchNotAuthorized('Luna settings/reservation changed')

    def assert_run_authorized(self, manifest):
        self._authorize()
        self.authorization.check(manifest)
        if (manifest['provider_mode'] != 'live' or
                manifest['model'] != LUNA_MODEL or manifest['provider'] != self.name):
            raise DispatchNotAuthorized('manifest does not select exact ordinary Luna route')

    def build_request(self, stage, packet):
        if _STAGE_ROLES.get(stage) != 'generation':
            raise DispatchNotAuthorized('Luna is authorized only for content stages')
        request = super().build_request(stage, packet)
        # Change the actual outgoing request, never a returned raw model identity.
        request['model'] = LUNA_MODEL
        return request

    def normalize_response(self, raw):
        response = super().normalize_response(raw)
        if raw.get('model') == LUNA_CANONICAL_MODEL:
            response = replace(response, model=LUNA_MODEL)
        return response


class RoleRoutedNousProvider(NousChatProvider):
    """Serial prepared dispatch bound to exact stage, packet and authorized child."""
    name = 'nous-chat'

    def __init__(self, transport, *, authorization=None, reasoning_effort='low',
                 max_input_tokens=12000, max_output_tokens=6000, content_profile="compact"):
        if reasoning_effort != 'low':
            raise ValueError('role authorization selects low reasoning')
        kwargs = dict(authorization=authorization, reasoning_effort=reasoning_effort,
                      max_input_tokens=max_input_tokens, max_output_tokens=max_output_tokens,content_profile=content_profile)
        self._children = {'generation': LunaNousChatProvider(transport, **kwargs),
                          'review': NousChatProvider(transport, **kwargs)}
        self.transport, self.authorization = transport, authorization
        self.reasoning_effort = reasoning_effort
        self.max_input_tokens, self.max_output_tokens = max_input_tokens, max_output_tokens
        self._prepared = {}
        self._active = None
        self._select(self._children['review'])
        self._frozen_settings = self.settings()

    def _select(self, child):
        self.model, self.reservation_micro = child.model, child.reservation_micro
        self.input_rate, self.output_rate = child.input_rate, child.output_rate

    def settings(self):
        return {'role_models': dict(ROLE_MODELS),
                'roles': {role: child.settings() for role, child in self._children.items()},
                'dispatch_binding': 'single prepared stage and exact packet digest'}

    def _authorize(self):
        if self.settings() != self._frozen_settings:
            raise DispatchNotAuthorized('role registry/settings changed')
        for child in self._children.values():
            if child.transport is not self.transport or child.authorization is not self.authorization:
                raise DispatchNotAuthorized('role transport/authorization changed')
            child._authorize()
        expected = self._children[self._active[2]] if self._active else self._children['review']
        if (self.model, self.reservation_micro, self.input_rate, self.output_rate) != (
                expected.model, expected.reservation_micro, expected.input_rate, expected.output_rate):
            raise DispatchNotAuthorized('dispatch model/reservation changed')

    def assert_run_authorized(self, manifest):
        self._authorize()
        self.authorization.check(manifest)
        if (manifest['provider_mode'] != 'live' or manifest['provider'] != self.name or
                manifest['model'] != SOL_MODEL or manifest.get('role_models') != ROLE_MODELS):
            raise DispatchNotAuthorized('manifest does not bind exact Luna generation/Sol review routes')

    def model_for_stage(self, stage):
        if stage not in _STAGE_ROLES:
            raise DispatchNotAuthorized('unauthorized role stage')
        return ROLE_MODELS[_STAGE_ROLES[stage]]

    def build_request(self, stage, packet):
        self.model_for_stage(stage)
        return self._children[_STAGE_ROLES[stage]].build_request(stage, packet)

    def prepare(self, stage, packet):
        self._authorize()
        self.model_for_stage(stage)
        if self._active is not None:
            raise DispatchNotAuthorized('an exact role dispatch is already prepared')
        role = _STAGE_ROLES[stage]
        child = self._children[role]
        child.prepare(stage, packet)
        key = (stage, digest(packet))
        self._prepared[key] = child._prepared[key]
        self._active = (stage, key[1], role)
        self._select(child)

    def _execute(self, stage, packet):
        self._authorize()
        key = (stage, digest(packet))
        if self._active is None or self._active[:2] != key:
            raise DispatchNotAuthorized('execution differs from prepared role/stage/packet')
        child = self._children[self._active[2]]
        try:
            return child._execute(stage, packet)
        finally:
            child._prepared.pop(key, None)
            self._prepared.pop(key, None)
            self._active = None
            # Prepared dispatch metadata supplies ledger identity; the idle
            # provider resumes the manifest's review identity.
            self._select(self._children['review'])

    def cost_micro(self, response):
        # Carried Sol generation responses remain priced as Sol, regardless of
        # the current generation route or most recently prepared request.
        for child in self._children.values():
            if response.model == child.model:
                return child.cost_micro(response)
        raise ValueError('response has no authorized actual model price')
