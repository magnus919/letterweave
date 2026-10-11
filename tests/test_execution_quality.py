"""Behavioral fixtures verify orchestration, not the quality of a model-generated corpus."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from email_corpus_forge.contracts import LABELS, blind_packet
from email_corpus_forge.duplicates import near_duplicates, validate_settings
from email_corpus_forge.ledger import Ledger, IntegrityError
from email_corpus_forge.pipeline import create_plan, run_pipeline, status_run, export_run, LiveProviderBlocked
import email_corpus_forge.pipeline as pipeline
from email_corpus_forge.providers import FixtureProvider, PHRASES
from email_corpus_forge.relations import evaluate_relation
from email_corpus_forge.provider_adapter import ContractProviderAdapter, DispatchNotAuthorized
from test_planning import inventory, mutation


def review(labels=(), unknown=()):
    return {'status': 'complete', 'judgments': {l: {'decision': 'unknown' if l in unknown else 'present' if l in labels else 'absent',
            'evidence': [PHRASES[l]] if l in labels else [], 'reason': 'Mechanical oracle'} for l in LABELS}}


def relation_hypothesis(add=(), remove=(), uncertain=()):
    m = mutation()
    m.update(operator='receipt-plus-substantive-offer', relation='uncertainty' if uncertain else 'change' if add or remove else 'preserve',
             add_labels=list(add), remove_labels=list(remove), uncertain_labels=list(uncertain),
             invariant_labels=[l for l in LABELS if l not in set(add) | set(remove) | set(uncertain)])
    return m


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.run = self.root / 'run'

    def plan(self, p, **kwargs):
        source = self.root / 'plan.json'; source.write_text(json.dumps(p))
        return create_plan(self.run, scenario_plan=source, max_repairs=0, max_rereviews=0, **kwargs)

    def test_add_remove_preserve_uncertainty_and_collateral_effects(self):
        parent = {'reviews': [review([LABELS[1]])]}
        child = {'reviews': [review([LABELS[1], LABELS[4]])]}
        m = relation_hypothesis(add=[LABELS[4]])
        self.assertEqual(evaluate_relation(parent, child, m)['label_relation'], 'pass')
        self.assertEqual(evaluate_relation(child, parent, relation_hypothesis(remove=[LABELS[4]]))['label_relation'], 'pass')
        self.assertEqual(evaluate_relation(parent, parent, relation_hypothesis())['label_relation'], 'pass')
        self.assertEqual(evaluate_relation(parent, child, relation_hypothesis())['label_relation'], 'fail')
        child['reviews'] = [review([LABELS[4]])]  # Collateral loss of the retained transaction.
        result = evaluate_relation(parent, child, m)
        self.assertEqual(result['label_relation'], 'fail'); self.assertEqual(result['per_label'][LABELS[1]], 'fail')
        child['reviews'] = [review(unknown=[LABELS[1]])]
        self.assertEqual(evaluate_relation(parent, child, relation_hypothesis(uncertain=[LABELS[1]]))['label_relation'], 'pass')
        self.assertEqual(evaluate_relation(parent, child, relation_hypothesis())['label_relation'], 'indeterminate')
        child['reviews'].append(review())
        self.assertEqual(evaluate_relation(parent, child, relation_hypothesis())['label_relation'], 'indeterminate')

    def test_mutation_request_parent_and_blind_review_and_resume(self):
        p = inventory(1); p['families'][0]['intended_labels'] = [LABELS[1]]
        m=relation_hypothesis(add=[LABELS[4]]);m['preserve_facts']=[PHRASES[LABELS[1]]]
        p['families'][0]['mutations'] = [m]
        self.plan(p, variants_per_family=2)
        provider = FixtureProvider(); report = run_pipeline(self.run, provider)
        self.assertEqual(report['relation_counts'], {'pass': 1, 'fail': 0, 'indeterminate': 0})
        self.assertEqual(report['counts']['accepted'], 2)
        stages = [s for s, _ in provider.calls]
        self.assertEqual(stages, ['generate', 'review', 'mutate', 'review'])
        mutation_packet = next(p for s, p in provider.calls if s == 'mutate')
        parent = json.loads((self.run / 'records' / 's00000-v0.json').read_text())
        self.assertEqual(mutation_packet['parent_content'], parent['content'])
        self.assertNotIn('add_labels', mutation_packet['operation'])
        ids = []
        for stage, packet in provider.calls:
            if stage == 'review':
                self.assertEqual(set(packet), {'record_id','rubric','subject','body','output_schema'})
                ids.append(packet['record_id'])
        self.assertEqual(len(set(ids)), 2)
        raw_before = {str(p): p.read_bytes() for p in (self.run / 'raw').glob('*.json')}
        resumed = FixtureProvider(); self.assertEqual(run_pipeline(self.run, resumed), report)
        self.assertEqual(resumed.calls, [])
        self.assertTrue(all(Path(p).read_bytes() == v for p, v in raw_before.items()))
        export_run(self.run, self.root / 'export')
        relation = json.loads((self.root / 'export' / 'relations.jsonl').read_text())
        self.assertEqual(relation['result'], 'pass')

    def test_failed_relation_excludes_controlled_descendants_without_label_repair(self):
        p = inventory(1); p['families'][0]['intended_labels'] = [LABELS[1]]
        first = relation_hypothesis()  # Applying upsell violates preserve hypothesis.
        second = mutation(); second.update(variant=2, parent_variant=1)
        p['families'][0]['mutations'] = [first, second]
        self.plan(p, variants_per_family=3)
        provider = FixtureProvider(); report = run_pipeline(self.run, provider)
        self.assertEqual(report['relation_counts']['fail'], 1)
        self.assertEqual(report['counts'], {'accepted': 3, 'held': 0, 'rejected': 0})
        self.assertEqual(report['controlled_transition_count'],0)
        self.assertFalse(any(s == 'repair' for s, _ in provider.calls))
        saved = json.loads((self.run / 'records' / 's00000-v1.json').read_text())
        self.assertEqual(saved['disposition'], 'accepted')  # Immutable review disposition preserved separately.
        export_run(self.run, self.root / 'export')
        diagnostics = [json.loads(l) for l in (self.root / 'export' / 'diagnostics.jsonl').read_text().splitlines()]
        self.assertEqual(len(diagnostics), 0)
        pools=[json.loads(l) for l in (self.root/'export'/'pools.jsonl').read_text().splitlines()]
        self.assertFalse(any(r['controlled_transition_included'] for r in pools))

    def test_missing_relation_evidence_blocks_resume_before_calls(self):
        p = inventory(1); p['families'][0]['mutations'] = [mutation()]
        self.plan(p, variants_per_family=2); run_pipeline(self.run)
        (self.run / 'relations' / 's00000-v1.json').unlink()
        provider = FixtureProvider()
        with self.assertRaises(IntegrityError): run_pipeline(self.run, provider)
        self.assertEqual(provider.calls, [])

    def test_duplicate_cross_family_clusters_and_same_family_exemption(self):
        text = 'alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau upsilon phi chi psi omega'
        rows = [{'id':'a0','family_id':'a','split':'train','disposition':'accepted','content':{'subject':'Fixture', 'body':text}},
                {'id':'b0','family_id':'b','split':'test','disposition':'accepted','content':{'subject':'Fixture', 'body':text+' extra'}},
                {'id':'b1','family_id':'b','split':'test','disposition':'accepted','content':{'subject':'Other', 'body':'unrelated short'}}]
        result = near_duplicates(rows, validate_settings({'enabled':True}))
        self.assertEqual(result['quarantine_ids'], ['a0','b0','b1'])
        self.assertTrue(result['edges'][0]['cross_split'])
        same = copy.deepcopy(rows[:2]); same[1]['family_id']='a'
        self.assertEqual(near_duplicates(same, validate_settings({'enabled':True}))['quarantine_ids'], [])
        unrelated = copy.deepcopy(rows[:2]); unrelated[1]['content']['body']='different unrelated words '*10
        self.assertEqual(near_duplicates(unrelated, validate_settings({'enabled':True}))['edges'], [])

    def test_cross_family_duplicate_quarantine_reaches_export(self):
        p=inventory(2)
        for family in p['families']:
            family['intended_labels']=[LABELS[0]]
        p['near_duplicates']={'enabled':True}
        self.plan(p,variants_per_family=1)
        class Copies(FixtureProvider):
            def generate(self,packet):
                response=super().generate(packet)
                from email_corpus_forge.providers import Response
                content=json.loads(response.text)
                content['subject']='Identical fixture'
                content['body']+='\nalpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau upsilon'
                return Response(json.dumps(content))
        report=run_pipeline(self.run,Copies())
        self.assertEqual(report['counts'],{'accepted':0,'held':1,'rejected':1})
        self.assertEqual(len(report['near_duplicates']['quarantine_families']),2)
        export_run(self.run,self.root/'export')
        self.assertEqual((self.root/'export'/'inputs.jsonl').read_text(),'')
        self.assertEqual(len((self.root/'export'/'diagnostics.jsonl').read_text().splitlines()),2)

    def test_mutation_tokens_replace_generation_and_require_explicit_profile(self):
        p=inventory(1);p['families'][0]['mutations']=[mutation()]
        tokens={'input_tokens':1,'visible_output_tokens':2,'reasoning_tokens':3}
        profile={stage:dict(tokens) for stage in ('generate','review','repair','repair_review','rereview')}
        p['token_budget']={'case_profiles':{'single':profile}}
        with self.assertRaises(ValueError):self.plan(p,variants_per_family=2)
        profile['mutate']={'input_tokens':100,'visible_output_tokens':200,'reasoning_tokens':300}
        plan=self.plan(p,variants_per_family=2)
        self.assertEqual(plan['budget_estimate']['totals'],{'input_tokens':103,'visible_output_tokens':206,'reasoning_tokens':309})

    def test_bounded_search_overflow_and_token_truncation_quarantine(self):
        rows = [{'id':str(i),'family_id':str(i),'split':'train','disposition':'accepted',
                 'content':{'subject':'Fixture','body':' '.join('word'+str(n) for n in range(30))}} for i in range(8)]
        settings = validate_settings({'enabled':True,'bucket_limit':2,'candidate_limit':1,'max_tokens':20})
        r = near_duplicates(rows,settings)
        self.assertLessEqual(r['comparisons'], len(rows))
        self.assertTrue(r['coverage_limited_ids'])
        self.assertEqual(len(r['quarantine_ids']),8)
        self.assertLessEqual(r['indexed_shingles'],settings['max_index_shingles'])

    def test_cached_append_detaches_nested_caller_data(self):
        ledger=Ledger(self.run); data={'value':'original'}
        ledger.append('audit_note', metadata=data); data['value']='changed'
        self.assertEqual(ledger.events(), Ledger(self.run).events())
        self.assertEqual(ledger.events()[0]['data']['metadata']['value'],'original')

    def test_normalized_exact_short_records_quarantine_cross_family(self):
        rows=[{'id':'a','family_id':'a','split':'train','disposition':'accepted','content':{'subject':'HI','body':'Meet Tuesday?'}},
              {'id':'b','family_id':'b','split':'test','disposition':'accepted','content':{'subject':'hi','body':'meet Tuesday !'}}]
        report=near_duplicates(rows,validate_settings({'enabled':True}))
        self.assertEqual(report['quarantine_ids'],['a','b'])
        self.assertEqual(report['edges'][0]['match'],'normalized_exact')

    def test_external_ledger_change_invalidates_cache_and_returned_events_detached(self):
        ledger=Ledger(self.run); ledger.reserve('a',10)
        detached=ledger.events(); detached[0]['data']['amount_micro']=500
        self.assertEqual(ledger.balance()['reserved_micro'],10)
        other=Ledger(self.run); other.reserve('b',20)
        self.assertEqual(ledger.balance()['reserved_micro'],30)
        data=ledger.path.read_text().replace('"amount_micro":10','"amount_micro":11')
        ledger.path.write_text(data)
        with self.assertRaises(IntegrityError): ledger.balance()

    def test_two_thousand_execution_crash_resume_no_duplicate_dispatch(self):
        p=inventory(1000); p['near_duplicates']={'enabled':False}
        self.plan(p,variants_per_family=2)
        original=pipeline._save_record; count=0
        def interrupt(run,ledger,record):
            nonlocal count
            original(run,ledger,record); count+=1
            if count==500: raise RuntimeError('Controlled fixture checkpoint interruption')
        first=FixtureProvider()
        with patch('email_corpus_forge.pipeline._save_record',side_effect=interrupt), self.assertRaises(RuntimeError):
            run_pipeline(self.run,first)
        self.assertEqual(status_run(self.run)['processed'],500)
        before={p.name:p.read_bytes() for p in (self.run/'raw').glob('*.json')}
        second=FixtureProvider(); result=run_pipeline(self.run,second)
        self.assertEqual(result['requested_candidates'],2000)
        self.assertEqual(result['processed'],2000)
        self.assertEqual(sum(result['counts'].values()),2000)
        self.assertEqual(sum(s=='generate' for s,_ in first.calls)+sum(s=='generate' for s,_ in second.calls),2000)
        self.assertTrue(all((self.run/'raw'/name).read_bytes()==data for name,data in before.items()))
        third=FixtureProvider(); self.assertEqual(run_pipeline(self.run,third),result); self.assertEqual(third.calls,[])
        self.assertEqual(result['budget']['spent_micro'],0)


class AdapterTests(unittest.TestCase):
    def adapter(self):
        return ContractProviderAdapter('explicit-unverified-model',input_rate_micro_per_million=2000000,
               output_rate_micro_per_million=10000000,max_input_tokens=2000,max_output_tokens=1000)

    def test_blind_request_and_explicit_inclusive_usage_cost(self):
        adapter=self.adapter(); packet=blind_packet({'subject':'Fixture','body':'English fixture'})
        request=adapter.build_request('review',packet)
        self.assertFalse(request['dispatch_authorized'])
        self.assertEqual(request['input'],packet)
        request['input']['subject']='changed request copy'
        self.assertEqual(packet['subject'],'Fixture')
        response=adapter.parse_response({'text':'{}','model':adapter.model,'request_id':'offline-contract-fixture',
                                        'usage':{'input_tokens':100,'output_tokens':200,'reasoning_tokens':50}})
        self.assertEqual(adapter.cost_micro(response),2200)  # Inclusive reasoning not billed twice.
        self.assertEqual(adapter.reservation_micro,14000)
        packet['intended_labels']=[]
        with self.assertRaises(ValueError): adapter.build_request('review',packet)
        with self.assertRaises(DispatchNotAuthorized): adapter.generate({})
        with tempfile.TemporaryDirectory() as d:
            run=Path(d)/'run';create_plan(run)
            with self.assertRaises(LiveProviderBlocked): run_pipeline(run,adapter)

    def test_missing_overlimit_or_invalid_usage_fails_closed(self):
        adapter=self.adapter()
        envelope={'text':'{}','model':adapter.model,'request_id':'fixture',
                  'usage':{'input_tokens':100,'output_tokens':200,'reasoning_tokens':50}}
        for change in (lambda e:e['usage'].pop('reasoning_tokens'),lambda e:e['usage'].update(input_tokens=2001),
                       lambda e:e['usage'].update(reasoning_tokens=201),lambda e:e.update(model='wrong')):
            e=copy.deepcopy(envelope);change(e)
            with self.assertRaises(ValueError): adapter.parse_response(e)


if __name__=='__main__': unittest.main()
