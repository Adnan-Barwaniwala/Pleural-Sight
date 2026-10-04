"""Build the case lists from NIH metadata.

data/cases.json       - the four test cases shown on the website
data/pilot_cases.json - the 19-pair pilot set plus a near-duplicate control, used only by run_eval.py

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

# (id, name, description, earlier image, current image, earlier report, current report)
WEBSITE = [
    ('case-1', '1 · No fluid, then fluid',
     'Earlier X-ray: no fluid. Current X-ray: new fluid on both sides. Each written report matches its own X-ray. '
     'Reports were written for this demo.',
     '00000078_000.png', '00000078_001.png',
     'The lungs are clear. No pleural effusion.',
     'New small bilateral pleural effusions, more prominent on the left.'),
    ('case-2', '2 · Images only',
     'Fluid on both sides in both X-rays (NIH labels). No written reports, so only the images are compared.',
     '00000099_000.png', '00000099_001.png', None, None),
    ('case-3', '3 · Front and back views',
     'The earlier X-ray was taken from the back (PA) and the current one from the front (AP). '
     'Different views can create or hide the look of fluid, so TimeLens refuses to compare them.',
     '00000013_017.png', '00000013_018.png', None, None),
    ('case-4', '4 · Report disagrees',
     'Fluid on the right in both X-rays. The earlier report matches its X-ray, but the current report wrongly says the lungs '
     'are clear. Reports were written for this demo.',
     '00000061_002.png', '00000061_003.png',
     'Large right pleural effusion.',
     'The lungs are clear. No pleural effusion.'),
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
        return {**film('00000008_000.png'), 'image': CONTROL, 'derived': 'Cropped 3% per edge and brightened 8% from 00000008_000.png'}
    row = META[name]
    return {'image': name, 'order': int(row['Follow-up #']), 'view': row['View Position'],
            'findings': row['Finding Labels'], 'effusion': 'Effusion' in row['Finding Labels']}


def label(prior, current):
    return {(False, False): 'absent', (False, True): 'new', (True, False): 'resolved', (True, True): 'persistent'}[
        (prior['effusion'], current['effusion'])]


def case(case_id, name, purpose, prior_name, current_name, earlier_report=None, current_report=None, case_set='demo'):
    prior, current = film(prior_name), film(current_name)
    reports = [{'scope': scope, 'text': text, 'source': 'synthetic', 'synthetic': True}
               for scope, text in (('prior', earlier_report), ('current', current_report)) if text]
    return {'id': case_id, 'set': case_set, 'name': name, 'purpose': purpose, 'source': 'NIH ChestX-ray14',
            'patient_id': META[prior_name if prior_name != CONTROL else '00000008_000.png']['Patient ID'],
            'prior': prior, 'current': current, 'reports': reports,
            'truth': {'nih_label': 'absent' if current_name == CONTROL else label(prior, current),
                      'expected_status': 'cannot_compare' if prior['view'] != current['view'] else None,
                      'note': 'NIH labels are mined from reports and can be wrong.'}}


def main():
    make_control()
    website = [case(*row) for row in WEBSITE]
    (ROOT/'data'/'cases.json').write_text(json.dumps(website, indent=2))
    pilot = []
    for i, (p, c) in enumerate(PILOT, 1):
        prior, current = film(p), film(c)
        kind = 'different views' if prior['view'] != current['view'] else 'NIH label: ' + label(prior, current)
        pilot.append(case(f'pilot-{i:02}', f'Pilot {i:02} · patient {int(META[p]["Patient ID"])}',
                          f'NIH test pair ({kind}), follow-up {prior["order"]} to {current["order"]}.', p, c, case_set='pilot'))
    pilot.append(case('control', 'Near-duplicate control', 'Current image is a cropped, brightened copy of the earlier one.',
                      '00000008_000.png', CONTROL, case_set='pilot'))
    (ROOT/'data'/'pilot_cases.json').write_text(json.dumps(pilot, indent=2))
    print(len(website), 'website cases,', len(pilot), 'pilot cases written')


if __name__ == '__main__':
    main()
