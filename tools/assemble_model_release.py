"""Offline immutable dataset assembly with dispatch-anchored public model provenance."""
from contextlib import ExitStack
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from email_corpus_forge.contracts import canonical, digest
from email_corpus_forge.ledger import Ledger, IntegrityError, exclusive_lock
from email_corpus_forge.pipeline import load_manifest
from email_corpus_forge.nous_chat import NousChatProvider
from email_corpus_forge.nous_roles import LunaNousChatProvider
from email_corpus_forge.release import (DatasetReleaseAuthorization, assemble_live_release,
                                       _public, _rename_new_directory)

FILES = {'inputs.jsonl', 'labels.jsonl', 'provenance.jsonl', 'manifest.json',
         'taxonomy.json', 'DATA_LICENSE.txt', 'DATA_CARD.md', 'checksums.json'}
VERSIONS = {'openai/gpt-6-luna-20260922': 'openai/gpt-6-luna',
            'openai/gpt-6.1-sol-20260929': 'openai/gpt-6.1-sol'}
REVIEW_STAGES = {'review', 'rereview', 'repair_review'}
BASIS = 'accepted rows from immutable dispatch and raw response evidence'


def _snapshot(root):
    # Locks contain no source evidence and may already be created by read helpers.
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and not p.name.endswith('.lock')}


def _rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def _check_files(root):
    if {p.name for p in root.iterdir()} != FILES or any(not p.is_file() or p.is_symlink() for p in root.iterdir()):
        raise IntegrityError('release must contain exactly eight regular files')
    hashes = json.loads((root / 'checksums.json').read_text())
    expected = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                for name in FILES - {'checksums.json'}}
    if hashes != expected:
        raise IntegrityError('release checksums do not match exact file set')


def _attempt(root, attempt_id, stage, events):
    these = [e for e in events if e['data'].get('attempt_id') == attempt_id]
    dispatches = [e['data'] for e in these if e['kind'] == 'dispatched']
    if len(dispatches) != 1 or dispatches[0].get('stage') != stage:
        raise IntegrityError('missing or ambiguous immutable stage dispatch')
    envelope = json.loads((root / 'raw' / (attempt_id + '.json')).read_text())
    anchors = [e['data'] for e in these if e['kind'] in {'raw_written', 'completed'}]
    if ({e['kind'] for e in these} & {'raw_written', 'completed', 'settled'}) != {'raw_written', 'completed', 'settled'}:
        raise IntegrityError('accepted row requires completed, settled, anchored raw evidence')
    if any(a.get('raw_hash') != digest(envelope) for a in anchors):
        raise IntegrityError('raw hash anchor mismatch')
    d = dispatches[0]
    response = envelope['response']
    if (response.get('outcome') != 'content' or
            response.get('provider_status') != 'completed' or
            not isinstance(response.get('text'), str) or not response['text'].strip()):
        raise IntegrityError('accepted evidence requires completed nonempty content response')
    if (envelope.get('attempt_id') != attempt_id or envelope.get('stage') != stage or
            envelope.get('packet_hash') != digest(envelope['packet']) or
            d.get('packet_hash') != envelope['packet_hash'] or
            envelope.get('response_hash') != digest(response) or
            response.get('model') != d.get('model')):
        raise IntegrityError('raw envelope differs from immutable dispatch')
    alias = response['model']
    adapters = {'openai/gpt-6.1-sol': NousChatProvider,
                'openai/gpt-6-luna': LunaNousChatProvider}
    if alias not in adapters:
        raise IntegrityError('actual response model has no verified normalization adapter')
    try:
        normalized = adapters[alias](None).normalize_response(response.get('raw_response'))
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise IntegrityError('original provider response cannot be normalized') from exc
    fields = ('model', 'text', 'outcome', 'provider_status',
              'input_tokens', 'output_tokens', 'reasoning_tokens')
    if any(getattr(normalized, field) != response.get(field) for field in fields):
        raise IntegrityError('stored normalized response differs from original provider evidence')
    version = (response.get('raw_response') or {}).get('model')
    if not isinstance(alias, str) or not alias or not isinstance(version, str) or not version:
        raise IntegrityError('actual model identity absent')
    if VERSIONS.get(version, version) != alias:
        raise IntegrityError('raw model version does not match normalized dispatch alias')
    request = response.get('request_payload')
    if not isinstance(request, dict) or request.get('model') != alias:
        raise IntegrityError('actual request wire model does not match dispatch')
    _public(alias); _public(version)
    return alias, version, envelope


def assemble_model_release(run_dirs, out_dir, *, authorization, qa_exclusions=None):
    """Create a new sanitized release; never modify a source or existing release."""
    if not isinstance(authorization, DatasetReleaseAuthorization):
        raise ValueError('explicit dataset release authorization required')
    authorization.check()
    roots = sorted({Path(p).resolve() for p in run_dirs}, key=str)
    out = Path(out_dir).resolve()
    if not roots or any(out == r or r in out.parents for r in roots):
        raise ValueError('destination must be outside every source')
    if out.exists() or out.is_symlink():
        raise FileExistsError('immutable release destination exists')
    out.parent.mkdir(parents=True, exist_ok=True)
    with ExitStack() as locks:
        for root in roots:
            locks.enter_context(exclusive_lock(root / '.run.lock', nonblocking=True))
        before = {root: _snapshot(root) for root in roots}
    work = Path(tempfile.mkdtemp(prefix='.model-release-', dir=out.parent))
    try:
        base = work / 'base'
        assemble_live_release(roots, base, authorization=authorization, qa_exclusions=qa_exclusions)
        _check_files(base)
        candidate = work / 'enriched'
        shutil.copytree(base, candidate)
        provenance = _rows(base / 'provenance.jsonl')
        inputs = _rows(base / 'inputs.jsonl')
        labels = _rows(base / 'labels.jsonl')
        manifest = json.loads((base / 'manifest.json').read_text())
        if not (len(provenance) == len(inputs) == len(labels) == manifest['accepted_count']):
            raise IntegrityError('accepted projection lengths differ')
        with ExitStack() as locks:
            for root in roots:
                locks.enter_context(exclusive_lock(root / '.run.lock', nonblocking=True))
            source_data = {}
            for root in roots:
                if _snapshot(root) != before[root]:
                    raise IntegrityError('source evidence changed during base assembly')
                m = load_manifest(root)
                ledger = Ledger(root, m['cap_micro'])
                events = ledger.events()
                h = digest(m)
                if h in source_data:
                    raise IntegrityError('ambiguous source manifest hash')
                source_data[h] = (root, m, events)
            for n, row in enumerate(provenance):
                if row['row'] != n or labels[n]['row'] != n or row['id'] != labels[n]['id']:
                    raise IntegrityError('row identity alignment mismatch')
                root, m, events = source_data[row['source_manifest_hash']]
                rid = row['id']
                record = json.loads((root / 'records' / (rid + '.json')).read_text())
                saved = [e['data'] for e in events if e['kind'] == 'record_saved' and e['data'].get('record_id') == rid]
                if len(saved) != 1 or saved[0].get('record_hash') != digest(record):
                    raise IntegrityError('accepted record lacks exact immutable anchor')
                if record.get('content_origin') != 'fresh_synthetic_private' or record.get('content') != inputs[n]:
                    raise IntegrityError('accepted row has no matching generated content')
                generations = [(s, rid + '-' + s) for s in ('generate', 'mutate')
                               if any(e['kind'] == 'dispatched' and e['data'].get('attempt_id') == rid + '-' + s for e in events)]
                if len(generations) != 1:
                    raise IntegrityError('accepted record generation identity ambiguous or absent')
                stage, aid = generations[0]
                alias, version, envelope = _attempt(root, aid, stage, events)
                # Repaired content requires a separately specified provenance policy.
                if json.loads(envelope['response']['text']) != inputs[n]:
                    raise IntegrityError('accepted content differs from generation/mutation evidence')
                row['generation_model'], row['generation_model_version'] = alias, version
                reviews = []
                paid_review_history = []
                for e in events:
                    if e['kind'] != 'dispatched':
                        continue
                    d = e['data']; s = d.get('stage'); a = d.get('attempt_id')
                    if s in REVIEW_STAGES and a == rid + '-' + s:
                        ra, rv, re = _attempt(root, a, s, events)
                        if {k: re['packet'].get(k) for k in ('subject', 'body')} != inputs[n]:
                            raise IntegrityError('review evidence does not review accepted content')
                        try:
                            paid_review = json.loads(re['response']['text'])
                        except (ValueError, TypeError) as exc:
                            raise IntegrityError('paid review response is not valid JSON') from exc
                        paid_review_history.append(paid_review)
                        reviews.append((ra, rv))
                if not reviews:
                    raise IntegrityError('accepted row has no actual paid review evidence')
                if paid_review_history != record.get('reviews'):
                    raise IntegrityError('paid review responses differ from saved ordered review history')
                row['review_models'] = sorted({a for a, _ in reviews})
                row['review_model_versions'] = sorted({v for _, v in reviews})
            for source in manifest['sources']:
                _, m, _ = source_data[source['manifest_hash']]
                source['role_models'] = m.get('role_models', {'generation': m['model'], 'review': m['model']})
                accepted = [r for r in provenance if r['source_manifest_hash'] == source['manifest_hash']]
                source['actual_generation_models'] = sorted({r['generation_model'] for r in accepted})
                source['actual_generation_model_versions'] = sorted({r['generation_model_version'] for r in accepted})
                source['actual_review_models'] = sorted({v for r in accepted for v in r['review_models']})
                source['actual_review_model_versions'] = sorted({v for r in accepted for v in r['review_model_versions']})
            manifest['model_provenance_version'] = 1
            manifest['model_provenance_basis'] = BASIS
            _public(provenance); _public(manifest)
            (candidate / 'provenance.jsonl').write_bytes(b''.join(canonical(r) + b'\n' for r in provenance))
            (candidate / 'manifest.json').write_bytes(canonical(manifest) + b'\n')
            for name in FILES - {'provenance.jsonl', 'manifest.json', 'checksums.json'}:
                if (candidate / name).read_bytes() != (base / name).read_bytes():
                    raise IntegrityError('base public projection changed')
            old = _rows(base / 'provenance.jsonl')
            fields = {'generation_model', 'generation_model_version', 'review_models', 'review_model_versions'}
            if [{k: v for k, v in r.items() if k not in fields} for r in provenance] != old:
                raise IntegrityError('labels or lineage provenance changed')
            for file in candidate.iterdir():
                _public(file.read_text())
            checksums = {name: hashlib.sha256((candidate / name).read_bytes()).hexdigest()
                         for name in sorted(FILES - {'checksums.json'})}
            (candidate / 'checksums.json').write_bytes(canonical(checksums) + b'\n')
            _check_files(candidate)
            for root in roots:
                if _snapshot(root) != before[root]:
                    raise IntegrityError('source evidence changed during enrichment')
            _rename_new_directory(candidate, out)
        return manifest
    finally:
        shutil.rmtree(work)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', nargs='+', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--authorization', required=True, type=Path)
    parser.add_argument('--qa-exclusions', type=Path)
    args = parser.parse_args()
    authorization = DatasetReleaseAuthorization(**json.loads(args.authorization.read_text()))
    exclusions = json.loads(args.qa_exclusions.read_text()) if args.qa_exclusions else []
    if not isinstance(exclusions, list) or any(not isinstance(x, str) for x in exclusions):
        raise ValueError('QA exclusions must be a JSON list of record IDs')
    result = assemble_model_release(args.runs, args.out, authorization=authorization, qa_exclusions=exclusions)
    print(json.dumps({'accepted_count': result['accepted_count'], 'model_provenance_version': 1}))


if __name__ == '__main__':
    main()
