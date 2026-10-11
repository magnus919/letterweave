"""Public explicit cap authorization tests; no private controller imports."""
import unittest

from email_corpus_forge.contracts import digest
from email_corpus_forge.openai_responses import PrivatePilotAuthorization
from email_corpus_forge.provider_adapter import DispatchNotAuthorized


class AuthorizationTests(unittest.TestCase):
    def auth(self,cap=25000000,approved=25000000,manifest=None):
        return PrivatePilotAuthorization(digest(manifest or {}),'offline explicit budget',cap,True,True,True,approved_cap_micro=approved)

    def test_explicit_twentyfive_dollar_manifest_binding_passes(self):
        manifest={'cap_micro':25000000,'mode':'test'}
        self.auth(manifest=manifest).check(manifest)

    def test_default_approval_still_rejects_twentyfive_dollars(self):
        value=PrivatePilotAuthorization(digest({}),'offline',25000000,True,True,True)
        with self.assertRaises(DispatchNotAuthorized):value.check()

    def test_invalid_types_zero_oversize_or_lower_approval_rejected(self):
        for cap,approved in ((True,25000000),(25000000,True),(25000000,25.0),
                             (0,25000000),(25000000,24000000),(30000001,30000001)):
            with self.subTest(cap=cap,approved=approved),self.assertRaises(DispatchNotAuthorized):
                self.auth(cap,approved).check()

    def test_hash_binding_does_not_override_lower_manifest_ceiling(self):
        manifest={'cap_micro':25000000}
        with self.assertRaises(DispatchNotAuthorized):self.auth(cap=24000000,manifest=manifest).check(manifest)
        with self.assertRaises(DispatchNotAuthorized):self.auth(manifest=manifest).check({'cap_micro':25000000,'changed':True})




if __name__=='__main__':unittest.main()
