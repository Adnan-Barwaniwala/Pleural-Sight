"""Build data/cases.json from NIH metadata: demo slots A-E plus the pilot evaluation set.

Labels follow the spec rule: Effusion flag on consecutive films -> new / resolved /
persistent / absent. NIH labels are report-mined and noisy; they are reference
labels, not ground truth, and are never placed in a run manifest.
"""
import csv
import json
import pathlib

from PIL import Image, ImageEnhance

ROOT = pathlib.Path(__file__).resolve().parents[1]
IMAGES = ROOT/'data'/'images'
META = {row['Image Index']: row for row in csv.DictReader(open(ROOT/'data'/'nih'/'Data_Entry_2017_v2020.csv'))}
CONTROL = 'control_00000008_000_crop_bright.png'

SYNTHETIC_C = 'Stable cardiomegaly. No significant interval change. No pleural effusion.'
SYNTHETIC_D = 'Persistent pleural effusion, similar to the prior study.'

DEMO = [
    ('case-A', 'A', 'New fluid', 'NIH labels: no fluid on the earlier X-ray, fluid on the current one. Both taken from the back (PA).', '00000001_001.png', '00000001_002.png', None),
    ('case-B', 'B', 'Different X-ray views', 'The earlier X-ray was taken from the back (PA) and the current one from the front (AP), so they should not be compared.', '00000013_017.png', '00000013_018.png', None),
    ('case-C', 'C', 'Report says no fluid', 'Same X-rays as Case A, plus a written report made up for this demo that says there is no fluid.', '00000001_001.png', '00000001_002.png', SYNTHETIC_C),
    ('case-D', 'D', 'Report agrees', 'NIH labels: fluid on both X-rays, plus a demo report that says the fluid is still there.', '00000061_002.png', '00000061_003.png', SYNTHETIC_D),
    ('case-E', 'E', 'Edited copy', 'The current image is a slightly cropped and brightened copy of the earlier one, so nothing should change.', '00000008_000.png', CONTROL, None),
]
PILOT = [
    ('00000001_001.png', '00000001_002.png'), ('00000005_006.png', '00000005_007.png'),
    ('00000039_003.png', '00000039_004.png'), ('00000056_000.png', '00000056_001.png'),
    ('00000011_000.png', '00000011_001.png'), ('00000023_002.png', '00000023_003.png'),
    ('00000038_000.png', '00000038_001.png'), ('00000044_000.png', '00000044_001.png'),
    ('00000061_002.png', '00000061_003.png'), ('00000084_000.png', '00000084_001.png'),
    ('00000096_002.png', '00000096_003.png'), ('00000099_000.png', '00000099_001.png'),
    ('00000001_000.png', '00000001_001.png'), ('00000003_001.png', '00000003_002.png'),
    ('00000008_000.png', '00000008_001.png'), ('00000022_000.png', '00000022_001.png'),
    ('00000005_000.png', '00000005_001.png'), ('00000013_017.png', '00000013_018.png'),
    ('00000011_004.png', '00000011_005.png'),
]


def make_control():
    path = IMAGES/CONTROL
    if path.exists():
        return
    with Image.open(IMAGES/'00000008_000.png') as im:
        w, h = im.size
        dx, dy = int(w*.03), int(h*.03)
        cropped = im.crop((dx, dy, w-dx, h-dy)).resize((w, h), Image.Resampling.LANCZOS)
        ImageEnhance.Brightness(cropped).enhance(1.08).save(path)


def film(name):
    if name == CONTROL:
        base = film('00000008_000.png')
        return {**base, 'image': CONTROL, 'derived': 'Cropped 3% per edge and brightened 8% from 00000008_000.png'}
    row = META[name]
    return {'image': name, 'order': int(row['Follow-up #']), 'view': row['View Position'],
            'findings': row['Finding Labels'], 'effusion': 'Effusion' in row['Finding Labels']}


def label(prior, current):
    return {(False, False): 'absent', (False, True): 'new', (True, False): 'resolved', (True, True): 'persistent'}[
        (prior['effusion'], current['effusion'])]


def case(case_id, title, purpose, prior_name, current_name, report, slot=None, case_set='demo'):
    prior, current = film(prior_name), film(current_name)
    nih = label(prior, current)
    if current_name == CONTROL:
        nih = 'absent'
    comparable = prior['view'] == current['view']
    return {'id': case_id, 'slot': slot, 'set': case_set, 'name': title, 'purpose': purpose,
            'source': 'NIH ChestX-ray14' + (' + derived control' if current_name == CONTROL else ''),
            'patient_id': META[prior_name if prior_name != CONTROL else '00000008_000.png']['Patient ID'],
            'prior': prior, 'current': current,
            'reports': [{'scope': 'current', 'text': report, 'source': 'synthetic', 'synthetic': True}] if report else [],
            'truth': {'nih_label': nih, 'expected_status': 'cannot_compare' if not comparable else None,
                      'note': 'NIH labels are mined from reports and can be wrong.'}}


def main():
    make_control()
    cases = [case(cid, f'Case {slot} · {title}', purpose, p, c, r, slot) for cid, slot, title, purpose, p, c, r in DEMO]
    for i, (p, c) in enumerate(PILOT, 1):
        prior, current = film(p), film(c)
        kind = 'different views' if prior['view'] != current['view'] else 'NIH label: ' + label(prior, current)
        cases.append(case(f'pilot-{i:02}', f'Pilot {i:02} · patient {int(META[p]["Patient ID"])}',
                          f'NIH test pair ({kind}), follow-up {prior["order"]} to {current["order"]}.',
                          p, c, None, case_set='pilot'))
    (ROOT/'data'/'cases.json').write_text(json.dumps(cases, indent=2))
    print(len(cases), 'cases written')


if __name__ == '__main__':
    main()
