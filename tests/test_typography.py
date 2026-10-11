"""Offline punctuation preservation regressions; no output rewriting."""
import json
import unittest
from email_corpus_forge.typography import profile_valid, broken_apostrophe_fragments
from email_corpus_forge.relations import fact_preservation
import test_nous_chat
from test_nous_chat import chat


class TypographyTests(unittest.TestCase):
    def content(self, body):
        return {'subject': 'Appointment', 'body': body}

    def test_curly_and_straight_typography_is_preserved(self):
        for text in ("Mara's appointment isn't cancelled — I'll attend…",
                     'Mara’s appointment isn’t cancelled – “I’ll attend.” The dogs’ bowls are ready.'):
            content = self.content(text)
            self.assertTrue(profile_valid(content))
            provider, _ = test_nous_chat.NousTests().provider([])
            raw = chat(json.dumps(content, ensure_ascii=False))
            response = provider.normalize_response(raw)
            self.assertEqual(response.outcome, 'content')
            self.assertEqual(json.loads(response.text), content)
            self.assertEqual(response.raw_response, raw)

    def test_newline_split_contractions_are_errors_not_rewritten(self):
        provider, _ = test_nous_chat.NousTests().provider([])
        for text in ('I\nm ready.', 'It isn\nt cancelled.', 'We\nre attending.', "I'\nm ready.", 'I\n’m ready.'):
            content = self.content(text)
            self.assertFalse(profile_valid(content))
            response = provider.normalize_response(chat(json.dumps(content)))
            self.assertEqual(response.outcome, 'error')
            self.assertEqual(json.loads(response.text), content)

    def test_parent_possessive_newline_corruption_keeps_raw_usage(self):
        parent = self.content('Mara’s appointment is confirmed.')
        child = self.content('Mara\ns appointment is confirmed.')
        self.assertTrue(broken_apostrophe_fragments(child, parent))
        provider, transport = test_nous_chat.NousTests().provider([chat(json.dumps(child))])
        packet = {'parent_content': parent, 'operation': {'operator': 'formatting-preserve'},
                  'content_schema_version': '0.3.2'}
        provider.prepare('mutate', packet)
        response = provider.mutate(packet)
        self.assertEqual(response.outcome, 'error')
        self.assertEqual(json.loads(response.text), child)
        self.assertEqual(response.input_tokens, 100)
        self.assertEqual(response.output_tokens, 200)
        self.assertEqual(response.raw_response['choices'][0]['message']['content'], json.dumps(child))
        self.assertEqual(len(transport.create_calls), 1)

    def test_case_whitespace_equivalence_never_erases_punctuation_or_meaning(self):
        parent = {'content': self.content('Mara’s total 51.84. Do not repay!')}
        hypothesis = {'operator': 'formatting-preserve', 'relation': 'preserve', 'preserve_facts': ['total 51.84.']}
        equivalent = {'content': self.content('MARA’S  TOTAL 51.84.\nDo not repay!')}
        self.assertEqual(fact_preservation(parent, equivalent, hypothesis)['status'], 'pass')
        for text in ('Mara\ns total 51.84. Do not repay!',
                     "Mara's total 51.84. Do not repay!",
                     'Mara’s total 58.14. Do not repay!',
                     'Mara’s total 51.84. Do repay!',
                     'Mara’s total 51.84. Do not repay?'):
            self.assertNotEqual(fact_preservation(parent, {'content': self.content(text)}, hypothesis)['status'], 'pass')

    def test_utf8_byte_limits_and_emoji_rejection(self):
        self.assertTrue(profile_valid({'subject': '’' * 53, 'body': 'x'}))
        self.assertFalse(profile_valid({'subject': '’' * 54, 'body': 'x'}))
        self.assertTrue(profile_valid(self.content('’' * 733)))
        self.assertFalse(profile_valid(self.content('’' * 734)))
        self.assertFalse(profile_valid(self.content('Confirmed 😀')))
        self.assertTrue(profile_valid(self.content('I\nmet Nora yesterday.')))
        self.assertTrue(profile_valid(self.content("The dogs'\nbowls are ready.")))


if __name__ == '__main__':
    unittest.main()
