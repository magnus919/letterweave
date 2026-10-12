import unittest
from email_corpus_forge.nous_chat import NousChatProvider
from email_corpus_forge.nous_roles import RoleRoutedNousProvider
from email_corpus_forge.realism import profile_valid
from email_corpus_forge.contracts import blind_packet
class RealismTests(unittest.TestCase):
 def test_long_unicode_subject_only_and_controls(self):
  self.assertTrue(profile_valid({"subject":"📅 Report available","body":""}))
  self.assertTrue(profile_valid({"subject":"Updates","body":"a"*6500}))
  self.assertTrue(profile_valid({"subject":"Updates","body":"a"*18000}))
  self.assertFalse(profile_valid({"subject":"Updates","body":"bad\x00text"}))
  self.assertFalse(profile_valid({"subject":"", "body":""}))
 def test_default_and_opt_in_wire_contract(self):
  packet={"scenario":{"context":"new notice","purpose":"notify","writing_style":"long","topic":"systems"}}
  old=NousChatProvider(None).build_request("generate",packet)
  new=NousChatProvider(None,content_profile="mail-realism-v1",max_input_tokens=24000).build_request("generate",packet)
  self.assertIn("<=2200",old["messages"][0]["content"])
  self.assertNotIn("<=2200",new["messages"][0]["content"])
  self.assertIn("completion-token budget",new["messages"][0]["content"])
  self.assertNotIn("maxLength",new["response_format"]["json_schema"]["schema"]["properties"]["body"]) # provider-compatible schema omits unsupported keywords; local validator enforces limits
 def test_review_not_intent_and_role_propagation(self):
  p=RoleRoutedNousProvider(None,content_profile="mail-realism-v1",max_input_tokens=24000)
  req=p.build_request("review",blind_packet({"subject":"Report","body":""}))
  self.assertIn("past meeting recap",req["messages"][0]["content"])
  self.assertNotIn("intended_labels",req["messages"][1]["content"])
  self.assertTrue(all(x.settings()["content_profile"]=="mail-realism-v1" for x in p._children.values()))
 def test_profile_rejects_unknown_or_unbounded(self):
  with self.assertRaises(ValueError):NousChatProvider(None,content_profile="bogus")
  with self.assertRaises(ValueError):NousChatProvider(None,max_input_tokens=24000)
  with self.assertRaises(ValueError):NousChatProvider(None,content_profile="mail-realism-v1",max_input_tokens=24001)
if __name__=="__main__":unittest.main()
