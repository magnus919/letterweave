"""Offline actual-wire byte envelope tests; no account or inference access."""
import json
import re
import unittest
from email_corpus_forge.contracts import blind_packet, canonical, digest
from email_corpus_forge.nous_chat import NousChatProvider, SDKNousChatTransport
from email_corpus_forge.openai_responses import PrivatePilotAuthorization, supported_schema
from test_openai_responses import OfflineTransport
from test_nous_chat import chat


class CountingTransport(OfflineTransport):
    def count(self, request):
        self.count_calls.append(request)
        return SDKNousChatTransport.count(None, request)


class RequestFeasibilityTests(unittest.TestCase):
    def provider(self):
        transport = CountingTransport([])
        auth = PrivatePilotAuthorization(digest({}), 'offline-only', 10000000, True, True, True)
        return NousChatProvider(transport, authorization=auth), transport

    def test_maximum_escaping_content_review_and_rereview_fit_frozen_ceiling(self):
        provider, _ = self.provider()
        for char in ('"', '\\', '\t', '\n', '\r'):
            for stage in ('review', 'rereview'):
                with self.subTest(char=repr(char), stage=stage):
                    packet = blind_packet({'subject': '"' * 160, 'body': 'x' + char * 2199})
                    wire = provider.build_request(stage, packet)
                    self.assertLessEqual(SDKNousChatTransport.count(None, wire), 12000)
                    user = json.loads(wire['messages'][1]['content'])
                    self.assertNotIn('output_schema', user)
                    self.assertEqual(user['body'], packet['body'])
        self.assertEqual(provider.max_input_tokens, 12000)
        self.assertEqual(provider.reservation_micro, 114000)

    def test_generation_schema_bounds_and_ascii_patterns_survive_projection(self):
        provider, _ = self.provider()
        packet = {'scenario': {'context': 'Example', 'purpose': 'Example', 'topic': 'Example',
                               'writing_style': 'Brief'}, 'variant': 0, 'content_schema_version': '0.3.0'}
        wire = provider.build_request('generate', packet)
        schema = wire['response_format']['json_schema']['schema']
        for field, ceiling in (('subject', 160), ('body', 2200)):
            self.assertIn('pattern', schema['properties'][field])
            pattern = schema['properties'][field]['pattern']
            self.assertIsNotNone(re.fullmatch(pattern, 'x' * ceiling))
            self.assertIsNone(re.fullmatch(pattern, 'x' * (ceiling + 1)))
            self.assertEqual(supported_schema(schema)['properties'][field]['pattern'], schema['properties'][field]['pattern'])

    def test_utf8_content_metadata_and_framing_are_all_counted(self):
        request = {'messages': [{'role': 'user', 'content': 'Appointment — mañana'}],
                   'model': 'example', 'response_format': {'type': 'json_schema', 'schema': {'title': 'é'}}}
        metadata = {k: v for k, v in request.items() if k != 'messages'}
        expected = len(request['messages'][0]['content'].encode('utf-8')) + len(b'user') + len(canonical(metadata)) + 1024
        self.assertEqual(SDKNousChatTransport.count(None, request), expected)
        self.assertGreater(expected, len(request['messages'][0]['content']) + 1024)

    def test_saved_unicode_appointment_is_reviewed_without_generation_ascii_rule(self):
        provider, _ = self.provider()
        wire = provider.build_request('review', blind_packet({'subject': 'Appointment — café', 'body': 'Confirm tomorrow.'}))
        self.assertIn('café', wire['messages'][1]['content'])
        self.assertLessEqual(SDKNousChatTransport.count(None, wire), 12000)

    def test_overbound_input_rejected_before_dispatch(self):
        provider, transport = self.provider()
        packet = blind_packet({'subject': 'Review', 'body': '"' * 12000})
        with self.assertRaises(ValueError):
            provider.prepare('review', packet)
        self.assertEqual(transport.create_calls, [])
        self.assertEqual(provider.reservation_micro, 114000)
        self.assertEqual(provider.max_input_tokens, 12000)

    def test_noncompliant_generation_output_is_terminal_error(self):
        provider, _ = self.provider()
        for content in ({'subject': 'x' * 161, 'body': 'Hello'},
                        {'subject': 'Hello', 'body': 'x' * 2201},
                        {'subject': 'Café', 'body': 'Hello'},
                        {'subject': 'Hello', 'body': 'bad\x01control'}):
            with self.subTest(content=content):
                response = provider.normalize_response(chat(json.dumps(content)))
                self.assertEqual(response.outcome, 'error')


if __name__ == '__main__':
    unittest.main()
