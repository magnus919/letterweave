"""Separate observable labels, design adherence and controller resources."""
from .contracts import LABELS, ContractError, validate_content, reviewed_labels


def review_projection(reviews):
    first = reviews[0]['judgments'] if reviews else None
    latest = reviews[-1]['judgments'] if reviews else None
    final = {}
    disagreements = []
    for label in LABELS:
        values = [r['judgments'][label]['decision'] for r in reviews]
        stable = bool(values) and all(r['status'] == 'complete' for r in reviews) and len(set(values)) == 1
        if len(set(values)) > 1:
            disagreements.append(label)
        final[label] = dict(latest[label]) if stable else {'decision': 'unknown', 'evidence': [],
            'reason': 'No complete stable review history.' if not values else 'Review history disagrees or includes an unavailable review.'}
    labels = reviewed_labels({'judgments': final})
    return {'first_pass_judgments': first, 'latest_judgments': latest, 'final_judgments': final,
            'final_labels': labels, 'disagreement_labels': disagreements,
            'label_validity': 'accepted' if reviews and all(v['decision'] != 'unknown' for v in final.values()) else 'held',
            'policy': 'all complete reviews must agree per label; disagreement is unknown, latest is separately visible'}


def scenario_adherence(record):
    final = record_projection(record)
    observed = set(final['final_labels'])
    intended = set(record.get('intended_labels', []))
    hypothesis=record.get('mutation_hypothesis')
    if hypothesis:
        intended=(intended | set(hypothesis['add_labels'])) - set(hypothesis['remove_labels'])
        intended-=set(hypothesis['uncertain_labels'])
    unknown = [l for l,j in final['final_judgments'].items() if j['decision'] == 'unknown']
    return {'status': 'indeterminate' if unknown else 'match' if observed == intended else 'off_target',
            'intended_labels_are': 'design hypotheses, not truth', 'observed_extra': sorted(observed-intended),
            'observed_missing': sorted(intended-observed), 'unknown_labels': unknown}


def validity_assessment(record):
    try:
        validate_content(record.get('content'))
        content = 'valid'
    except ContractError:
        content = 'unavailable' if record.get('content') is None else 'invalid'
    projected = record_projection(record)
    adherence = scenario_adherence(record)
    return {'content_contract': content, 'label_validity': projected['label_validity'],
            'judgment_evidence': 'technical_unavailable' if content != 'valid' or not record.get('reviews') or record.get('review_failure') else 'observed_review',
            'scenario_adherence': adherence, 'review_resource': record.get('review_resource', 'not_recorded'),
            'pool': 'off_target' if content == 'valid' and projected['label_validity'] == 'accepted' and adherence['status']=='off_target'
                    else 'on_target' if content == 'valid' and projected['label_validity']=='accepted' and adherence['status']=='match'
                    else 'unresolved'}


def record_projection(record):
    projection=review_projection(record.get('reviews', []))
    if record.get('review_failure'):
        projection['final_judgments']={l:{'decision':'unknown','evidence':[], 'reason':'Review execution failure; inspect immutable raw evidence.'} for l in LABELS}
        projection['final_labels']=[];projection['label_validity']='held'
    return projection
