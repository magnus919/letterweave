"""Offline, separately authorized, sanitized live corpus assembly; no publication."""
from dataclasses import dataclass
from contextlib import ExitStack
from pathlib import Path
import ctypes,errno,hashlib,json,os,re,shutil,sys,tempfile
from .contracts import LABELS,RUBRIC,VERSION,canonical,digest,validate_content
from .ledger import Ledger,IntegrityError,exclusive_lock,write_once
from .pipeline import load_manifest,_records,_quality_records,_verify_raw_evidence,LiveProviderBlocked,PendingOutcome
from .duplicates import near_duplicates

# Scan actual emitted values, never copy raw envelopes, controller plans or paths.
_PRIVATE = re.compile(r'(?:/(?:Users|home|Volumes)/|/var/folders/|[A-Za-z]:\\(?:Users|Documents and Settings)\\)',re.I)
_SECRET = re.compile(r'(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----|Bearer\s+[A-Za-z0-9_.-]{20,}|(?:api[_ -]?key|access[_ -]?token)\s*[:=]\s*[A-Za-z0-9_-]{12,})',re.I)


def _rename_new_directory(source, target):
    """Atomically publish a directory without replacing any existing path."""
    if sys.platform == 'win32':
        os.rename(source, target)  # Windows rename refuses an existing target.
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        fn = libc.renamex_np
        fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = fn(os.fsencode(source), os.fsencode(target), 4)  # RENAME_EXCL
    elif sys.platform.startswith('linux') and hasattr(libc, 'renameat2'):
        fn = libc.renameat2
        fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = fn(-100, os.fsencode(source), -100, os.fsencode(target), 1)  # RENAME_NOREPLACE
    else:
        raise OSError('atomic no-replace directory publication unavailable on this platform')
    if result != 0:
        error = ctypes.get_errno()
        if error in (errno.EEXIST, errno.ENOTEMPTY):
            raise FileExistsError(error, os.strerror(error), str(target))
        raise OSError(error, os.strerror(error), str(target))


def _public(value):
    if isinstance(value,str):
        if _PRIVATE.search(value) or _SECRET.search(value):
            raise ValueError('private path or credential-looking text in proposed release')
    elif isinstance(value,dict):
        for k,v in value.items():_public(k);_public(v)
    elif isinstance(value,(list,tuple)):
        for v in value:_public(v)
    return value


@dataclass(frozen=True)
class DatasetReleaseAuthorization:
    release_name: str
    version: str
    rights_holder: str
    publication_reference: str
    terms_evidence: str
    dataset_release_approved: bool=False
    redistribution_rights_confirmed: bool=False

    def check(self):
        if self.dataset_release_approved is not True or self.redistribution_rights_confirmed is not True:
            raise LiveProviderBlocked('dataset publication approval and applicable redistribution rights must be declared separately from code release')
        for name in ('release_name','version','rights_holder','publication_reference','terms_evidence'):
            value=getattr(self,name)
            if not isinstance(value,str) or not value.strip() or len(value)>1000:
                raise ValueError('release authorization requires bounded nonempty text')
            _public(value)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}',self.release_name):raise ValueError('release name must be a public slug')
        if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?',self.version):raise ValueError('release version must be semantic version text')


def _load_source(root):
    manifest=load_manifest(root)
    if manifest['provider_mode']!='live' or manifest['mode']=='fixture_only':
        raise LiveProviderBlocked('fixture runs cannot enter a live dataset release')
    ledger=Ledger(root,manifest['cap_micro']);events=ledger.events();_verify_raw_evidence(root,ledger)
    authority=[e['data'] for e in events if e['kind']=='private_pilot_authorized']
    if len(authority)!=1 or authority[0].get('content_origin')!='fresh_synthetic_private':
        raise LiveProviderBlocked('only declared fresh synthetic live evidence can be released; API/software fixtures forbidden')
    dispatched={e['data']['attempt_id'] for e in events if e['kind']=='dispatched'}
    settled={e['data']['attempt_id'] for e in events if e['kind']=='settled'}
    if dispatched-settled or ledger.balance()['reserved_micro']:
        raise PendingOutcome('unresolved provider outcomes or reservations prevent assembly')
    anchors={e['data']['record_id'] for e in events if e['kind']=='record_saved'}
    if anchors!={p.stem for p in (root/'records').glob('*.json')}:
        raise IntegrityError('unanchored or missing records prevent release; no recovery during assembly')
    records=_records(root,ledger)
    if len(records)!=manifest['message_count']:raise IntegrityError('incomplete source run cannot be released')
    expected={r['id'] for r in records if r.get('parent_id')}
    relation_anchors={e['data']['record_id'] for e in events if e['kind']=='relation_saved'}
    if relation_anchors!=expected or expected!={p.stem for p in (root/'relations').glob('*.json')}:
        raise IntegrityError('missing or unanchored relation evidence prevents release')
    for r in records:
        if r.get('kind')!='private_synthetic_quality_pilot' or r.get('content_origin') not in {'fresh_synthetic_private','not_generated'}:
            raise LiveProviderBlocked('fixture or mixed-origin record in live release')
    effective,_,_=_quality_records(root,ledger,records,manifest)
    return manifest,effective


def assemble_live_release(run_dirs,out_dir,*,authorization,qa_exclusions=None):
    """Assemble only final accepted projections; never export a private run wholesale.

    Authorization is an explicit caller declaration, not legal clearance. Historical
    source/rubric mismatches fail closed. Raw first/latest histories stay private.
    """
    if not isinstance(authorization,DatasetReleaseAuthorization):raise LiveProviderBlocked('dataset release authorization absent')
    authorization.check()
    roots=sorted({Path(p).resolve() for p in run_dirs},key=str);out=Path(out_dir)
    if not roots:raise ValueError('at least one live source required')
    target=out.resolve()
    if any(target==r or r in target.parents for r in roots):raise ValueError('release destination cannot be inside a source run')
    if out.exists() or out.is_symlink():raise FileExistsError('immutable release destination exists')
    qa=set(qa_exclusions or ())
    if any(not isinstance(x,str) for x in qa):raise ValueError('QA exclusions must be record IDs')
    with ExitStack() as stack:
        for root in roots:stack.enter_context(exclusive_lock(root/'.run.lock',nonblocking=True))
        sources=[];all_records=[];ids=set();families=set();reference=None;source_for={}
        for root in roots:
            m,records=_load_source(root)
            current=(m['contract_version'],m['rubric_hash'],m['model'],m['provider'],m['seed'],canonical(m['near_duplicates']))
            if reference is not None and current!=reference:raise IntegrityError('cohort source versions/settings differ')
            reference=current;source_hash=digest(m)
            these={r['family_id'] for r in records}
            if families&these:raise IntegrityError('one family must belong to one source manifest')
            families.update(these)
            for r in records:
                if r['id'] in ids:raise IntegrityError('duplicate record ID across source runs')
                ids.add(r['id']);source_for[r['id']]=source_hash
            all_records.extend(records);sources.append({'manifest_hash':source_hash,'code_fingerprint':m['code_fingerprint'],'requested_candidates':m['message_count'],'family_count':m['family_count'],'model':m['model'],'provider':m['provider']})
        if qa-ids:raise ValueError('QA exclusion ID absent from source evidence')
        if not json.loads(reference[-1])['enabled']:raise ValueError('global duplicate audit must be enabled for release')
        audit=near_duplicates(all_records,json.loads(reference[-1]));quarantine=set(audit['quarantine_ids'])
        if audit.get('coverage_limited_ids') or audit.get('audit_limited_ids') or not audit.get('pair_lists_complete',True):
            raise IntegrityError('incomplete global lexical audit prevents release')
        # Excluded ancestors cannot yield a controlled descendant silently.
        blocked=qa|quarantine
        for r in sorted(all_records,key=lambda x:(x['family_id'],x['variant'])):
            if r.get('parent_id') in blocked:blocked.add(r['id'])
        accepted=sorted((r for r in all_records if r['disposition']=='accepted' and r['assessment']['label_validity']=='accepted' and r['id'] not in blocked),key=lambda x:x['id'])
        input_rows=[];label_rows=[];provenance=[]
        accepted_ids={r['id'] for r in accepted}
        for n,r in enumerate(accepted):
            content=validate_content(r['content']);_public(content)
            decisions={l:r['final_judgments'][l]['decision'] for l in LABELS}
            if any(v not in {'present','absent'} for v in decisions.values()):raise IntegrityError('accepted release row contains unknown final decisions')
            labels=[l for l in LABELS if decisions[l]=='present']
            controlled=bool(r['controlled_transition_included'] and r.get('parent_id') in accepted_ids)
            input_rows.append(content);label_rows.append({'row':n,'id':r['id'],'labels':labels,'decisions':decisions})
            provenance.append({'row':n,**{k:r.get(k) for k in ['id','family_id','split','slice','variant','parent_id','lineage_root']},'source_manifest_hash':source_for[r['id']],'controlled_transition_included':controlled,'pool':r['assessment']['pool']})
        manifest={'release_name':authorization.release_name,'release_version':authorization.version,'contract_version':VERSION,'rubric_hash':digest(RUBRIC),'kind':'fresh_synthetic_machine_labeled_not_gold','accepted_count':len(accepted),'excluded_count':len(all_records)-len(accepted),'source_candidate_count':len(all_records),'source_family_count':len(families),'qa_excluded_ids':sorted(qa),'global_quarantined_ids':sorted(quarantine),'controlled_transition_count':sum(r['controlled_transition_included'] for r in provenance),'sources':sorted(sources,key=lambda x:x['manifest_hash']),'license':'MIT','rights_holder':authorization.rights_holder,'publication_reference':authorization.publication_reference,'terms_evidence':authorization.terms_evidence,'gold_labels':False,'semantic_equivalence_established':False}
        for value in [input_rows,label_rows,provenance,manifest]:_public(value)
        out.parent.mkdir(parents=True,exist_ok=True);temp=Path(tempfile.mkdtemp(prefix='.release-',dir=out.parent))
        try:
            for name,values in [('inputs.jsonl',input_rows),('labels.jsonl',label_rows),('provenance.jsonl',provenance)]:
                (temp/name).write_bytes(b''.join(canonical(x)+b'\n' for x in values))
            write_once(temp/'manifest.json',manifest);write_once(temp/'taxonomy.json',{'version':VERSION,'labels':list(LABELS),'rubric':RUBRIC})
            # Stable license text, no wall-clock date or source-machine paths.
            license_text=_MIT
            license_text=re.sub(r'Copyright \(c\).*',f'Copyright (c) {authorization.rights_holder}',license_text,count=1)
            (temp/'DATA_LICENSE.txt').write_text(license_text)
            (temp/'DATA_CARD.md').write_text(f'# {authorization.release_name} {authorization.version}\n\nFresh synthetic English emails; machine-labeled, not gold. No private Gmail content or copied upstream corpus is authorized.\n\n{len(accepted)} accepted rows from {len(families)} planned families; {len(all_records)-len(accepted)} source slots excluded. Unknown/failed/QA-excluded rows are omitted from binary-label inputs. All-negative decided vectors are valid.\n\nLabels describe observable purpose and overlap. Review agreement, literal anchors and lexical duplicate checks do not establish semantic accuracy, population prevalence or training suitability. Families and descendants are correlated; intended labels are not gold.\n\nMIT data license; rights holder: {authorization.rights_holder}. Applicable terms evidence: {authorization.terms_evidence}. Publication reference: {authorization.publication_reference}. No raw API envelopes, hidden reasoning, account settings or private paths are included.\n')
            for p in temp.rglob('*'):
                if p.is_file():_public(p.read_text())
            hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(temp.iterdir()) if p.is_file()}
            write_once(temp/'checksums.json',hashes)
            if out.exists():raise FileExistsError('release destination appeared during assembly')
            _rename_new_directory(temp,out)
        finally:
            if temp.exists():shutil.rmtree(temp)
        return manifest


_MIT='''MIT License

Copyright (c) rights holder

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''
