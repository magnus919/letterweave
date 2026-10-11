import json
import unittest
from importlib.resources import files
from email_corpus_forge.contracts import CONTENT_SCHEMA, REVIEW_SCHEMA, RUBRIC, LABELS, VERSION
from email_corpus_forge.providers import PHRASES


class ResourceTests(unittest.TestCase):
    def resource(self, name):
        return json.loads(files("email_corpus_forge").joinpath("data", name).read_text())

    def test_packaged_contracts_match_runtime_contracts(self):
        self.assertEqual(self.resource("content.schema.json"), CONTENT_SCHEMA)
        self.assertEqual(self.resource("review.schema.json"), REVIEW_SCHEMA)
        self.assertEqual(self.resource("taxonomy.json"), {"version": VERSION, "labels": list(LABELS), "rubric": RUBRIC})

    def test_packaged_fixture_is_explicit_and_complete(self):
        fixture = self.resource("fixture-phrases.json")
        self.assertEqual(fixture["kind"], "software_fixture_not_corpus")
        self.assertEqual(fixture["version"], VERSION)
        self.assertEqual(fixture["phrases"], PHRASES)
        self.assertEqual(set(PHRASES), set(LABELS))
