"""Headless pilot evaluation: A naive call vs B strong call vs C TimeLens, plus the anchoring test.

Writes data/eval/results.json for the Evaluation page. Reads NIH reference labels,
which never enter any model prompt. Small n: this is a pilot, not proof.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cases  # noqa: E402
import gemini_direct as gemini  # noqa: E402
import verdict  # noqa: E402

DEFINITE = ('new', 'resolved', 'persistent', 'absent')
CURRENT_STATE = {'new': 'present', 'persistent': 'present', 'resolved': 'absent', 'absent': 'absent'}
SENTENCE = {'present': 'Pleural effusion is present.', 'absent': 'No pleural effusion.'}
LIMIT = asyncio.Semaphore(3)


async def guarded(coro):
    async with LIMIT:
        try:
            return await coro
        except gemini.ModelError as exc:
            return {'error': str(exc)}


def pct(num, den):
    return f'{num}/{den} ({round(100*num/den)}%)' if den else '—'


async def evaluate(case):
    prior, current = (cases.IMAGES/case['prior']['image']).read_bytes(), (cases.IMAGES/case['current']['image']).read_bytes()
    gate = cases.gate(cases.IMAGES/case['prior']['image'], cases.IMAGES/case['current']['image'],
                      case['prior']['view'], case['current']['view'])
    a, b = await asyncio.gather(guarded(gemini.baseline_naive(prior, current)), guarded(gemini.baseline_strong(prior, current)))
    row = {'id': case['id'], 'truth': case['truth']['nih_label'], 'ap_pa': not gate['comparable'],
           'control': case['id'] == 'control',
           'A': a.get('data', {}).get('label', 'error'), 'B': b.get('data', {}).get('label', 'error')}
    if not gate['comparable']:
        row.update(C='cannot_compare', consistent=None, reading=None)
        return row
    pair = await guarded(gemini.read_pair(prior, current))
    if 'error' in pair:
        row.update(C='error', consistent=None, reading=None)
        return row
    reading = pair['data']
    status = verdict.final(gate, reading, [], {'claims': []})
    row.update(C=status['reading_label'] if status['status'] == 'image_only' else status['status'],
               consistent=reading['consistent'], reading=reading)
    return row


async def anchoring(rows, pilot):
    """Same PA pairs; the current-study report is right for even-indexed pairs and wrong for odd ones."""
    by_id = {c['id']: c for c in pilot}
    single = {'n': 0, 'anchored': 0, 'flagged': 0, 'false': 0, 'n_right': 0}
    lens = dict(single)
    jobs = []
    for i, row in enumerate(r for r in rows if not r['ap_pa'] and not r['control']):
        truth_state = CURRENT_STATE[row['truth']]
        wrong = i % 2 == 1
        stated = ({'present': 'absent', 'absent': 'present'}[truth_state]) if wrong else truth_state
        jobs.append((row, wrong, stated))
    calls = await asyncio.gather(*(guarded(gemini.baseline_with_report(
        (cases.IMAGES/by_id[r['id']]['prior']['image']).read_bytes(),
        (cases.IMAGES/by_id[r['id']]['current']['image']).read_bytes(), SENTENCE[s])) for r, _, s in jobs))
    for (row, wrong, stated), call in zip(jobs, calls):
        label = call.get('data', {}).get('label')
        if label in CURRENT_STATE:
            seen = CURRENT_STATE[label]
            key = 'n' if wrong else 'n_right'
            single[key] += 1
            if wrong:
                single['anchored'] += seen == stated
                single['flagged'] += seen != stated
            else:
                single['false'] += seen != stated
        if row['reading'] is not None:
            reports = [{'scope': 'current', 'text': SENTENCE[stated]}]
            claims = {'claims': [{'report_index': 0, 'state': stated, 'quote': SENTENCE[stated]}]}
            blind = row['reading']['reading_a']['current']['state'] if row['reading']['consistent'] else None
            flagged = bool(verdict.disputes(row['reading'], reports, claims))
            key = 'n' if wrong else 'n_right'
            lens[key] += 1
            if wrong:
                lens['anchored'] += blind == stated
                lens['flagged'] += flagged
            else:
                lens['false'] += flagged
    return {'description': 'Each PA pair gets a current-study report sentence that is correct for half the pairs and deliberately '
                           'wrong for the other half. One call sees films + report; TimeLens reads the films blind and then '
                           'compares. "Followed the wrong report" means the call\'s current-film answer matched the wrong sentence. '
                           f'False flags on correct reports: single call {pct(single["false"], single["n_right"])}, '
                           f'TimeLens {pct(lens["false"], lens["n_right"])}.',
            'rows': [{'name': 'One call: films + report', 'n': single['n'], 'anchored': pct(single['anchored'], single['n']),
                      'flagged': pct(single['flagged'], single['n'])},
                     {'name': 'TimeLens: blind read, then compare', 'n': lens['n'], 'anchored': pct(lens['anchored'], lens['n']),
                      'flagged': pct(lens['flagged'], lens['n'])}]}


def summarize(rows, condition, name):
    main = [r for r in rows if not r['ap_pa'] and not r['control']]
    answered = [r for r in main if r[condition] in DEFINITE]
    correct = sum(r[condition] == r['truth'] for r in answered)
    ap = [r for r in rows if r['ap_pa']]
    control = [r for r in rows if r['control']]
    swap = None
    if condition == 'C':
        read = [r for r in main if r['consistent'] is not None]
        swap = pct(sum(r['consistent'] for r in read), len(read))
    return {'id': condition, 'name': name, 'accuracy': pct(correct, len(answered)), 'coverage': pct(len(answered), len(main)),
            'abstention': pct(sum(r[condition] == 'cannot_compare' for r in ap), len(ap)),
            'false_new': pct(sum(r[condition] == 'new' for r in control), len(control)),
            'swap_consistency': swap, 'errors': sum(r[condition] == 'error' for r in rows)}


async def main():
    pilot = json.loads((ROOT/'data'/'pilot_cases.json').read_text())
    started = time.time()
    rows = await asyncio.gather(*(evaluate(c) for c in pilot))
    anchor = await anchoring(rows, pilot)
    _, models = gemini.configuration()
    result = {'created': started, 'seconds': round(time.time()-started, 1), 'model': models[0] + ' (fallbacks: ' + ', '.join(models[1:]) + ')',
              'n_pairs': sum(not r['ap_pa'] and not r['control'] for r in rows), 'n_ap_pa': sum(r['ap_pa'] for r in rows),
              'n_controls': sum(r['control'] for r in rows),
              'conditions': [summarize(rows, 'A', 'One naive call'), summarize(rows, 'B', 'One strong report-blind call that may abstain'),
                             summarize(rows, 'C', 'TimeLens: gate + two-slot blind read')],
              'anchoring': anchor,
              'pairs': [{k: r[k] for k in ('id', 'truth', 'A', 'B', 'C')} for r in rows],
              'honesty': f'{len(rows)} pairs is a pilot: roughly ±20 points of uncertainty. NIH labels are report-mined and noisy. '
                         'Unstable and cannot-compare answers count as abstentions, which lowers coverage. Model capacity errors are '
                         'listed as failed calls, not as wrong answers.'}
    out = ROOT/'data'/'eval'/'results.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1))
    for c in result['conditions']:
        print(c)
    print(anchor['rows'])


if __name__ == '__main__':
    asyncio.run(main())
