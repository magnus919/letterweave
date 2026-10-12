import importlib.util,json,unittest
from pathlib import Path
from email_corpus_forge.contracts import blind_packet
from email_corpus_forge.nous_chat import NousChatProvider
from email_corpus_forge.nous_roles import RoleRoutedNousProvider
from email_corpus_forge.realism import BOUNDARY_POLICY_V2
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('contrast_plan',ROOT/'tools/build_contrast_plan.py');builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
class RealismV2Tests(unittest.TestCase):
 def test_v2_policy_on_generation_and_blind_review_while_v1_unchanged(self):
  packet={'scenario':{'context':'invented notice','purpose':'notify','writing_style':'plain','topic':'operations','intended_labels':['alerts/updates']}}
  old=NousChatProvider(None,content_profile='mail-realism-v1').build_request('generate',packet)
  provider=RoleRoutedNousProvider(None,content_profile='mail-realism-v2',max_input_tokens=24000)
  gen=provider.build_request('generate',packet);review=provider.build_request('review',blind_packet({'subject':'Your notes','body':'Available online'}))
  self.assertNotIn(BOUNDARY_POLICY_V2,old['messages'][0]['content'])
  self.assertIn(BOUNDARY_POLICY_V2,gen['messages'][0]['content']);self.assertIn(BOUNDARY_POLICY_V2,review['messages'][0]['content'])
  self.assertNotIn('intended_labels',gen['messages'][1]['content']);self.assertNotIn('intended_labels',review['messages'][1]['content'])
  self.assertEqual(set(json.loads(review['messages'][1]['content'])),{'record_id','rubric','subject','body'})
  self.assertTrue(all(p.settings()['content_profile']=='mail-realism-v2' for p in provider._children.values()))
 def test_v2_accepts_long_generated_response_and_rejects_control(self):
  provider=NousChatProvider(None,content_profile='mail-realism-v2',max_input_tokens=24000)
  content={'subject':'Notes ready','body':'Long readable content. '*900}
  raw={'id':'fixture','model':'openai/gpt-6.1-sol','choices':[{'finish_reason':'stop','message':{'role':'assistant','content':json.dumps(content)}}],'usage':{'prompt_tokens':100,'completion_tokens':100,'total_tokens':200,'completion_tokens_details':{'reasoning_tokens':0}}}
  self.assertEqual(provider.normalize_response(raw).outcome,'content')
  content['body']='bad\x00text';raw['choices'][0]['message']['content']=json.dumps(content);self.assertEqual(provider.normalize_response(raw).outcome,'error')
  with self.assertRaises(ValueError):NousChatProvider(None,content_profile='mail-realism-v2',max_input_tokens=24001)
 def test_archived_inventory_and_exact_group_split_overrides(self):
  plan,groups=builder.inventory();archived=json.loads((ROOT/'scenario-plans/contrasts-0.3.0.json').read_text());self.assertEqual(plan,archived);self.assertEqual(len(groups),160);self.assertEqual(len(set(groups.values())),30)
  assigned=builder.split_groups(groups);self.assertEqual(assigned,builder.split_groups(groups));self.assertEqual(sum(x=='test_planned' for x in assigned.values()),6)
  data=ROOT/'datasets/letterweave-0.3.0/provenance.jsonl'
  if data.exists():
   seen={}
   for row in map(json.loads,data.read_text().splitlines()):
    if row['family_id'] in groups:
     group=groups[row['family_id']];self.assertEqual(row['split'],assigned[group]);self.assertEqual(seen.setdefault(group,row['split']),row['split'])
if __name__=='__main__':unittest.main()
