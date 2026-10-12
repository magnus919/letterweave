"""Validated scalable plans; external scenario descriptions are claims, not quality evidence."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re

from .contracts import LABELS, digest
from .duplicates import validate_settings

MAX_CANDIDATES = 1_000_000
CASES = {'single', 'overlap', 'no_match_candidate', 'missing_context', 'near_negative', 'custom'}
STAGES = {'generate', 'review', 'repair', 'repair_review', 'rereview'}


def integer(value, name, minimum=0, maximum=MAX_CANDIDATES):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be an integer in [{minimum}, {maximum}]')
    return value


def dollars_to_micro(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+(?:\.\d{1,6})?', value):
        raise ValueError('cap USD must be a nonnegative decimal with at most six fractional digits')
    try:
        amount = Decimal(value) * 1_000_000
    except InvalidOperation as exc:
        raise ValueError('invalid cap USD') from exc
    if amount > 1_000_000_000_000:
        raise ValueError('cap USD exceeds planning limit of 1000000')
    return int(amount)


def _object(value, required, optional=()):
    if type(value) is not dict or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        raise ValueError(f'object requires {sorted(required)}; optional {sorted(optional)}')


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError(f'{name} requires nonempty text of at most 2000 characters')
    return value.strip()


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def read_scenario_plan(path):
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('scenario plan exceeds 64 MiB')
    value = json.loads(path.read_text(), object_pairs_hook=_unique_keys)
    _object(value, {'schema_version', 'families', 'diversity'}, {'coverage', 'token_budget', 'near_duplicates', 'rereview_allocation'})
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('scenario plan schema_version must be 1')
    _object(value['diversity'], {'description'})
    _text(value['diversity']['description'], 'diversity description')
    families = value['families']
    if type(families) is not list or not 1 <= len(families) <= 100_000:
        raise ValueError('families must contain 1..100000 explicit scenarios')
    ids, semantics = set(), set()
    for family in families:
        _object(family, {'family_id', 'case', 'intended_labels', 'topic', 'context', 'purpose', 'writing_style'}, {'slice', 'stratum', 'diagnostic_tags', 'mutations'})
        fid = family['family_id']
        if not isinstance(fid, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', fid) or fid.casefold() in ids:
            raise ValueError('family_id must be unique, safe and at most 64 characters')
        ids.add(fid.casefold())
        if not isinstance(family.get('slice', 'ordinary'), str) or family.get('slice', 'ordinary') not in {'ordinary', 'challenge', 'uncertainty'}:
            raise ValueError('slice must be ordinary, challenge or uncertainty')
        if 'stratum' in family:
            _text(family['stratum'], 'stratum')
        tags = family.get('diagnostic_tags', [])
        if type(tags) is not list or any(not isinstance(t, str) or not t.strip() or len(t) > 80 for t in tags) or len(set(tags)) != len(tags):
            raise ValueError('diagnostic_tags must be distinct short strings')
        mutations = family.get('mutations', [])
        if type(mutations) is not list:
            raise ValueError('mutations must be a list')
        variant_ids = set()
        for mutation in mutations:
            _object(mutation, {'variant', 'parent_variant', 'operator', 'operator_version', 'changed_factors',
                               'relation', 'add_labels', 'remove_labels', 'invariant_labels', 'uncertain_labels',
                               'rationale', 'context_sufficiency'}, {'preserve_facts'})
            anchors=mutation.get('preserve_facts', [])
            if type(anchors) is not list or len(anchors)>64 or any(not isinstance(a,str) or not a.strip() or len(a)>2000 for a in anchors) or len(set(anchors))!=len(anchors):
                raise ValueError('preserve_facts must be distinct bounded literal anchors')
            variant = integer(mutation['variant'], 'mutation variant', minimum=1)
            integer(mutation['parent_variant'], 'parent_variant', maximum=variant - 1)
            if variant in variant_ids:
                raise ValueError('duplicate mutation variant')
            variant_ids.add(variant)
            for field in ('operator', 'operator_version', 'rationale'):
                _text(mutation[field], field)
            if not isinstance(mutation['context_sufficiency'], str) or mutation['context_sufficiency'] not in {'sufficient', 'insufficient', 'ambiguous'}:
                raise ValueError('invalid context_sufficiency')
            factors = mutation['changed_factors']
            if type(factors) is not list or not factors or any(not isinstance(f, str) or not f.strip() for f in factors):
                raise ValueError('changed_factors requires nonempty text list')
            groups = []
            for key in ('add_labels', 'remove_labels', 'invariant_labels', 'uncertain_labels'):
                labels = mutation[key]
                if type(labels) is not list or any(not isinstance(x, str) or x not in LABELS for x in labels) or len(set(labels)) != len(labels):
                    raise ValueError('mutation label sets must contain distinct known labels')
                groups.extend(labels)
            if set(groups) != set(LABELS) or len(groups) != len(LABELS):
                raise ValueError('mutation relation must partition all seven labels')
            relation = mutation['relation']
            if not isinstance(relation, str) or (relation == 'preserve' and (mutation['add_labels'] or mutation['remove_labels'] or mutation['uncertain_labels'])) or (relation == 'change' and (not (mutation['add_labels'] or mutation['remove_labels']) or mutation['uncertain_labels'])) or (relation == 'uncertainty' and not mutation['uncertain_labels']) or relation not in {'preserve', 'change', 'uncertainty'}:
                raise ValueError('mutation relation inconsistent with label effects')
        case = family['case']
        if not isinstance(case, str) or case not in CASES:
            raise ValueError('unknown scenario case')
        labels = family['intended_labels']
        if type(labels) is not list or any(not isinstance(x, str) or x not in LABELS for x in labels) or len(set(labels)) != len(labels):
            raise ValueError('intended_labels must be unique known labels')
        if (case == 'single' and len(labels) != 1) or (case == 'overlap' and len(labels) < 2) or (case in {'no_match_candidate', 'missing_context'} and labels):
            raise ValueError('case and intended_labels inconsistent')
        for key in ('topic', 'context', 'purpose', 'writing_style'):
            _text(family[key], key)
        # Topic/family renaming alone must not qualify as scenario expansion.
        semantic_key = tuple(' '.join(family[k].split()).casefold() for k in ('context', 'purpose', 'writing_style'))
        if semantic_key in semantics:
            raise ValueError('repeated context/purpose/writing_style; topic renaming is not diversity')
        semantics.add(semantic_key)
    coverage = value.get('coverage', {})
    _object(coverage, set(), {'minimum_positive_families', 'minimum_negative_families', 'minimum_case_families'})
    for key in ('minimum_positive_families', 'minimum_negative_families'):
        mapping = coverage.get(key, {})
        _object(mapping, set(), set(LABELS))
        for label, minimum in mapping.items():
            integer(minimum, key, maximum=len(families))
            actual = sum((label in f['intended_labels']) == (key == 'minimum_positive_families') for f in families)
            if actual < minimum:
                raise ValueError(f'coverage unmet: {key} {label}')
    counts = Counter(f['case'] for f in families)
    mapping = coverage.get('minimum_case_families', {})
    _object(mapping, set(), CASES)
    for case, minimum in mapping.items():
        integer(minimum, 'minimum_case_families', maximum=len(families))
        if counts[case] < minimum:
            raise ValueError(f'coverage unmet: {case}')
    validate_settings(value.get('near_duplicates'), default_enabled=True)
    return value


def stable_split(seed, family_id):
    slot = int(hashlib.sha256(f'{seed}:{family_id}'.encode()).hexdigest(), 16) % 10000
    return 'train_fixture' if slot < 6667 else 'development_fixture' if slot < 8333 else 'test_fixture'


def budget_envelope(spec, scenarios, max_repairs, max_rereviews, cap_micro):
    if spec is None:
        return {'status': 'token assumptions absent; dollar estimate unavailable', 'cap_micro': cap_micro,
                'scenario_design': 'external input; not executed or costed', 'execution_authorized': False}
    _object(spec, {'case_profiles'}, {'rates_micro_usd_per_million_tokens', 'scenario_design_tokens'})
    profiles = spec['case_profiles']
    cases = set(s['case'] for s in scenarios)
    _object(profiles, cases)
    for case, profile in profiles.items():
        _object(profile, STAGES, {'mutate'})
        for stage, tokens in profile.items():
            _object(tokens, {'input_tokens', 'visible_output_tokens', 'reasoning_tokens'})
            for key, amount in tokens.items():
                integer(amount, f'{case}.{stage}.{key}', maximum=10_000_000)
    totals = dict(input_tokens=0, visible_output_tokens=0, reasoning_tokens=0)
    design_tokens = spec.get('scenario_design_tokens', dict(totals))
    _object(design_tokens, set(totals))
    for key, amount in design_tokens.items():
        totals[key] += integer(amount, f'scenario_design.{key}', maximum=1_000_000_000)
    base_counts = Counter()
    for scenario in scenarios:
        count = len(scenario['variants'])
        base_counts[scenario['case']] += count
        mutation_count = len(scenario.get('mutations', []))
        profile = profiles[scenario['case']]
        if mutation_count and 'mutate' not in profile:
            raise ValueError('token profile must supply mutate stage for mutation scenarios')
        for key in totals:
            totals[key] += (count - mutation_count) * profile['generate'][key] + count * profile['review'][key]
            totals[key] += mutation_count * profile.get('mutate', profile['generate'])[key]
    optional = {}
    for group, stages, allowance in (('repair_and_review', ('repair', 'repair_review'), max_repairs),
                                      ('rereview', ('rereview',), max_rereviews)):
        bounds = {key: allowance * max(sum(profiles[c][stage][key] for stage in stages) for c in cases) for key in totals}
        optional[group] = bounds
        for key in totals:
            totals[key] += bounds[key]
    result = {'status': 'declared token envelope; not measured usage', 'base_candidates_by_case': dict(base_counts),
              'optional_upper_bounds': optional, 'totals': totals,
              'billed_output_tokens': totals['visible_output_tokens'] + totals['reasoning_tokens'],
              'scenario_design': {'tokens': design_tokens, 'status': 'externally declared; not executed'},
              'method': 'case-specific base profiles plus conservative independent token maxima for bounded optional calls; not a flat per-row cost',
              'cap_micro': cap_micro, 'execution_authorized': False}
    rates = spec.get('rates_micro_usd_per_million_tokens')
    if rates is None:
        result['dollar_cost_status'] = 'unknown; no rates supplied'
    else:
        _object(rates, {'input', 'output_including_reasoning'})
        for key, rate in rates.items():
            integer(rate, key, maximum=1_000_000_000)
        numerator = totals['input_tokens'] * rates['input'] + result['billed_output_tokens'] * rates['output_including_reasoning']
        result.update(estimated_upper_micro=(numerator + 999999) // 1000000,
                      rates_status='user-declared, unverified; not authorization or a provider quote')
        result['envelope_exceeds_cap'] = result['estimated_upper_micro'] > cap_micro
    return result


def configure_plan(smoke, *, seed, family_count=None, variants_per_family=5, requested_candidates=None,
                   cap_usd='10', max_repairs=12, max_rereviews=12, provider_mode='fixture', scenario_plan=None, live_provider='openai-responses', generation_model=None):
    integer(seed, 'seed', maximum=2**32 - 1)
    integer(variants_per_family, 'variants_per_family', minimum=1)
    if live_provider not in {'openai-responses','nous-chat'}:raise ValueError('unsupported live provider')
    if generation_model is not None and (generation_model != 'openai/gpt-6-luna' or provider_mode != 'live' or live_provider != 'nous-chat'):
        raise ValueError('generation override requires exact authorized ordinary Nous Luna route')
    if not isinstance(provider_mode, str) or provider_mode not in {'fixture', 'live'}:
        raise ValueError('provider_mode must be fixture or live')
    cap = dollars_to_micro(cap_usd)
    source = read_scenario_plan(scenario_plan) if scenario_plan is not None else None
    if provider_mode == 'live' and source is None:
        raise ValueError('live planning requires an explicit scenario plan; smoke fixtures are not live scenarios')
    families = source['families'] if source else smoke
    count = len(families)
    if family_count is not None and integer(family_count, 'family_count', minimum=1, maximum=100000) != count:
        raise ValueError('family_count must match explicit scenario families; provide a distinct scenario plan to expand')
    requested = integer(count * variants_per_family, 'requested candidate product', minimum=1)
    if requested_candidates is not None and integer(requested_candidates, 'requested_candidates', minimum=1) != requested:
        raise ValueError('requested_candidates must equal family_count * variants_per_family')
    integer(max_repairs, 'max_repairs', maximum=requested)
    integer(max_rereviews, 'max_rereviews', maximum=requested)
    scenarios = []
    for family in families:
        if any(m['variant'] >= variants_per_family for m in family.get('mutations', [])):
            raise ValueError('mutation variant exceeds variants_per_family')
        scenario = dict(family)
        scenario.setdefault('slice', 'ordinary')
        scenario.setdefault('diagnostic_tags', [])
        scenario.setdefault('mutations', [])
        if source:
            scenario['split'] = stable_split(seed, family['family_id']).replace('_fixture', '_planned' if provider_mode == 'live' else '_fixture')
        scenario['variants'] = list(range(variants_per_family))
        scenarios.append(scenario)
    scenarios.sort(key=lambda s: s['family_id'])
    all_ids=[f"{s['family_id']}-v{v}" for s in scenarios for v in s['variants']]
    allocation=source.get('rereview_allocation') if source else None
    if allocation is None:
        allocation=sorted(all_ids,key=lambda x:(not x.endswith('-v0'),x))[:max_rereviews]
    valid_ids=set(all_ids)
    if type(allocation) is not list or len(allocation)>max_rereviews or any(not isinstance(x,str) for x in allocation) or len(set(allocation))!=len(allocation) or any(x not in valid_ids for x in allocation):
        raise ValueError('rereview_allocation must name distinct planned records within max_rereviews')
    return {**({'role_models': {'generation': generation_model, 'review': 'openai/gpt-6.1-sol'}, 'routing_version': 1} if generation_model else {}), 'scenarios': scenarios, 'family_count': count, 'message_count': requested,
            'requested_candidates': requested, 'variants_per_family': variants_per_family,
            'cap_micro': cap, 'max_repairs': max_repairs, 'max_rereviews': max_rereviews,
            'rereview_allocation': allocation, 'rereview_policy': 'frozen record-ID allocation; no dynamic consumption by intent mismatch',
            'mode': 'fixture_only' if provider_mode == 'fixture' else 'live_planned', 'provider_mode': provider_mode,
            'provider': 'fixture' if provider_mode == 'fixture' else live_provider,
            'model': 'fixture-v1' if provider_mode == 'fixture' else ('openai/gpt-6.1-sol' if live_provider=='nous-chat' else 'gpt-6.1-sol'),
            'dataset_kind': 'software_fixture_not_corpus' if provider_mode == 'fixture' else 'scenario_plan_not_generated_corpus',
            'profile': 'external_scenarios' if source else 'smoke_test',
            'split_policy': 'sha256(seed:family_id) buckets 6667/1666/1667; stable under reordering/extension' if source else 'smoke 16/4/4 shuffled families',
            'topup_policy': 'none; requested candidates do not guarantee accepted rows',
            'mutation_relation_policy': 'hypotheses only; blind parent and descendant separately before controller comparison; not evaluated by fixtures',
            'content_origin': 'software_fixture' if provider_mode == 'fixture' else 'not_generated',
            'near_duplicates': validate_settings(source.get('near_duplicates') if source else None, default_enabled=source is not None),
            'token_budget_assumptions': source.get('token_budget') if source else None,
            'scenario_source_hash': digest(source) if source else None,
            'scenario_diversity': {'declared': source['diversity'] if source else None,
                                   'semantic_quality_verified': False,
                                   'fixture_generation': 'fixed mechanical phrases; scenario metadata is not rendered as semantic diversity'},
            'planned_slice_families': dict(Counter(s['slice'] for s in scenarios)),
            'coverage_requirements': source.get('coverage', {}) if source else {},
            'budget_estimate': budget_envelope(source.get('token_budget') if source else None, scenarios, max_repairs, max_rereviews, cap)}
