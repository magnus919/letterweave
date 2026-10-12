"""Verify a sanitized release offline. Does not certify semantic labels or rights."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

PAYLOAD = {'inputs.jsonl','labels.jsonl','provenance.jsonl','manifest.json','taxonomy.json','DATA_LICENSE.txt','DATA_CARD.md'}
LABELS = {'correspondence','transactions/records','alerts/updates','newsletters/publications','promotions/outreach','community/discussions','scheduling/invitations'}
PRIVATE = re.compile(r'(?:/(?:Users|home|Volumes)/|/var/folders/|[A-Za-z]:\\(?:Users|Documents and Settings)\\)',re.I)
SECRET = re.compile(r'(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----|Bearer\s+[A-Za-z0-9_.-]{20,}|(?:api[_ -]?key|access[_ -]?token)\s*[:=]\s*[A-Za-z0-9_-]{12,})',re.I)
PROVENANCE = {'row','id','family_id','split','slice','variant','parent_id','lineage_root','source_manifest_hash','controlled_transition_included','pool'}
MODEL_PROVENANCE = {'generation_model','generation_model_version','review_models','review_model_versions'}
MODEL_BASIS = 'accepted rows from immutable dispatch and raw response evidence'
SOL = 'openai/gpt-6.1-sol'
LUNA = 'openai/gpt-6-luna'
MODEL_VERSIONS = {SOL: {SOL, SOL+'-20260929'}, LUNA: {LUNA, LUNA+'-20260922'}}
SOURCE_ACTUAL = {'actual_generation_models','actual_generation_model_versions','actual_review_models','actual_review_model_versions'}


def model_list(value, *, allow_empty=False):
    if not isinstance(value,list) or (not value and not allow_empty) or any(not isinstance(x,str) or not x.strip() for x in value):
        fail('invalid model provenance list')
    if value!=sorted(set(value)):fail('model provenance lists must be sorted and unique')
    return value


def fail(message):
    raise ValueError(message)


def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:fail('duplicate JSON key')
        result[key]=value
    return result


def parse(text):
    return json.loads(text,object_pairs_hook=unique_object,parse_constant=lambda x:fail('nonfinite JSON'))


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def scan(value):
    if isinstance(value,str):
        if PRIVATE.search(value) or SECRET.search(value):fail('private path or credential-shaped release value')
    elif isinstance(value,dict):
        for key,item in value.items():scan(key);scan(item)
    elif isinstance(value,list):
        for item in value:scan(item)


def verify_dataset(directory):
    root=Path(directory)
    if not root.is_dir() or root.is_symlink():fail('dataset must be a real directory')
    if {p.name for p in root.iterdir()} != PAYLOAD|{'checksums.json'}:fail('unexpected or missing release file')
    contents={}
    for name in PAYLOAD|{'checksums.json'}:
        path=root/name
        if not path.is_file() or path.is_symlink() or path.stat().st_size>128*1024*1024:fail('invalid or oversized payload file')
        contents[name]=path.read_bytes()
    hashes=parse(contents['checksums.json'].decode())
    if not isinstance(hashes,dict) or set(hashes)!=PAYLOAD:fail('checksum payload allowlist mismatch')
    for name in PAYLOAD:
        if hashes[name]!=hashlib.sha256(contents[name]).hexdigest():fail('payload checksum mismatch')
    manifest=parse(contents['manifest.json'].decode());taxonomy=parse(contents['taxonomy.json'].decode())
    allowed_manifest={'release_name','release_version','contract_version','rubric_hash','kind','accepted_count','excluded_count','source_candidate_count','source_family_count','qa_excluded_ids','global_quarantined_ids','controlled_transition_count','sources','license','rights_holder','publication_reference','terms_evidence','gold_labels','semantic_equivalence_established','model_provenance_version','model_provenance_basis'}
    if not isinstance(manifest,dict) or set(manifest)-allowed_manifest:fail('manifest field allowlist mismatch')
    versioned='model_provenance_version' in manifest
    if versioned:
        if type(manifest['model_provenance_version']) is not int or manifest['model_provenance_version']!=1:fail('unsupported model provenance version')
        if manifest.get('model_provenance_basis')!=MODEL_BASIS:fail('model provenance basis mismatch')
    elif 'model_provenance_basis' in manifest:fail('model provenance basis requires version')
    if not isinstance(taxonomy,dict) or set(taxonomy)-{'version','labels','rubric'}:fail('taxonomy field allowlist mismatch')
    for value in (manifest,taxonomy):scan(value)
    for name in ('DATA_LICENSE.txt','DATA_CARD.md'):scan(contents[name].decode())
    if taxonomy.get('labels') is None or len(taxonomy['labels'])!=7 or set(taxonomy['labels'])!=LABELS:fail('taxonomy mismatch')
    if taxonomy.get('version')!=manifest.get('contract_version'):fail('taxonomy version mismatch')
    if not isinstance(taxonomy.get('rubric'),dict) or manifest.get('rubric_hash')!=hashlib.sha256(canonical(taxonomy['rubric'])).hexdigest():fail('rubric hash mismatch')
    if manifest.get('kind')!='fresh_synthetic_machine_labeled_not_gold' or manifest.get('gold_labels') is not False or manifest.get('semantic_equivalence_established') is not False:fail('release must explicitly disclaim gold/semantic truth')
    if manifest.get('license')!='MIT' or not all(isinstance(manifest.get(k),str) and manifest[k].strip() for k in ('rights_holder','terms_evidence','publication_reference')):fail('MIT rights declaration missing')
    if 'MIT License' not in contents['DATA_LICENSE.txt'].decode() or 'Permission is hereby granted' not in contents['DATA_LICENSE.txt'].decode() or 'not gold' not in contents['DATA_CARD.md'].decode().lower():fail('license/card declaration missing')
    sources=manifest.get('sources')
    if not isinstance(sources,list) or not sources:fail('source manifest declarations missing')
    source_fields={'manifest_hash','code_fingerprint','requested_candidates','family_count','model','provider'}
    if versioned:source_fields|=SOURCE_ACTUAL|{'role_models'}
    if any(not isinstance(s,dict) or set(s)-source_fields for s in sources):fail('source field allowlist mismatch')
    allowed_hashes={s.get('manifest_hash') for s in sources}
    if len(allowed_hashes)!=len(sources) or any(not isinstance(x,str) or not re.fullmatch('[0-9a-f]{64}',x) for x in allowed_hashes):fail('source hash declaration invalid')
    for source in sources:
        for field in ('requested_candidates','family_count'):
            if type(source.get(field)) is not int or source[field]<0:fail('invalid source count')
        if versioned:
            if source.get('role_models')!={'generation':LUNA,'review':SOL}:fail('source role model declaration mismatch')
            for field in SOURCE_ACTUAL:model_list(source.get(field),allow_empty=True)
    actual_models={s['manifest_hash']:{field:set() for field in SOURCE_ACTUAL} for s in sources}
    rows={}
    for name in ('inputs.jsonl','labels.jsonl','provenance.jsonl'):
        lines=contents[name].decode().splitlines()
        if len(lines)>200000 or any(not line.strip() for line in lines):fail('invalid JSONL rows')
        rows[name]=[parse(line) for line in lines]
        scan(rows[name])
    n=len(rows['inputs.jsonl'])
    if any(len(values)!=n for values in rows.values()):fail('misaligned table lengths')
    for key in ('accepted_count','excluded_count','source_candidate_count','source_family_count','controlled_transition_count'):
        if type(manifest.get(key)) is not int or manifest[key]<0:fail('invalid release count')
    if manifest['accepted_count']!=n or n+manifest['excluded_count']!=manifest['source_candidate_count']:fail('release count mismatch')
    if sum(s['requested_candidates'] for s in sources)!=manifest['source_candidate_count'] or sum(s['family_count'] for s in sources)!=manifest['source_family_count']:fail('source aggregate count mismatch')
    families={};ids={}
    for number,(content,label,provenance) in enumerate(zip(rows['inputs.jsonl'],rows['labels.jsonl'],rows['provenance.jsonl'])):
        if not isinstance(content,dict) or set(content)!={'subject','body'} or any(not isinstance(x,str) for x in content.values()) or not any(x.strip() for x in content.values()):fail('input metadata leakage or unreadable content')
        if set(label)!={'row','id','labels','decisions'} or set(provenance)!=(PROVENANCE|MODEL_PROVENANCE if versioned else PROVENANCE):fail('table field allowlist mismatch')
        if type(label['row']) is not int or label['row']!=number or type(provenance['row']) is not int or provenance['row']!=number or label['id']!=provenance['id']:fail('misaligned row IDs')
        if not isinstance(label['id'],str) or label['id'] in ids:fail('duplicate or invalid record ID')
        decisions=label['decisions']
        if not isinstance(decisions,dict) or set(decisions)!=LABELS or any(x not in ('present','absent') for x in decisions.values()):fail('nonbinary final decisions')
        if not isinstance(label['labels'],list) or len(set(label['labels']))!=len(label['labels']) or set(label['labels'])!={k for k,v in decisions.items() if v=='present'}:fail('labels differ from final decisions')
        if provenance['source_manifest_hash'] not in allowed_hashes:fail('unapproved source hash')
        if versioned:
            generation=provenance['generation_model'];generation_version=provenance['generation_model_version']
            if not isinstance(generation,str) or generation not in MODEL_VERSIONS:fail('unsupported generation model')
            if not isinstance(generation_version,str) or generation_version not in MODEL_VERSIONS[generation]:fail('generation model/version mismatch')
            reviews=model_list(provenance['review_models']);review_versions=model_list(provenance['review_model_versions'])
            if reviews!=[SOL] or any(v not in MODEL_VERSIONS[SOL] for v in review_versions):fail('review model/version mismatch')
            actual=actual_models[provenance['source_manifest_hash']]
            actual['actual_generation_models'].add(generation)
            actual['actual_generation_model_versions'].add(generation_version)
            actual['actual_review_models'].update(reviews)
            actual['actual_review_model_versions'].update(review_versions)
        if type(provenance['controlled_transition_included']) is not bool:fail('invalid controlled transition flag')
        if type(provenance['variant']) is not int or provenance['variant']<0:fail('invalid variant number')
        if provenance['parent_id'] is not None and not isinstance(provenance['parent_id'],str):fail('invalid parent ID')
        if provenance['parent_id']==provenance['id']:fail('self-parent lineage')
        if not isinstance(provenance['lineage_root'],str) or not provenance['lineage_root']:fail('invalid lineage root')
        if provenance['variant']==0 and (provenance['parent_id'] is not None or provenance['lineage_root']!=provenance['id']):fail('invalid root lineage')
        family,split=provenance['family_id'],provenance['split']
        if not isinstance(family,str) or not isinstance(split,str) or families.setdefault(family,split)!=split:fail('family split leakage')
        ids[label['id']]=provenance
    if versioned:
        for source in sources:
            for field in SOURCE_ACTUAL:
                if source[field]!=sorted(actual_models[source['manifest_hash']][field]):fail('source actual model aggregate mismatch')
    if len(families)>manifest['source_family_count']:fail('family count exceeds source declarations')
    if sum(r['controlled_transition_included'] for r in ids.values())!=manifest['controlled_transition_count']:fail('controlled transition count mismatch')
    for record in ids.values():
        parent=ids.get(record['parent_id'])
        if parent and (parent['family_id']!=record['family_id'] or parent['split']!=record['split'] or parent['lineage_root']!=record['lineage_root']):fail('descendant family/split/root leakage')
        if parent and parent['variant']>=record['variant']:fail('nonincreasing parent-child variant lineage')
        if record['controlled_transition_included'] is True and parent is None:fail('controlled descendant missing accepted parent')
    return {'verified':True,'accepted_count':n,'accepted_families':len(families),'semantic_quality_verified':False,'rights_independently_verified':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--dataset',type=Path,required=True)
    args=parser.parse_args(argv)
    try:result=verify_dataset(args.dataset)
    except (ValueError,OSError,TypeError,KeyError) as exc:
        print('Dataset verification failed: '+str(exc),file=sys.stderr);return 1
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
