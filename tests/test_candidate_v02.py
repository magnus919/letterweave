import json
from pathlib import Path
import tempfile
import unittest
from email_corpus_forge.assessments import review_projection, validity_assessment
from email_corpus_forge.contracts import LABELS,RUBRIC,VERSION
from email_corpus_forge.relations import evaluate_relation,mutation_applicability
from email_corpus_forge.pipeline import create_plan,run_pipeline,export_run
from email_corpus_forge.providers import FixtureProvider,Response,PHRASES
from test_planning import inventory,mutation
from test_execution_quality import review,relation_hypothesis

class CandidateTests(unittest.TestCase):
    def test_history_unknown_preserved_and_first_pass_separate(self):
        first=review([LABELS[0]]);second=review([LABELS[0]],unknown=[LABELS[1]])
        p=review_projection([first,second])
        self.assertEqual(p['first_pass_judgments'][LABELS[1]]['decision'],'absent')
        self.assertEqual(p['latest_judgments'][LABELS[1]]['decision'],'unknown')
        self.assertEqual(p['final_judgments'][LABELS[1]]['decision'],'unknown')
        self.assertEqual(p['final_labels'],[LABELS[0]])
        self.assertEqual(p['disagreement_labels'],[LABELS[1]])
        self.assertEqual(p['label_validity'],'held')

    def test_key_order_does_not_create_disagreement(self):
        a=review([LABELS[0]]);b={'status':'complete','judgments':dict(reversed(list(a['judgments'].items())))}
        self.assertEqual(review_projection([a,b])['label_validity'],'accepted')

    def test_off_target_labels_are_valid_independent_of_intent(self):
        r={'content':{'subject':'Receipt','body':PHRASES[LABELS[1]]},'reviews':[review([LABELS[1],LABELS[2]])],
           'intended_labels':[LABELS[1]],'review_resource':'unallocated_or_exhausted'}
        a=validity_assessment(r)
        self.assertEqual(a['pool'],'off_target');self.assertEqual(a['label_validity'],'accepted')
        self.assertEqual(a['scenario_adherence']['observed_extra'],[LABELS[2]])

    def test_identical_content_never_successful_even_when_labels_preserved(self):
        p={'content':{'subject':'Same','body':'unchanged facts'},'reviews':[review([LABELS[0]])]}
        relation=evaluate_relation(p,p,relation_hypothesis())
        self.assertEqual(relation['label_relation'],'pass');self.assertEqual(relation['content_change'],'no_op')
        self.assertEqual(relation['result'],'fail');self.assertFalse(relation['local_checks_pass'])

    def test_lost_declared_fact_excludes_otherwise_successful_label_flip(self):
        m=relation_hypothesis(add=[LABELS[4]]);m['preserve_facts']=['Total 51.84']
        p={'content':{'subject':'Receipt','body':'Total 51.84'},'reviews':[review([LABELS[1]])]}
        c={'content':{'subject':'Receipt and offer','body':'Total 58.14 and sale'},'reviews':[review([LABELS[1],LABELS[4]])]}
        r=evaluate_relation(p,c,m)
        self.assertEqual(r['label_relation'],'pass');self.assertEqual(r['fact_preservation']['status'],'fail')
        self.assertEqual(r['result'],'fail')
        c['content']['body']='Total 51.84 and sale';r=evaluate_relation(p,c,m)
        self.assertEqual(r['result'],'pass');self.assertFalse(r['fact_preservation']['semantic_fact_preservation_established'])

    def test_no_fact_evidence_remains_indeterminate(self):
        p={'content':{'subject':'Receipt','body':'paid'},'reviews':[review([LABELS[1]])]}
        c={'content':{'subject':'Receipt','body':'paid and sale'},'reviews':[review([LABELS[1],LABELS[4]])]}
        r=evaluate_relation(p,c,relation_hypothesis(add=[LABELS[4]]))
        self.assertEqual(r['label_relation'],'pass');self.assertEqual(r['result'],'indeterminate')

    def test_inapplicable_baseline_skips_variant_without_paid_stage(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);p=inventory(1);p['families'][0].update(case='single',intended_labels=[LABELS[4]],mutations=[relation_hypothesis(add=[LABELS[4]])])
            source=root/'source.json';source.write_text(json.dumps(p));run=root/'run'
            create_plan(run,scenario_plan=source,variants_per_family=2,max_repairs=0,max_rereviews=0)
            provider=FixtureProvider();s=run_pipeline(run,provider)
            self.assertFalse(any(stage=='mutate' for stage,_ in provider.calls));self.assertEqual(s['processed'],2)
            child=json.loads((run/'records/s00000-v1.json').read_text())
            self.assertTrue(child['generation_skipped']);self.assertEqual(child['mutation_applicability']['status'],'inapplicable')
            self.assertEqual(s['diagnostics']['technical_contract_failure'],0)

    def test_frozen_allocation_validation_and_no_intent_hold(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);p=inventory(1);p['rereview_allocation']=[]
            source=root/'source.json';source.write_text(json.dumps(p));run=root/'run'
            create_plan(run,scenario_plan=source,variants_per_family=1,max_rereviews=1,max_repairs=0)
            class OffTarget(FixtureProvider):
                def generate(self,packet):
                    self.calls.append(('generate',packet));return Response(json.dumps({'subject':'Receipt','body':PHRASES[LABELS[1]]}))
            provider=OffTarget();s=run_pipeline(run,provider)
            self.assertEqual(s['counts']['accepted'],1);self.assertEqual(s['pool_counts']['off_target'],1)
            self.assertEqual(s['rereview_count'],0)
            export_run(run,root/'export');label=json.loads((root/'export/labels.jsonl').read_text())
            self.assertEqual(label['pool'],'off_target');self.assertEqual(label['judgments'][LABELS[1]]['decision'],'present')
            p['rereview_allocation']=['not-a-planned-id'];source.write_text(json.dumps(p))
            with self.assertRaises(ValueError):create_plan(root/'bad',scenario_plan=source,variants_per_family=1,max_rereviews=1)

    def test_missing_fact_anchor_blocks_variant_before_dispatch(self):
        m=relation_hypothesis(add=[LABELS[4]]);m['preserve_facts']=['Total 51.84']
        p={'content':{'subject':'Receipt','body':'Missing amount'},'reviews':[review([LABELS[1]])]}
        self.assertEqual(mutation_applicability(p,m)['status'],'indeterminate')

    def test_generation_instruction_avoids_reader_fiction_announcements(self):
        from email_corpus_forge.provider_adapter import ContractProviderAdapter
        a=ContractProviderAdapter('test',input_rate_micro_per_million=1,output_rate_micro_per_million=1,max_input_tokens=1000,max_output_tokens=1000)
        req=a.build_request('generate',{'content_schema_version':VERSION,'variant':0,'scenario':{'context':'Invented names','purpose':'Receipt','topic':'Pottery','writing_style':'English','mutations':[{'future':'remove pitch'}]}})
        self.assertIn('Do not announce fiction',req['instructions'])
        self.assertNotIn('mutations',req['input']['scenario'])

    def test_rubric_decisions_are_explicit_versioned(self):
        self.assertEqual(VERSION,'0.5.0')
        text=json.dumps(RUBRIC)
        self.assertIn('completed-payment',text);self.assertIn('ordinary community discussion',text)
        self.assertIn('Do not invent hypothetical hidden purposes',text)

if __name__=='__main__':unittest.main()
