"""Budget safety specifications exercised with local temporary state only."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from email_corpus_forge.ledger import IntegrityError, Ledger, write_once


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_cap_refuses_request_without_changing_balance(self):
        ledger = Ledger(self.root, cap_micro=100)
        self.assertTrue(ledger.reserve("first", 70))
        before = ledger.balance()
        self.assertFalse(ledger.reserve("second", 31))
        self.assertEqual(ledger.balance(), before)
        self.assertTrue(ledger.reserve("third", 30))
        self.assertEqual(ledger.balance()["reserved_micro"], 100)

    def test_confirmed_usage_reconciles_reservation(self):
        ledger = Ledger(self.root, cap_micro=100)
        ledger.reserve("first", 70)
        ledger.settle("first", 40)
        self.assertEqual(ledger.balance(), {"spent_micro": 40, "reserved_micro": 0, "cap_micro": 100})
        self.assertTrue(ledger.reserve("second", 60))
        self.assertFalse(ledger.reserve("third", 1))

    def test_unsettled_reservation_survives_restart(self):
        ledger = Ledger(self.root, cap_micro=100)
        ledger.reserve("uncertain", 70)
        resumed = Ledger(self.root, cap_micro=100)
        self.assertEqual(resumed.balance()["reserved_micro"], 70)
        self.assertFalse(resumed.reserve("retry-with-new-id", 31))
        self.assertEqual(resumed.balance()["spent_micro"], 0)

    def test_repeated_reservation_cannot_double_count(self):
        ledger = Ledger(self.root, cap_micro=100)
        ledger.reserve("same", 70)
        ledger.reserve("same", 70)
        self.assertEqual(ledger.balance()["reserved_micro"], 70)

    def test_second_ledger_observes_previous_reservation(self):
        first = Ledger(self.root, cap_micro=100)
        second = Ledger(self.root, cap_micro=100)
        first.reserve("first", 70)
        self.assertFalse(second.reserve("second", 40))
        self.assertEqual(second.balance()["reserved_micro"], 70)

    def test_uncertain_event_does_not_release_reservation(self):
        ledger = Ledger(self.root, cap_micro=100)
        ledger.reserve("uncertain", 90)
        ledger.append("uncertain", attempt_id="uncertain")
        self.assertEqual(Ledger(self.root, cap_micro=100).balance()["reserved_micro"], 90)

    def test_changed_usage_or_reservation_fails_closed(self):
        ledger = Ledger(self.root, cap_micro=100)
        ledger.reserve("first", 70)
        for action in (lambda: ledger.reserve("first", 60),
                       lambda: ledger.settle("first", 71),
                       lambda: ledger.settle("missing", 1)):
            with self.assertRaises(IntegrityError):
                action()
        self.assertEqual(ledger.balance()["reserved_micro"], 70)

    def test_already_settled_usage_cannot_be_changed(self):
        ledger = Ledger(self.root, cap_micro=100)
        ledger.reserve("first", 70)
        ledger.settle("first", 40)
        ledger.settle("first", 40)
        with self.assertRaises(IntegrityError):
            ledger.settle("first", 30)
        self.assertEqual(ledger.balance()["spent_micro"], 40)

    def test_partial_ledger_tail_is_rejected(self):
        ledger = Ledger(self.root, cap_micro=100)
        ledger.reserve("first", 70)
        path = self.root / "ledger.jsonl"
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaises(IntegrityError):
            Ledger(self.root, cap_micro=100).balance()

    def test_raw_write_is_immutable(self):
        path = self.root / "raw" / "attempt.json"
        write_once(path, {"text": "first evidence"})
        original = path.read_bytes()
        with self.assertRaises(FileExistsError):
            write_once(path, {"text": "replacement"})
        self.assertEqual(path.read_bytes(), original)

    def test_interrupted_raw_publication_leaves_no_partial_artifact(self):
        path = self.root / "raw" / "attempt.json"
        with patch("email_corpus_forge.ledger.os.link", side_effect=OSError("fixture interruption")):
            with self.assertRaises(OSError):
                write_once(path, {"text": "evidence"})
        self.assertFalse(path.exists())
        self.assertEqual(list(path.parent.iterdir()), [])

    def test_negative_bool_and_fractional_budget_inputs_fail(self):
        ledger = Ledger(self.root, cap_micro=100)
        for amount in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                ledger.reserve("invalid", amount)
        self.assertEqual(ledger.balance()["reserved_micro"], 0)


if __name__ == "__main__":
    unittest.main()
