"""Build five manual upload fixtures from verified, unmodified local NIH images."""
import csv
import hashlib
import json
import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'extended-test-dataset'
CASES = [
    ('07_fluid_resolution', 'Fluid resolves — label challenge', '00000023_002.png', '00000023_003.png',
     'Pleural effusion is present.',
     'No pleural effusion is identified on this examination.', 'present', 'absent',
     'Resolution on a new patient. The two films look quite similar, so this is also a useful label-versus-model challenge. The current NIH No Finding label is not proof of a normal image.'),
    ('08_other_changes_remain', 'Fluid resolves, other changes remain', '00000044_000.png', '00000044_001.png',
     'Pleural effusion is present. Consolidation and infiltrative opacity are also described.',
     'Pleural thickening and infiltrative opacity remain. No pleural effusion is identified.', 'present', 'absent',
     'Separating fluid from other abnormalities: pleural thickening means thickening of the lung lining, not necessarily fluid. Visible devices and other shadows make this a harder image pair. Absence of fluid must not become a claim that the entire X-ray is normal.'),
    ('09_uncertain_report', 'Report is unsure about fluid', '00000084_000.png', '00000084_001.png',
     'Pleural effusion is present.',
     'A pleural effusion cannot be excluded. Its presence is uncertain on this examination.', 'present', 'uncertain',
     'The current report deliberately hedges despite Effusion labels on both images. Extract uncertainty, not a definite absence or contradiction. Presence in both images does not establish unchanged severity.'),
    ('10_report_silent_on_fluid', 'Reports discuss something else', '00000003_001.png', '00000003_002.png',
     'FINDINGS: Hernia.\nIMPRESSION: Hernia.',
     'FINDINGS: Hernia is again described.\nIMPRESSION: Hernia.', 'no_relevant_claim', 'no_relevant_claim',
     'Both reports are real text inputs but contain no statement about fluid. Missing mention must not be interpreted as no fluid, agreement, or no report uploaded. Hernia is the NIH label on both studies; do not invent a subtype or a severity.'),
    ('11_history_in_current_report', 'Current report mentions the past', '00000039_003.png', '00000039_004.png',
     None,
     'COMPARISON: The earlier examination showed no pleural effusion.\nFINDINGS: Pleural effusion is now present on the current examination.\nIMPRESSION: Interval development of pleural effusion.', None, 'present',
     'Upload only a CURRENT report. It contains both a historical negative and a current positive. Extract present for the current study; do not turn the historical sentence into a current negative or manufacture an uploaded earlier report. The visible change is subtle, so model agreement with the NIH label is not guaranteed.'),
]


def main():
    metadata_path = ROOT / 'data/nih/Data_Entry_2017_v2020.csv'
    with metadata_path.open() as stream:
        metadata = {r['Image Index']: r for r in csv.DictReader(stream)}
    provenance = {r['image']: r for r in json.loads((ROOT / 'data/provenance.json').read_text())}
    manifest = {'source': 'NIH ChestX-ray14', 'metadata_sha256': hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
                'reports': 'Synthetic software-test fixtures, NOT original clinical reports.',
                'live_model_runs_performed': False, 'cases': []}
    OUT.mkdir(exist_ok=True)
    overview = ['# Five additional upload tests', '',
                'All ten images were already available locally; no new download was needed. Images are unmodified copies verified against the existing provenance hashes. Each pair has the same NIH patient ID, increasing consecutive follow-up numbers, and PA views in the metadata.', '',
                'The reports are SIMULATED, not original NIH reports. Definite statements are based on dataset labels; uncertainty and omission are deliberately constructed extraction tests. Missing Effusion labels do not prove absence. No laterality, size, treatment, dates, or elapsed time is inferred.', '',
                'These pairs are new to the six current UI examples and the existing six upload fixtures. They were already candidates in the local pilot catalog, so they are not a held-out accuracy dataset. The first pair extends a resolution pattern attempted in an older upload; the other scenarios add specific extraction and image-complexity challenges.', '',
                '## Upload', '',
                'Open http://127.0.0.1:8765/workspace and select New comparison. For each folder, use the name below, attach 1_earlier_PA.png and 2_current_PA.png, set BOTH views to Taken from the back (PA), and attach the supplied TXT reports to their matching earlier/current fields. In test 11 leave the earlier report empty. Confirm same patient and order, save, then compare. Do not upload README or manifest files as reports.', '',
                'Reports already contain a synthetic-data header. Keep that header when pasting or attaching them.', '',
                '## Cases', '']
    for folder_name, title, prior, current, prior_text, current_text, prior_claim, current_claim, rationale in CASES:
        folder = OUT / folder_name
        folder.mkdir(exist_ok=True)
        a, b = metadata[prior], metadata[current]
        assert a['Patient ID'] == b['Patient ID']
        assert int(b['Follow-up #']) == int(a['Follow-up #']) + 1
        assert a['View Position'] == b['View Position'] == 'PA'
        record = {'folder': folder_name, 'name': title, 'patient_id': a['Patient ID'], 'purpose': rationale, 'images': {}, 'reports': []}
        for scope, original, filename in [('prior', prior, '1_earlier_PA.png'), ('current', current, '2_current_PA.png')]:
            source = ROOT / 'data/images' / original
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            assert digest == provenance[original]['sha256']
            with Image.open(source) as im:
                im.verify()
            shutil.copyfile(source, folder / filename)
            assert hashlib.sha256((folder / filename).read_bytes()).hexdigest() == digest
            row = metadata[original]
            record['images'][scope] = {'file': filename, 'original': original, 'sha256': digest,
                                       'source': provenance[original]['source'], 'view': row['View Position'],
                                       'follow_up': int(row['Follow-up #']), 'labels': row['Finding Labels']}
        for scope, text, claim in [('prior', prior_text, prior_claim), ('current', current_text, current_claim)]:
            if text is None:
                continue
            filename = 'earlier_report.txt' if scope == 'prior' else 'current_report.txt'
            body = 'SYNTHETIC TEST REPORT — not an original clinical report.\n\n' + text + '\n'
            (folder / filename).write_text(body)
            record['reports'].append({'file': filename, 'scope': scope, 'synthetic': True, 'expected_extraction': claim})
        presence = tuple('Effusion' in r['Finding Labels'].split('|') for r in (a, b))
        pattern = {(True, False): 'resolved', (True, True): 'present_both', (False, False): 'absent_both', (False, True): 'new'}[presence]
        record['label_reference_pattern'] = pattern
        instructions = (f'# {title}\n\n{rationale}\n\n'
                        '## Upload\n\n1. Use this title as the comparison name.\n'
                        '2. Earlier image: 1_earlier_PA.png. Current image: 2_current_PA.png.\n'
                        '3. Choose Taken from the back (PA) for BOTH dropdowns.\n'
                        '4. Attach earlier_report.txt under Earlier report if supplied; otherwise leave it empty. '
                        'Attach current_report.txt under Current report. Do not also paste the same report.\n'
                        '5. Confirm same patient and chronological order, save, and compare.\n\n'
                        f'## Reference and checks\n\nNIH labels: earlier {a["Finding Labels"]}; current {b["Finding Labels"]}. '
                        f'Label-derived fluid pattern: {pattern}. This is a reference, not a guaranteed visual finding.\n\n'
                        f'Expected report extraction: earlier {prior_claim or "no report uploaded"}; current {current_claim}.\n\n'
                        'Check quotations match the uploaded text and attach to the correct study. '
                        'If image findings match definite report statements, those claims should agree. '
                        'Uncertain wording should remain uncertain; unrelated text should have no relevant claim. '
                        'A stable definite contradiction may trigger the Investigator; mere uncertainty or omission should not. '
                        'Unstable or unassessable image reads may stop comparison earlier.\n\n'
                        'No paid model calls were run to preselect favorable results. Record any model/label disagreement; do not treat the label as clinical ground truth.\n')
        (folder / 'README.md').write_text(instructions)
        overview.extend([f'- **{title}** (`{folder_name}`): {rationale}', ''])
        manifest['cases'].append(record)
    overview.extend(['## Record results', '',
                     'Use results-template.csv to record run IDs, image patterns, report extractions, and unexpected behavior. These are manual functional tests, not diagnostic accuracy measurements.', '',
                     'Rebuild with `.venv/bin/python scripts/make_extended_test_pack.py` from the project directory. This overwrites generated fixture files but leaves the results sheet intact.'])
    (OUT / 'README.md').write_text('\n'.join(overview) + '\n')
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    results = OUT / 'results-template.csv'
    if not results.exists():
        with results.open('w', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['case', 'run_id', 'image_pattern', 'earlier_report_claim', 'current_report_claim', 'investigator_ran', 'unexpected_behavior'])
            writer.writerows([[c[1], '', '', '', '', '', ''] for c in CASES])
    print(f'Validated {len(CASES)} pairs, 10 original PNGs, 9 synthetic reports: {OUT}')


if __name__ == '__main__':
    main()
