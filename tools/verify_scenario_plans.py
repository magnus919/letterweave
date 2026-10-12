"""Offline verification of published design hypotheses, never semantic truth."""
import argparse,json,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from email_corpus_forge.contracts import digest
from email_corpus_forge.planning import read_scenario_plan
from tools.verify_dataset import scan,parse


def verify_plans(directory):
    root=Path(directory)
    expected={'ordinary-inventory.json','challenge-inventory.json','context_sensitive-inventory.json','plan-checksums.json','REPRODUCIBILITY.md'}
    if root.is_symlink() or not root.is_dir() or {p.name for p in root.iterdir()}!=expected:raise ValueError('scenario sidecar allowlist mismatch')
    for p in root.iterdir():
        if p.is_symlink() or not p.is_file() or p.stat().st_size>64*1024*1024:raise ValueError('invalid plan sidecar file')
    meta=parse((root/'plan-checksums.json').read_text());scan(meta);scan((root/'REPRODUCIBILITY.md').read_text())
    if meta.get('kind')!='scenario_design_hypotheses_not_observed_labels' or meta.get('gold_labels') is not False or meta.get('statistical_independence') is not False:raise ValueError('scenario design truth/independence declaration missing')
    if not re.fullmatch('[0-9a-f]{64}',meta.get('code_fingerprint','')):raise ValueError('code fingerprint invalid')
    if set(meta.get('plans',{}))!={'ordinary','challenge','context_sensitive'}:raise ValueError('strata mismatch')
    ids=set();semantics=set();families=candidates=0
    for name,count,variants in [('ordinary',750,1),('challenge',100,2),('context_sensitive',50,1)]:
        item=meta['plans'][name]
        if item.get('file')!=name+'-inventory.json' or any(type(item.get(k)) is not int for k in ('families','variants_per_family','candidates')) or (item['families'],item['variants_per_family'],item['candidates'])!=(count,variants,count*variants):raise ValueError('declared stratum counts mismatch')
        path=root/item['file'];raw=parse(path.read_text());scan(raw)
        if digest(raw)!=item.get('canonical_sha256'):raise ValueError('canonical inventory hash mismatch')
        plan=read_scenario_plan(path)
        if len(plan['families'])!=count:raise ValueError('actual family count mismatch')
        for family in plan['families']:
            fid=family['family_id'].casefold()
            if fid in ids:raise ValueError('duplicate family across strata')
            ids.add(fid)
            semantic=tuple(' '.join(family[k].split()).casefold() for k in ('context','purpose','writing_style'))
            if semantic in semantics:raise ValueError('renamed design clone across strata')
            semantics.add(semantic)
            if len(family.get('mutations',[]))!=variants-1:raise ValueError('controlled variant count mismatch')
        families+=count;candidates+=count*variants
    if type(meta.get('family_count')) is not int or type(meta.get('planned_candidates')) is not int or (meta['family_count'],meta['planned_candidates'])!=(families,candidates):raise ValueError('cohort totals mismatch')
    return {'verified':True,'planned_families':families,'planned_candidates':candidates,'semantic_diversity_verified':False,'gold_labels':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plans',type=Path,required=True);args=p.parse_args()
    try:report=verify_plans(args.plans)
    except (ValueError,OSError,TypeError,KeyError) as e:print('Plan verification failed: '+str(e),file=sys.stderr);return 1
    print(json.dumps(report,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
