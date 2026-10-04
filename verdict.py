"""Deterministic diffing, dispute detection and final status. LLMs only read images and text."""

STATUS_ORDER = {'disagreement': 0, 'cannot_compare': 1, 'unstable': 2, 'image_only': 3, 'agrees': 4}
STATUS_TEXT = {'disagreement': 'Disagreement', 'cannot_compare': 'Cannot compare', 'unstable': 'Unstable read',
               'image_only': 'Image only', 'agrees': 'Agrees with report'}
DEFINITE = ('present', 'absent')
LIMITATIONS = ['Labels and model readings can be wrong.',
               'Agent agreement is not a confidence score.',
               'Research prototype; every flag needs clinician review.']


def consensus(reading):
    """Per-film states when both slot orders agree, else None."""
    if not reading['consistent']:
        return None
    return {scope: reading['reading_a'][scope]['state'] for scope in ('prior', 'current')}


def compare_claims(states, reports, extracted):
    matches = []
    for claim in extracted['claims']:
        report = reports[claim['report_index']]
        visual, stated = states[report['scope']], claim['state']
        if stated == 'no_relevant_claim':
            verdict = 'no_relevant_claim'
        elif visual not in DEFINITE or stated == 'uncertain':
            verdict = 'uncertainty'
        else:
            verdict = 'agreement' if visual == stated else 'contradiction'
        matches.append({**claim, 'scope': report['scope'], 'synthetic': bool(report.get('synthetic')),
                        'verdict': verdict})
    return matches


def disputes(reading, reports, extracted):
    """Films where a stable, definite blind read contradicts a report claim."""
    states = consensus(reading)
    if states is None or any(s not in DEFINITE for s in states.values()):
        return []
    return sorted({c['scope'] for c in compare_claims(states, reports, extracted) if c['verdict'] == 'contradiction'})


def targeted_question(scopes):
    films = ' and '.join({'prior': 'FILM 1', 'current': 'FILM 2'}[s] for s in scopes)
    return (f'An independent source disputes the pleural-effusion call on {films}. Re-examine {films} specifically: '
            'are both costophrenic angles sharp, is there a meniscus, and is there blunting of the lateral or posterior '
            'sulci? Decide presence on each film again from the pixels alone.')


def final(gate, reading, reports, extracted, reassessment=None):
    gate_reasons = gate.get('reasons', [])
    base = {'finding': 'pleural_effusion', 'limitations': LIMITATIONS + gate.get('flags', [])}
    if not gate.get('comparable', True):
        return {**base, 'status': 'cannot_compare', 'reading_label': None, 'order_swap_consistent': None,
                'summary': 'Comparability gate stopped the run before any model call. ' + gate_reasons[0],
                'claims': []}
    a, b = reading['reading_a'], reading['reading_b']
    unassessable = [s for r in (a, b) for s in ('prior', 'current') if r[s]['state'] == 'not_assessable']
    if unassessable:
        return {**base, 'status': 'cannot_compare', 'reading_label': None, 'order_swap_consistent': reading['consistent'],
                'summary': 'The blind reader could not assess at least one film, so it abstained.', 'claims': []}
    if not reading['consistent']:
        return {**base, 'status': 'unstable', 'reading_label': None, 'order_swap_consistent': False,
                'summary': f'The answer flipped when the films swapped slots (Reading A: {a["label"]}, '
                           f'Reading B: {b["label"]}). Read this case manually.', 'claims': []}
    states = consensus(reading)
    label = a['label']
    if label == 'indeterminate':
        return {**base, 'status': 'cannot_compare', 'reading_label': None, 'order_swap_consistent': True,
                'summary': 'The blind reader was uncertain about at least one film on both slot orders, so it abstained.',
                'claims': []}
    if not reports:
        return {**base, 'status': 'image_only', 'reading_label': label, 'order_swap_consistent': True,
                'summary': f'Blind read: {label.replace("_", " ")} effusion pattern on both slot orders. No report attached.',
                'claims': []}
    claims = compare_claims(states, reports, extracted)
    disputed = [c for c in claims if c['verdict'] == 'contradiction']
    if disputed and reassessment:
        re_states = {s: reassessment['data'][s]['state'] for s in ('prior', 'current')}
        still = [c for c in compare_claims(re_states, reports, extracted) if c['verdict'] == 'contradiction']
        if still:
            c = still[0]
            return {**base, 'status': 'disagreement', 'reading_label': label, 'order_swap_consistent': True,
                    'reassessment_label': reassessment['data']['label'], 'claims': claims,
                    'summary': f'Blind read says {c["scope"]} film effusion is {re_states[c["scope"]]}; '
                               f'the {c["scope"]} report says {c["state"]} ("{c["quote"]}"). '
                               'Still conflicting after one targeted reassessment.'}
        return {**base, 'status': 'agrees', 'reading_label': reassessment['data']['label'], 'order_swap_consistent': True,
                'reassessment_label': reassessment['data']['label'], 'claims': claims,
                'summary': 'The initial blind read conflicted with the report, but the targeted reassessment agreed with the report. '
                           'Both readings are preserved for review.'}
    if disputed:
        c = disputed[0]
        return {**base, 'status': 'disagreement', 'reading_label': label, 'order_swap_consistent': True, 'claims': claims,
                'summary': f'Blind read says {c["scope"]} film effusion is {states[c["scope"]]}; the report says {c["state"]}. '
                           'No reassessment was available.'}
    relevant = [c for c in claims if c['verdict'] == 'agreement']
    summary = (f'Blind read ({label.replace("_", " ")}) matches the report.' if relevant else
               f'Blind read: {label.replace("_", " ")}. The report makes no definite effusion claim to check.')
    return {**base, 'status': 'agrees' if relevant else 'image_only', 'reading_label': label,
            'order_swap_consistent': True, 'claims': claims, 'summary': summary}
