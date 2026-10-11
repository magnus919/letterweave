"""Disposable offline release tests; mocked fresh metadata is not real API data."""
import json
import io
from contextlib import redirect_stdout
from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from email_corpus_forge.contracts import LABELS,digest
from email_corpus_forge.pipeline import create_plan,run_pipeline
from email_corpus_forge.nous_chat import NousChatProvider
from email_corpus_forge.openai_responses import PrivatePilotAuthorization
from email_corpus_forge.release import DatasetReleaseAuthorization,assemble_live_release,_rename_new_directory
from test_openai_responses import OfflineTransport
from test_nous_chat import chat
from test_execution_quality import review
from test_planning import inventory


class LiveReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def authorization(self,**changes):
        values=dict(release_name='example-corpus',version='0.3.3',rights_holder='Example author',
                    publication_reference='offline-test-approval',terms_evidence='Offline test rights assertion, not provider clearance',
                    dataset_release_approved=True,redistribution_rights_confirmed=True)
        values.update(changes)
        return DatasetReleaseAuthorization(**values)

    def build_run(self,name='source',body='Please reply with your thoughts.',unknown=False,fresh=True,pending=False,divergent=False):
        directory=self.root/name;source=self.root/(name+'.json')
        plan=inventory(1);plan['families'][0]['intended_labels']=[LABELS[0]]
        source.write_text(json.dumps(plan))
        manifest=create_plan(directory,scenario_plan=source,provider_mode='live',live_provider='nous-chat',variants_per_family=1,max_repairs=0,max_rereviews=1 if divergent else 0)
        judgments=review(unknown=[LABELS[0]]) if unknown else review()
        if not unknown:
            judgments['judgments'][LABELS[0]].update(decision='present',evidence=[body])
        transport=OfflineTransport([chat(json.dumps({'subject':'Message','body':body})),chat(json.dumps(judgments))])
        if divergent:
            transport.responses=[transport.responses[0],chat(json.dumps(review())),transport.responses[1]]
        if pending:
            transport.responses=transport.responses[:1]
        # Explicit mocked origin exercise: never a real inference transport.
        transport.is_offline_fixture=not fresh
        auth=PrivatePilotAuthorization(digest(manifest),'offline-only',10000000,True,True,True)
        run_pipeline(directory,NousChatProvider(transport,authorization=auth))
        return directory

    def test_unapproved_dataset_or_unconfirmed_rights_rejected(self):
        run=self.build_run()
        for changes in ({'dataset_release_approved':False},{'redistribution_rights_confirmed':False}):
            with self.subTest(changes=changes),self.assertRaises((ValueError,RuntimeError)):
                assemble_live_release([run],self.root/'denied',authorization=self.authorization(**changes))
        self.assertFalse((self.root/'denied').exists())

    def test_fixture_origin_and_mixed_origins_rejected(self):
        fresh=self.build_run('fresh');fixture=self.build_run('fixture',fresh=False)
        for runs in ([fixture],[fresh,fixture]):
            with self.assertRaises((ValueError,RuntimeError)):
                assemble_live_release(runs,self.root/'release',authorization=self.authorization())
        self.assertFalse((self.root/'release').exists())

    def test_private_path_and_secret_shaped_reader_content_rejected(self):
        for n,body in enumerate(('/Users/example/private/mail.txt','token sk-'+('a'*40))):
            run=self.build_run('unsafe'+str(n),body=body)
            with self.assertRaises((ValueError,RuntimeError)):
                assemble_live_release([run],self.root/('out'+str(n)),authorization=self.authorization())

    def test_ordinary_secret_and_token_words_are_not_credentials(self):
        run=self.build_run(body='The secret garden discussion uses a token for attendance at example.org.')
        result=assemble_live_release([run],self.root/'release',authorization=self.authorization())
        self.assertEqual(result['accepted_count'],1)
        self.assertIn('secret garden',(self.root/'release/inputs.jsonl').read_text())

    def test_unknown_record_not_emitted_as_complete_negative(self):
        run=self.build_run(unknown=True)
        out=self.root/'release'
        assemble_live_release([run],out,authorization=self.authorization())
        self.assertEqual((out/'inputs.jsonl').read_text(),'')
        self.assertEqual((out/'labels.jsonl').read_text(),'')

    def test_disagreeing_history_does_not_release_first_pass_all_negative(self):
        run=self.build_run(divergent=True);out=self.root/'release'
        result=assemble_live_release([run],out,authorization=self.authorization())
        self.assertEqual(result['accepted_count'],0)
        self.assertEqual((out/'labels.jsonl').read_text(),'')

    def test_deterministic_bytes_final_labels_and_no_overwrite(self):
        run=self.build_run();first=self.root/'one';second=self.root/'two'
        assemble_live_release([run],first,authorization=self.authorization())
        assemble_live_release([run],second,authorization=self.authorization())
        first_files={str(p.relative_to(first)):p.read_bytes() for p in first.rglob('*') if p.is_file()}
        second_files={str(p.relative_to(second)):p.read_bytes() for p in second.rglob('*') if p.is_file()}
        self.assertEqual(first_files,second_files)
        labels=json.loads((first/'labels.jsonl').read_text())
        self.assertIn(LABELS[0],labels['labels'])
        self.assertNotIn('/Users/',json.dumps(first_files,default=lambda x:x.decode()))
        with self.assertRaises((FileExistsError,ValueError,RuntimeError)):
            assemble_live_release([run],first,authorization=self.authorization())
        self.assertEqual(first_files,{str(p.relative_to(first)):p.read_bytes() for p in first.rglob('*') if p.is_file()})

    def test_explicit_qa_exclusion_omits_content_and_reports_count(self):
        run=self.build_run();out=self.root/'release'
        result=assemble_live_release([run],out,authorization=self.authorization(),qa_exclusions={'s00000-v0'})
        self.assertEqual(result['accepted_count'],0)
        self.assertEqual(result['excluded_count'],1)
        self.assertEqual((out/'inputs.jsonl').read_text(),'')

    def test_duplicate_ids_across_source_runs_rejected(self):
        a=self.build_run('a');b=self.build_run('b')
        with self.assertRaises((ValueError,RuntimeError)):
            assemble_live_release([a,b],self.root/'release',authorization=self.authorization())

    def test_missing_generation_evidence_rejected_without_partial_bundle(self):
        run=self.build_run()
        next((run/'raw').glob('*-generate.json')).unlink()
        with self.assertRaises((ValueError,RuntimeError)):
            assemble_live_release([run],self.root/'release',authorization=self.authorization())
        self.assertFalse((self.root/'release').exists())

    def test_pending_review_outcome_cannot_be_released(self):
        run=self.build_run(pending=True)
        with self.assertRaises((ValueError,RuntimeError)):
            assemble_live_release([run],self.root/'release',authorization=self.authorization())
        self.assertFalse((self.root/'release').exists())

    def test_assembly_interruption_cleans_staging_without_partial_release(self):
        run=self.build_run();out=self.root/'release'
        with patch('email_corpus_forge.release._rename_new_directory',side_effect=OSError('offline interruption')):
            with self.assertRaises(OSError):
                assemble_live_release([run],out,authorization=self.authorization())
        self.assertFalse(out.exists())
        self.assertEqual(list(self.root.glob('.release-*')),[])

    def test_unknown_qa_id_rejected_instead_of_silent_omission(self):
        run=self.build_run()
        with self.assertRaises(ValueError):
            assemble_live_release([run],self.root/'release',authorization=self.authorization(),qa_exclusions={'absent-id'})
        self.assertFalse((self.root/'release').exists())

    def test_release_metadata_cannot_leak_paths_or_credentials(self):
        run=self.build_run()
        for changes in ({'terms_evidence':'/Users/example/private/terms.txt'},
                        {'publication_reference':'Bearer '+('a'*30)},
                        {'release_name':'../escape'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                assemble_live_release([run],self.root/'release',authorization=self.authorization(**changes))
        self.assertFalse((self.root/'release').exists())

    def test_public_tables_exclude_raw_history_and_controller_fields(self):
        run=self.build_run();out=self.root/'release'
        assemble_live_release([run],out,authorization=self.authorization())
        content=json.loads((out/'inputs.jsonl').read_text())
        labels=json.loads((out/'labels.jsonl').read_text())
        provenance=json.loads((out/'provenance.jsonl').read_text())
        self.assertEqual(set(content),{'subject','body'})
        self.assertEqual(set(labels),{'row','id','labels','decisions'})
        self.assertEqual(set(labels['decisions']),set(LABELS))
        self.assertTrue(all(value in {'present','absent'} for value in labels['decisions'].values()))
        self.assertFalse({'reviews','intended_labels','raw_response','rationale','model_settings'} & set(provenance))
        self.assertIn('MIT License',(out/'DATA_LICENSE.txt').read_text())
        self.assertIn('not gold',(out/'DATA_CARD.md').read_text())

    def test_atomic_publish_refuses_empty_destination_created_before_rename(self):
        source=self.root/'staged';target=self.root/'destination'
        source.mkdir();(source/'payload').write_text('staged evidence');target.mkdir()
        original_inode=target.stat().st_ino
        with self.assertRaises(FileExistsError):
            _rename_new_directory(source,target)
        self.assertEqual(target.stat().st_ino,original_inode)
        self.assertEqual(list(target.iterdir()),[])
        self.assertEqual((source/'payload').read_text(),'staged evidence')

    def test_atomic_publish_preserves_existing_destination_marker(self):
        source=self.root/'staged';target=self.root/'destination'
        source.mkdir();target.mkdir();(target/'marker').write_text('original')
        with self.assertRaises(FileExistsError):
            _rename_new_directory(source,target)
        self.assertEqual((target/'marker').read_text(),'original')
        self.assertTrue(source.exists())

    def test_cli_assembly_uses_explicit_authorization_file(self):
        from email_corpus_forge.cli import main
        run=self.build_run();out=self.root/'release';authfile=self.root/'authorization.json'
        authfile.write_text(json.dumps(asdict(self.authorization())))
        captured=io.StringIO()
        with redirect_stdout(captured):
            code=main(['assemble-release','--runs',str(run),'--out',str(out),'--authorization',str(authfile)])
        self.assertEqual(code,0)
        self.assertEqual(json.loads(captured.getvalue())['accepted_count'],1)
        self.assertTrue((out/'DATA_LICENSE.txt').is_file())


if __name__=='__main__':
    unittest.main()
