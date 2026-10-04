"""Shapes cases and runs for the workspace UI (static/app.js) in plain language.

The UI reads `result.initial.data`, `result.comparison`, `result.agents` and
`run.progress.{assess_images,read_reports}`. The pipeline's richer result stays
stored unchanged; this module only presents it.
"""
import verdict

STAGES = {'readers_running': 'agents_running', 'investigating': 'agents_running',
          'finalizing': 'comparing', 'gate_stopped': 'comparing'}
TRANSITIONS = {'new': 'new', 'resolved': 'resolved', 'persistent': 'present_both', 'absent': 'absent_both'}
WORDS = {'present': 'fluid', 'absent': 'no fluid', 'uncertain': 'unsure', 'not_assessable': 'could not tell'}
VIEW = {'PA': 'from the back (PA)', 'AP': 'from the front (AP)'}


def case(item):
    out = {key: value for key, value in item.items() if key not in ('prior', 'current')}
    out['prior'], out['current'] = item['prior']['image'], item['current']['image']
    out['assertions'] = item.get('purpose') or ''
    if 'width' in item['prior']:
        out['metadata'] = {scope: {k: item[scope][k] for k in ('width', 'height', 'sha256')} for scope in ('prior', 'current')}
    if item.get('last_run'):
        out['last_run'] = run(item['last_run'], item)
    return out


def run(record, item):
    out = dict(record)
    out['stage'] = STAGES.get(record.get('stage'), record.get('stage'))
    progress = record.get('progress') or {}
    out['progress'] = {'assess_images': progress.get('read_pair', 'waiting'),
                       'read_reports': progress.get('read_reports', 'waiting')}
    if record.get('result') and record['result'].get('verdict'):
        out['result'] = result(record['result'], item)
    if record.get('error'):
        out['error'] = record['error'].replace('Blind Reader', 'Image review').replace('Report Reader', 'Report review')
    return out


def gate_text(item, gate):
    views = gate.get('views', {})
    if views.get('prior') in VIEW and views.get('current') in VIEW and views['prior'] != views['current']:
        return (f"The earlier X-ray was taken {VIEW[views['prior']]} and the current one {VIEW[views['current']]}. "
                'Different views can create or hide the look of fluid, so the two images were not compared.')
    return 'The two files are identical, so there is no change to compare.'


def result(stored, item):
    v, gate = stored['verdict'], stored.get('gate', {})
    reading = stored['reading']['data'] if stored.get('reading') else None
    images, note = {}, None
    if reading is None:
        text = gate_text(item, gate)
        images = {s: {'state': 'not_assessable', 'evidence': text, 'limitations': []} for s in ('prior', 'current')}
        note = 'These images were not compared. ' + text
    else:
        a, b = reading['reading_a'], reading['reading_b']
        for s in ('prior', 'current'):
            if a[s]['state'] == b[s]['state']:
                images[s] = {k: a[s][k] for k in ('state', 'evidence', 'limitations')}
            else:
                images[s] = {'state': 'not_assessable',
                             'evidence': f"Two independent passes reviewed the image in opposite study order and disagreed "
                                         f"({WORDS[a[s]['state']]} vs {WORDS[b[s]['state']]}), so TimeLens does not guess. "
                                         f"First pass: {a[s]['evidence']} Second pass: {b[s]['evidence']}",
                             'limitations': a[s]['limitations'] + b[s]['limitations']}
        if not reading['consistent']:
            note = ('The image review ran two independent passes in opposite study order. They disagreed, so TimeLens '
                    'does not guess. A human should review the images.')
    states = {s: images[s]['state'] for s in ('prior', 'current')}
    extracted = (stored.get('reports') or {}).get('data') or {'claims': []}
    claims = [{k: c[k] for k in ('report_index', 'scope', 'state', 'quote', 'verdict')}
              for c in verdict.compare_claims(states, item['reports'], extracted)] if item['reports'] and extracted['claims'] else []
    re = stored.get('reassessment')
    if re and v['status'] == 'disagreement':
        note = 'A report differs from the images. A second, focused look at the images gave the same answer. Review the evidence.'
    elif re and v['status'] == 'agrees':
        note = 'The images first differed from the report, but a second, focused look agreed with the report. Review the evidence.'
    transition = verdict_transition(states)
    labels = {'completed': 'completed', 'completed_headless': 'completed', 'skipped_no_report': 'skipped_no_report',
              'skipped_gate_failed': 'Not needed', 'skipped_no_dispute': 'Not needed'}
    agents = [{'role': a['role'], 'status': labels.get(a['status'], a['status']), 'session_id': a.get('session_id'),
               'tool_calls': a.get('tool_calls', 0)} for a in stored.get('agents', [])]
    return {'initial': {'data': images}, 'comparison': {'transition': transition, 'claims': claims, 'note': note,
            'report_status': 'uploaded' if item['reports'] else 'no_report'},
            'agents': agents, 'orchestrator': stored.get('orchestrator'), 'status': 'needs_human_review', 'version': 2}


def verdict_transition(states):
    from gemini_direct import transition
    return TRANSITIONS.get(transition(states['prior'], states['current']), 'indeterminate')
