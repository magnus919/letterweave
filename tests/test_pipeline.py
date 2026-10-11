"""End-to-end safety assertions over explicitly artificial offline fixtures."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from email_corpus_forge.ledger import IntegrityError
from email_corpus_forge.pipeline import create_plan, export_run, run_pipeline, status_run
from email_corpus_forge.providers import FixtureProvider, PHRASES, Response
from email_corpus_forge.contracts import LABELS


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "run"
        self.manifest = create_plan(self.run)

    def complete(self):
        provider = FixtureProvider()
        summary = run_pipeline(self.run, provider)
        self.assertEqual(summary["processed"], 120)
        return provider, summary

    def test_family_split_fixture_counts_and_variants(self):
        counts = {}
        for family in self.manifest["scenarios"]:
            counts[family["split"]] = counts.get(family["split"], 0) + 1
            self.assertEqual(family["variants"], list(range(5)))
        self.assertEqual(sorted(counts.values()), [4, 4, 16])
        self.assertEqual(self.manifest["dataset_kind"], "software_fixture_not_corpus")

    def test_resume_does_not_dispatch_or_modify_evidence(self):
        _, original = self.complete()
        snapshots = {p: p.read_bytes() for p in (self.run / "raw").glob("*.json")}
        resumed = FixtureProvider()
        second = run_pipeline(self.run, resumed)
        self.assertEqual(resumed.calls, [])
        self.assertEqual(second, original)
        self.assertTrue(all(p.read_bytes() == data for p, data in snapshots.items()))

    def test_timeout_retains_reservation_and_never_implicitly_retries(self):
        class TimeoutFixture(FixtureProvider):
            reservation_micro = 75
            def generate(self, packet):
                self.calls.append(("generate", packet))
                raise TimeoutError("offline uncertain-outcome fixture")
        provider = TimeoutFixture()
        first = run_pipeline(self.run, provider)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(first["budget"]["reserved_micro"], 75)
        self.assertEqual(first["processed"], 0)
        self.assertEqual(len(first["pending_attempts"]), 1)
        resumed = TimeoutFixture()
        second = run_pipeline(self.run, resumed)
        self.assertEqual(resumed.calls, [])
        self.assertEqual(second["budget"]["reserved_micro"], 75)
        self.assertEqual(second["pending_attempts"], first["pending_attempts"])

    def test_cost_cap_stops_before_provider_call(self):
        class ExpensiveFixture(FixtureProvider):
            reservation_micro = 10_000_001
        provider = ExpensiveFixture()
        summary = run_pipeline(self.run, provider)
        self.assertEqual(provider.calls, [])
        self.assertEqual(summary["processed"], 0)
        self.assertEqual(summary["budget"]["reserved_micro"], 0)

    def test_review_packets_hide_controller_metadata(self):
        provider, _ = self.complete()
        packets = [p for stage, p in provider.calls if stage == "review"]
        self.assertTrue(packets)
        for packet in packets:
            self.assertEqual(set(packet), {"record_id", "rubric", "subject", "body", "output_schema"})
            self.assertRegex(packet["record_id"], r"^[0-9a-f]{32}$")

    def test_accepted_no_match_and_held_unknown_stay_separate(self):
        self.complete()
        records = [json.loads(p.read_text()) for p in (self.run / "records").glob("*.json")]
        accepted_empty = [r for r in records if r["disposition"] == "accepted" and r["reviewed_labels"] == []]
        held_unknown = [r for r in records if any(j["decision"] == "unknown" for v in r["reviews"] for j in v["judgments"].values())]
        self.assertTrue(accepted_empty)
        self.assertTrue(held_unknown)
        self.assertTrue(all(r["disposition"] == "held" for r in held_unknown))

    def test_tampered_raw_blocks_export(self):
        self.complete()
        raw = next((self.run / "raw").glob("*.json"))
        envelope = json.loads(raw.read_text())
        envelope["response"]["text"] = "tampered evidence"
        raw.write_text(json.dumps(envelope))
        with self.assertRaises(IntegrityError):
            export_run(self.run, self.root / "export")
        self.assertFalse((self.root / "export").exists())

    def test_export_content_allowlist_join_counts_and_checksums(self):
        self.complete()
        out = self.root / "export"
        export_run(self.run, out)
        inputs = [json.loads(line) for line in (out / "inputs.jsonl").read_text().splitlines()]
        labels = [json.loads(line) for line in (out / "labels.jsonl").read_text().splitlines()]
        provenance = [json.loads(line) for line in (out / "provenance.jsonl").read_text().splitlines()]
        self.assertTrue(inputs)
        self.assertTrue(all(set(value) == {"subject", "body"} for value in inputs))
        self.assertEqual(len(inputs), len(labels))
        self.assertEqual(len(inputs), len(provenance))
        self.assertEqual([r["row"] for r in labels], list(range(len(inputs))))
        self.assertEqual([r["id"] for r in labels], [r["id"] for r in provenance])
        for relative, expected in json.loads((out / "checksums.json").read_text()).items():
            self.assertEqual(hashlib.sha256((out / relative).read_bytes()).hexdigest(), expected)
        self.assertTrue((out / "FIXTURE_ONLY.txt").exists())

    def test_export_never_replaces_existing_bundle(self):
        self.complete()
        out = self.root / "export"
        out.mkdir()
        marker = out / "existing"
        marker.write_text("preserve")
        with self.assertRaises(FileExistsError):
            export_run(self.run, out)
        self.assertEqual(marker.read_text(), "preserve")

    def test_export_interruption_removes_staging_without_partial_destination(self):
        self.complete()
        out = self.root / "export"
        with patch("email_corpus_forge.pipeline.os.rename", side_effect=OSError("offline interrupted export")):
            with self.assertRaises(OSError):
                export_run(self.run, out)
        self.assertFalse(out.exists())
        self.assertEqual(list(self.root.glob(".export-*")), [])

    def test_review_key_order_does_not_change_agreement(self):
        class ReorderedFixture(FixtureProvider):
            def generate(self, packet):
                if any(stage == "generate" for stage, _ in self.calls):
                    raise TimeoutError("stop after one record")
                self.calls.append(("generate", packet))
                self.positive = next(label for label in LABELS
                                     if [label] != packet["scenario"]["intended_labels"])
                return Response(json.dumps({"subject": "Fixture", "body": PHRASES[self.positive]}))
            def review(self, packet):
                self.calls.append(("review", packet))
                labels = LABELS if sum(stage == "review" for stage, _ in self.calls) == 1 else reversed(LABELS)
                judgments = {label: {"decision": "present" if label == self.positive else "absent",
                                    "evidence": [PHRASES[label]] if label == self.positive else [],
                                    "reason": "Fixture reason"} for label in labels}
                return Response(json.dumps({"status": "complete", "judgments": judgments}))
        provider = ReorderedFixture()
        summary = run_pipeline(self.run, provider)
        self.assertEqual(summary["processed"], 1)
        self.assertEqual(summary["counts"]["accepted"], 1)
        self.assertEqual(sum(stage == "review" for stage, _ in provider.calls), 2)
        self.assertEqual(summary["pool_counts"]["off_target"],1)

    def test_nested_enum_review_is_held_without_uncaught_type_error(self):
        class InvalidEnumFixture(FixtureProvider):
            def generate(self, packet):
                if any(stage == "generate" for stage, _ in self.calls):
                    raise TimeoutError("stop after one malformed-review record")
                return super().generate(packet)
            def review(self, packet):
                response = super().review(packet)
                malformed = json.loads(response.text)
                malformed["status"] = {"unexpected": "complete"}
                malformed["judgments"][LABELS[0]]["decision"] = ["absent"]
                return Response(json.dumps(malformed))
        summary = run_pipeline(self.run, InvalidEnumFixture())
        self.assertEqual(summary["processed"], 1)
        self.assertEqual(summary["counts"]["held"], 1)
        self.assertEqual(summary["counts"]["accepted"], 0)
        record = json.loads(next((self.run / "records").glob("*.json")).read_text())
        self.assertIn("contract failure", record["reason"])

    def test_failed_repairs_still_consume_attempt_allowance(self):
        class MalformedFixture(FixtureProvider):
            def generate(self, packet):
                self.calls.append(("generate", packet))
                return Response("{}")
            def repair(self, packet):
                self.calls.append(("repair", packet))
                return Response("{}")
        provider = MalformedFixture()
        summary = run_pipeline(self.run, provider)
        self.assertEqual(summary["processed"], 120)
        self.assertEqual(sum(stage == "repair" for stage, _ in provider.calls), 12)
        resumed = MalformedFixture()
        run_pipeline(self.run, resumed)
        self.assertEqual(resumed.calls, [])

    def test_malformed_rereviews_still_consume_attempt_allowance(self):
        class MalformedRereviewFixture(FixtureProvider):
            def review(self, packet):
                self.calls.append(("review", packet))
                count = sum(stage == "review" for stage, _ in self.calls)
                # Initial and second calls alternate until the global allowance ends.
                if count <= 24 and count % 2 == 0:
                    return Response("{}")
                judgments = {label: {"decision": "unknown", "evidence": [], "reason": "Missing context fixture"}
                             for label in LABELS}
                return Response(json.dumps({"status": "complete", "judgments": judgments}))
        provider = MalformedRereviewFixture()
        summary = run_pipeline(self.run, provider)
        self.assertEqual(summary["processed"], 120)
        self.assertLessEqual(sum(stage == "review" for stage, _ in provider.calls), 132)
        self.assertEqual(summary["rereview_count"],10)

    def test_deleted_anchored_raw_blocks_resume(self):
        self.complete()
        next((self.run / "raw").glob("*.json")).unlink()
        with self.assertRaises(IntegrityError):
            run_pipeline(self.run, FixtureProvider())

    def test_deleted_anchored_record_blocks_resume_and_export(self):
        self.complete()
        next((self.run / "records").glob("*.json")).unlink()
        with self.assertRaises(IntegrityError):
            run_pipeline(self.run, FixtureProvider())
        with self.assertRaises(IntegrityError):
            export_run(self.run, self.root / "export")


if __name__ == "__main__":
    unittest.main()
