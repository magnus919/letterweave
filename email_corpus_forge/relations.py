"""Assess transformation dimensions separately; intent never changes judgments."""
import re
from .contracts import LABELS
from .assessments import record_projection


def mutation_applicability(parent, hypothesis):
    judgments = record_projection(parent or {})['final_judgments']
    checks = {}
    for label in hypothesis['add_labels']:
        decision = judgments[label]['decision']
        checks[label] = 'applicable' if decision == 'absent' else 'inapplicable' if decision == 'present' else 'indeterminate'
    for label in hypothesis['remove_labels']:
        decision = judgments[label]['decision']
        checks[label] = 'applicable' if decision == 'present' else 'inapplicable' if decision == 'absent' else 'indeterminate'
    text=(parent['content']['subject']+'\n'+parent['content']['body']) if parent and parent.get('content') else ''
    normalize = _format_text if hypothesis['operator']=='formatting-preserve' else lambda x:x
    missing_anchors=[a for a in hypothesis.get('preserve_facts',[]) if normalize(a) not in normalize(text)]
    if not parent or not parent.get('content') or missing_anchors:
        status = 'indeterminate'
    elif 'inapplicable' in checks.values():
        status = 'inapplicable'
    elif 'indeterminate' in checks.values():
        status = 'indeterminate'
    elif hypothesis['relation'] == 'preserve' and any(v['decision']=='unknown' for v in judgments.values()):
        status = 'indeterminate'
    else:
        status = 'applicable'
    return {'status': status, 'preconditions': checks, 'missing_parent_fact_anchors':missing_anchors, 'basis': 'stable observed parent labels; no intended-label substitution'}


def _format_text(text):
    """Only case and whitespace change; punctuation, numbers and order retained."""
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _format_content(content):
    return tuple(_format_text(content[k]) for k in ("subject", "body"))


def _tokens(content):
    return re.findall(r"\w+", (content['subject']+'\n'+content['body']).casefold())


def fact_preservation(parent, child, hypothesis):
    before, after = parent.get('content') if parent else None, child.get('content') if child else None
    if not before or not after:
        return {'status':'indeterminate','method':'content unavailable','semantic_fact_preservation_established':False}
    anchors = hypothesis.get('preserve_facts', [])
    text_before = before['subject']+'\n'+before['body'];text_after=after['subject']+'\n'+after['body']
    formatting = hypothesis['relation']=='preserve' and hypothesis['operator']=='formatting-preserve'
    normalize = _format_text if formatting else lambda x:x
    missing_parent=[a for a in anchors if normalize(a) not in normalize(text_before)]
    lost=[a for a in anchors if normalize(a) not in normalize(text_after)]
    if formatting:
        # Full subject/body equality prevents retained anchors masking new facts,
        # negation, punctuation changes or reordered content in a formatting task.
        status='indeterminate' if missing_parent else 'pass' if _format_content(before)==_format_content(after) else 'fail'
        method='full ordered subject/body equality after case/whitespace normalization; punctuation retained; semantic equivalence not established'
    elif anchors:
        status='indeterminate' if missing_parent else 'fail' if lost else 'pass'
        method='predeclared literal fact anchors only; does not detect contradictory additions'
    else:
        status='indeterminate';method='no predeclared fact anchors; no semantic preservation claim'
    return {'status':status,'method':method,'anchors':anchors,'missing_parent_anchors':missing_parent,
            'lost_anchors':lost,'semantic_fact_preservation_established':False}


def evaluate_relation(parent, child, hypothesis):
    projections=[record_projection(r or {}) for r in (parent,child)]
    results={};comparison={}
    for label in LABELS:
        before,after=[p['final_judgments'][label]['decision'] for p in projections]
        comparison[label]={'parent':before,'descendant':after}
        if label in hypothesis['uncertain_labels']:
            result='indeterminate' if before not in {'present','absent'} else 'pass' if after=='unknown' else 'fail'
        elif before not in {'present','absent'} or after not in {'present','absent'}:
            result='indeterminate'
        elif label in hypothesis['add_labels']:
            result='pass' if (before,after)==('absent','present') else 'fail'
        elif label in hypothesis['remove_labels']:
            result='pass' if (before,after)==('present','absent') else 'fail'
        else:
            result='pass' if before==after else 'fail'
        results[label]=result
    label_result='fail' if 'fail' in results.values() else 'indeterminate' if 'indeterminate' in results.values() else 'pass'
    applicable=mutation_applicability(parent,hypothesis)
    before=parent.get('content') if parent else None;after=child.get('content') if child else None
    change='indeterminate' if not before or not after else 'no_op' if before==after else 'changed'
    facts=fact_preservation(parent,child,hypothesis)
    result='fail' if applicable['status']=='inapplicable' or change=='no_op' or facts['status']=='fail' or label_result=='fail' else 'pass' if applicable['status']=='applicable' and change=='changed' and facts['status']=='pass' and label_result=='pass' else 'indeterminate'
    return {'result':result,'per_label':results,'judgment_comparison':comparison,'label_relation':label_result,
            'applicability':applicable,'content_change':change,'fact_preservation':facts,
            'local_checks_pass':result=='pass',
            'basis':'isolated blind item review histories plus explicit controller checks; hypothesis is not gold',
            'evidence_kind':'mechanical diagnostics; semantic preservation not established'}
