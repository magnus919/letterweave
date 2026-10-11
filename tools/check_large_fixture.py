"""Disposable large fixture execution/resume proof, never a synthetic corpus."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch
import email_corpus_forge.pipeline as pipeline
from email_corpus_forge.contracts import LABELS
from email_corpus_forge.providers import FixtureProvider


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--families',type=int,default=2000)
    parser.add_argument('--variants',type=int,default=5)
    parser.add_argument('--interrupt-after',type=int,default=2500)
    args=parser.parse_args()
    size=args.families*args.variants
    if not 1 <= args.families <= 10000 or not 0 < args.interrupt_after < size <= 50000:
        raise ValueError('bounded fixture benchmark dimensions invalid')
    begin=time.monotonic()
    with tempfile.TemporaryDirectory(prefix='email-forge-large-fixture-') as folder:
        root=Path(folder);run=root/'run';source=root/'source.json'
        source.write_text(json.dumps({'schema_version':1,'diversity':{'description':'Mechanical stress inputs; not independent semantic situations'},
           'near_duplicates':{'enabled':False},'families':[{'family_id':f's{i:05d}','case':'single','intended_labels':[LABELS[i%7]],
              'topic':f'fixture {i}','context':f'Artificial validator situation {i}','purpose':'Test execution mechanics',
              'writing_style':'Mechanical'} for i in range(args.families)]}))
        manifest=pipeline.create_plan(run,scenario_plan=source,variants_per_family=args.variants,max_repairs=0,max_rereviews=0)
        original=pipeline._save_record; count=0
        def interrupt(directory,ledger,record):
            nonlocal count
            original(directory,ledger,record);count+=1
            if count==args.interrupt_after:
                raise RuntimeError('controlled checkpoint interruption')
        first=FixtureProvider()
        try:
            with patch('email_corpus_forge.pipeline._save_record',side_effect=interrupt):
                pipeline.run_pipeline(run,first)
        except RuntimeError as error:
            if str(error)!='controlled checkpoint interruption': raise
        checkpoint=pipeline.status_run(run)
        assert checkpoint['processed']==args.interrupt_after
        hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (run/'raw').glob('*.json')}
        resumed=FixtureProvider();report=pipeline.run_pipeline(run,resumed)
        assert report['processed']==size and report['status']=='complete'
        dispatches=sum(stage=='generate' for stage,_ in first.calls+resumed.calls)
        assert dispatches==size
        assert all(hashlib.sha256((run/'raw'/name).read_bytes()).hexdigest()==value for name,value in hashes.items())
        again=FixtureProvider();assert pipeline.run_pipeline(run,again)==report and not again.calls
        pipeline.export_run(run,root/'export')
        evidence={'scope':'offline mechanical fixture execution; not corpus quality or semantic diversity',
                  'code_fingerprint':manifest['code_fingerprint'],'families':args.families,'requested_candidates':size,
                  'checkpoint_processed':checkpoint['processed'],'final_counts':report['counts'],
                  'generate_dispatches':dispatches,'prior_raw_hashes_verified':len(hashes),
                  'completed_resume_dispatches':len(again.calls),'budget':report['budget'],
                  'near_duplicate_check_enabled':False,'export_completed':True,'live_calls':0,
                  'elapsed_seconds':round(time.monotonic()-begin,3),'temporary_artifacts_removed_on_exit':True}
    (Path(__file__).resolve().parents[1]/'docs'/'large-fixture-verification.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(evidence,indent=2))


if __name__=='__main__':main()
