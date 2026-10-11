"""Bounded lexical candidate search; no embedding or semantic equivalence claim."""
from collections import defaultdict
import hashlib
import heapq
import re

DEFAULTS = {'enabled': False, 'jaccard_ppm': 900000, 'min_tokens': 20,
            'max_tokens': 4096, 'signature_size': 16, 'bucket_limit': 128,
            'candidate_limit': 64, 'max_edges': 10000, 'max_index_shingles': 250000, 'max_exact_entries': 100000}


def validate_settings(value=None, *, default_enabled=False):
    settings = {**DEFAULTS, 'enabled': default_enabled}
    if value is not None:
        if type(value) is not dict or set(value) - set(DEFAULTS):
            raise ValueError('unknown near-duplicate settings')
        settings.update(value)
    if type(settings['enabled']) is not bool:
        raise ValueError('near_duplicates.enabled must be boolean')
    bounds = {'jaccard_ppm': (500000, 1000000), 'min_tokens': (3, 1000), 'max_tokens': (20, 4096),
              'signature_size': (1, 32), 'bucket_limit': (1, 256), 'candidate_limit': (1, 256), 'max_edges': (1, 20000), 'max_index_shingles': (100, 1000000), 'max_exact_entries': (100, 200000)}
    for key, (lo, hi) in bounds.items():
        if type(settings[key]) is not int or not lo <= settings[key] <= hi:
            raise ValueError(f'invalid near-duplicate {key}')
    if settings['min_tokens'] > settings['max_tokens']:
        raise ValueError('min_tokens exceeds max_tokens')
    return settings


def near_duplicates(records, settings):
    """Audit every readable content record, regardless of its disposition.

    Pair lists are bounded observations, not complete counts. Exact indexing stores
    bounded record entries (not just unique hashes), so repeated identical records
    cannot silently grow memory. Same-family matches are reported, not quarantined.
    """
    report = {'method': 'lowercase ASCII words; short unigram/bigram or long 3-shingle Jaccard; smallest-hash candidate index',
              'semantic_equivalence_established': False, 'enabled': settings['enabled'],
              'comparisons': 0, 'edges': [], 'exact_pairs': [], 'normalized_exact_pairs': [], 'lexical_pairs': [],
              'quarantine_ids': [], 'coverage_limited_ids': [], 'audit_limited_ids': [],
              'short_records_skipped': 0, 'short_records_audited': 0, 'content_records_audited': 0,
              'unreadable_content_ids': [], 'truncated_ids': [], 'clusters': [],
              'pair_limit_per_field': settings['max_edges'],
              'pair_lists_complete': True,
              'limitations': 'bounded indexes/candidates/pair lists can miss matches; lexical comparisons use the same shingle width only; ASCII tokenization omits other characters; no semantic equivalence claim; numbers and negation can change meaning'}
    if not settings['enabled']:
        return report
    buckets, docs = defaultdict(list), {}
    quarantine, limited, audit_limited, parents = set(), set(), set(), {}
    exact, normalized_exact = defaultdict(list), defaultdict(list)
    exact_entries = normalized_entries = index_shingles = 0

    def root(item):
        parents.setdefault(item, item)
        while parents[item] != item:
            parents[item] = parents[parents[item]]
            item = parents[item]
        return item

    def append_pair(field, pair):
        if len(report[field]) < settings['max_edges']:
            report[field].append(pair)
        else:
            report['pair_lists_complete'] = False
            audit_limited.update((pair['left'], pair['right']))

    def pair_for(other, record, match, score=1000000):
        return {'left': other['id'], 'right': record['id'], 'jaccard_ppm': score,
                'cross_split': other['split'] != record['split'],
                'cross_family': other['family_id'] != record['family_id'], 'match': match}

    def cross_family(pair):
        if pair['cross_family']:
            quarantine.update((pair['left'], pair['right']))
            parents[root(pair['right'])] = root(pair['left'])
            append_pair('edges', pair)

    for record in sorted(records, key=lambda r: r['id']):
        content = record.get('content')
        rid = record['id']
        if not isinstance(content, dict) or any(not isinstance(content.get(k), str) for k in ('subject', 'body')):
            report['unreadable_content_ids'].append(rid)
            continue
        report['content_records_audited'] += 1
        literal = hashlib.sha256((content['subject'] + '\0' + content['body']).encode()).hexdigest()
        normalized = hashlib.sha256((' '.join(re.findall(r'[a-z0-9]+', content['subject'].casefold())) + '\n' +
                                     ' '.join(re.findall(r'[a-z0-9]+', content['body'].casefold()))).encode()).hexdigest()
        exact_candidates = exact.get(literal, ())
        normalized_candidates = normalized_exact.get(normalized, ())
        for candidates_for_hash in (exact_candidates, normalized_candidates):
            if len(candidates_for_hash) > settings['candidate_limit']:
                limited.add(rid)
                limited.update(other['id'] for other in candidates_for_hash)
        for other in exact_candidates[:settings['candidate_limit']]:
            append_pair('exact_pairs', pair_for(other, record, 'exact'))
        # Normalized detection retains the legacy cross-family edge behavior.
        for other in normalized_candidates[:settings['candidate_limit']]:
            pair = pair_for(other, record, 'normalized_exact')
            append_pair('normalized_exact_pairs', pair)
            cross_family(pair)
        if exact_entries < settings['max_exact_entries']:
            exact[literal].append(record)
            exact_entries += 1
        else:
            limited.add(rid)
        if normalized_entries < settings['max_exact_entries']:
            normalized_exact[normalized].append(record)
            normalized_entries += 1
        else:
            limited.add(rid)
        tokens = re.findall(r'[a-z0-9]+', (content['subject'] + '\n' + content['body']).casefold())
        if not tokens:
            report['unreadable_content_ids'].append(rid)
            continue
        short = len(tokens) < settings['min_tokens']
        if short:
            report['short_records_audited'] += 1
        if len(tokens) > settings['max_tokens']:
            report['truncated_ids'].append(rid)
            limited.add(rid)
        tokens = tokens[:settings['max_tokens']]
        width = 1 if len(tokens) == 1 else 2 if short else 3
        method = {1: 'unigram', 2: 'bigram', 3: '3-shingle'}[width]
        shingles = {int.from_bytes(hashlib.blake2b(' '.join(tokens[i:i+width]).encode(), digest_size=8).digest(), 'big')
                    for i in range(len(tokens)-width+1)}
        signature = heapq.nsmallest(settings['signature_size'], shingles)
        candidates = set()
        for key in signature:
            bucket = buckets[(width, key)]
            candidates.update(bucket)
            if len(bucket) >= settings['bucket_limit']:
                limited.add(rid)
                limited.update(bucket)
        if len(candidates) > settings['candidate_limit']:
            limited.add(rid)
            limited.update(candidates)
        for candidate in sorted(candidates)[:settings['candidate_limit']]:
            other = docs[candidate]
            intersection = len(shingles & other['shingles'])
            union = len(shingles | other['shingles'])
            report['comparisons'] += 1
            if union and intersection * 1000000 >= settings['jaccard_ppm'] * union:
                pair = pair_for(other, record, 'lexical', intersection * 1000000 // union)
                pair['lexical_method'] = method
                append_pair('lexical_pairs', pair)
                cross_family(pair)
        if index_shingles + len(shingles) > settings['max_index_shingles']:
            limited.add(rid)
            continue
        index_shingles += len(shingles)
        docs[rid] = {'id': rid, 'family_id': record['family_id'], 'split': record['split'], 'shingles': shingles}
        for key in signature:
            if len(buckets[(width, key)]) < settings['bucket_limit']:
                buckets[(width, key)].append(rid)
    clusters = defaultdict(list)
    for rid in sorted(parents):
        clusters[root(rid)].append(rid)
    report['clusters'] = sorted(clusters.values())
    families = {r['family_id'] for r in records if r['id'] in quarantine | limited}
    report['quarantine_families'] = sorted(families)
    report['quarantine_ids'] = sorted(r['id'] for r in records if r['family_id'] in families)
    report['indexed_shingles'] = index_shingles
    report['exact_index_entries'] = exact_entries
    report['normalized_exact_index_entries'] = normalized_entries
    report['coverage_limited_ids'] = sorted(limited)
    report['audit_limited_ids'] = sorted(audit_limited)
    if limited:
        report['pair_lists_complete'] = False
    return report
