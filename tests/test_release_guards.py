"""Offline behavior checks: live evidence cannot enter a fixture export."""
import json
from pathlib import Path
import tempfile
import unittest
from email_corpus_forge.contracts import LABELS
from email_corpus_forge.pipeline import create_plan,run_pipeline,export_run,LiveProviderBlocked
from email_corpus_forge.providers import PHRASES
from test_planning import inventory
from test_execution_quality import review
import test_nous_chat
from test_nous_chat import chat

class ReleaseGuardTests(unittest.TestCase):
    def test_reviewed_live_plan_still_cannot_export_or_change_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'plan.json';value=inventory(1)
            value['families'][0]['intended_labels']=[LABELS[0]]
            source.write_text(json.dumps(value))
            run=root/'live'
            manifest=create_plan(run,scenario_plan=source,provider_mode='live',live_provider='nous-chat',variants_per_family=1,max_repairs=0,max_rereviews=0)
            provider,transport=test_nous_chat.NousTests().provider([chat(json.dumps({'subject':'Fixture','body':PHRASES[LABELS[0]]})),chat(json.dumps(review([LABELS[0]])))],manifest)
            status=run_pipeline(run,provider);self.assertEqual(status['counts']['accepted'],1)
            ledger=(run/'ledger.jsonl').read_bytes();out=root/'forbidden'
            with self.assertRaises(LiveProviderBlocked):export_run(run,out)
            self.assertFalse(out.exists());self.assertEqual((run/'ledger.jsonl').read_bytes(),ledger)
            self.assertEqual(len(transport.create_calls),2)

    def test_fixture_export_is_explicitly_fixture_only(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);run=root/'fixture';create_plan(run);run_pipeline(run)
            out=root/'export';export_run(run,out)
            self.assertIn('Not a generated corpus, not gold labels',(out/'FIXTURE_ONLY.txt').read_text())

if __name__=='__main__':unittest.main()
