"""Create demo-test-cases/: ready-to-upload X-ray pairs, reports and expected results."""
import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'demo-test-cases'
IMAGES = ROOT/'data'/'images'

# folder: (earlier image, current image, earlier view, current view, earlier report, current report, expected)
CASES = {
    '1_no_fluid_then_fluid': (
        '00000078_000.png', '00000078_001.png', 'PA', 'PA',
        'The lungs are clear. No pleural effusion.',
        'New small bilateral pleural effusions, more prominent on the left.',
        'Headline: "Possible new fluid in the current study."\n'
        'Earlier image: No fluid detected. Current image: Fluid detected.\n'
        'Both study cards: "Sources agree". Summary: "Images and reports agree."\n'
        'Checked: the image review gave the same answer on repeated runs (fluid on both sides, more on the left).'),
    '2_images_only': (
        '00000099_000.png', '00000099_001.png', 'PA', 'PA', None, None,
        'Headline: "Fluid is detected in both X-rays."\n'
        'Summary: "Image findings only. No report attached." Reports step shows "Skipped".\n'
        'Checked: both image reviews agreed (fluid on both sides in both X-rays).'),
    '3_front_and_back_views': (
        '00000013_017.png', '00000013_018.png', 'PA', 'AP', None, None,
        'IMPORTANT: set "Earlier image" to "Taken from the back (PA)" and "Current image" to "Taken from the front (AP)".\n'
        'Finishes in about a second with no AI calls.\n'
        'Headline: "Change could not be determined." Summary: "These images were not compared. The earlier X-ray was taken\n'
        'from the back (PA) and the current one from the front (AP)..." Run details: all reviews "Not needed".'),
    '4_report_disagrees': (
        '00000061_002.png', '00000061_003.png', 'PA', 'PA',
        'Large right pleural effusion.',
        'The lungs are clear. No pleural effusion.',
        'Headline: "Fluid is detected in both X-rays."\n'
        'Earlier study card: "Sources agree". Current study card: "Sources disagree".\n'
        'Summary: "A report differs from the images. A second, focused look at the images gave the same answer."\n'
        'Run details: Images, Reports and Second look all reviewed (3 OpenSwarm agents).\n'
        'Checked live end to end through OpenSwarm.'),
    '5_upload_set_A_fluid_both_reports_agree': (
        '00000096_002.png', '00000096_003.png', 'PA', 'PA',
        'Bilateral pleural effusions.',
        'Persistent bilateral pleural effusions, similar to the prior study.',
        'Headline: "Fluid is detected in both X-rays."\n'
        'Both study cards: "Sources agree". Summary: "Images and reports agree."\n'
        'Checked: both image reviews agreed (fluid on both sides in both X-rays).'),
    '6_upload_set_B_report_says_fluid_but_images_clear': (
        '00000022_000.png', '00000022_001.png', 'PA', 'PA',
        'No pleural effusion.',
        'New moderate left pleural effusion.',
        'Headline: "No fluid detected in either study."\n'
        'Earlier study card: "Sources agree". Current study card: "Sources disagree" (the report claims fluid the images do not show).\n'
        'Summary: "A report differs from the images. A second, focused look..." Run details include "Second look".\n'
        'Checked: both image reviews agreed (no fluid on either X-ray).'),
}
VIEW = {'PA': 'Taken from the back (PA)', 'AP': 'Taken from the front (AP)'}


def blank_pdf(path):
    from pypdf import PdfWriter
    writer = PdfWriter(); writer.add_blank_page(width=612, height=792)
    with open(path, 'wb') as f:
        writer.write(f)


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    for name, (earlier, current, earlier_view, current_view, earlier_report, current_report, expected) in CASES.items():
        folder = OUT/name
        folder.mkdir(parents=True)
        shutil.copy(IMAGES/earlier, folder/f'1_earlier_{earlier_view}.png')
        shutil.copy(IMAGES/current, folder/f'2_current_{current_view}.png')
        steps = [f'Earlier image: 1_earlier_{earlier_view}.png  ->  dropdown "{VIEW[earlier_view]}"',
                 f'Current image: 2_current_{current_view}.png  ->  dropdown "{VIEW[current_view]}"']
        if earlier_report:
            (folder/'earlier_report.txt').write_text(earlier_report)
            steps.append(f'Add written reports -> Earlier report: paste "{earlier_report}" (or attach earlier_report.txt)')
        if current_report:
            (folder/'current_report.txt').write_text(current_report)
            steps.append(f'Add written reports -> Current report: paste "{current_report}" (or attach current_report.txt)')
        if not (earlier_report or current_report):
            steps.append('No reports: leave "Add written reports" closed.')
        steps.append('Tick both boxes -> Save comparison -> Compare studies.')
        (folder/'README.txt').write_text('HOW TO UPLOAD\n' + '\n'.join('- ' + s for s in steps) +
                                         '\n\nWHAT YOU SHOULD SEE\n' + expected + '\n\nNIH images; reports were written for testing.\n')
    bad = OUT/'7_should_be_rejected'
    bad.mkdir()
    (bad/'not_an_image.png').write_text('this is not an image')
    Image.new('L', (64, 64), 128).save(bad/'too_small_64px.png')
    blank_pdf(bad/'scanned_blank_report.pdf')
    (bad/'report.docx').write_bytes(b'PK\x03\x04 not a real document')
    (bad/'README.txt').write_text(
        'Use any good image pair from another folder, then swap in one of these files:\n'
        '- not_an_image.png as an image  -> "The image is corrupt or too large to decode safely."\n'
        '- too_small_64px.png as an image -> "Images must be 128-8192 pixels per side and at most 25 megapixels."\n'
        '- scanned_blank_report.pdf as a report -> "No readable text found. Scanned PDFs are not supported; paste the text instead."\n'
        '- report.docx as a report -> "Use a TXT file or a PDF with selectable text."\n'
        '- Leave the two boxes unticked -> the form asks you to tick them.\n')
    print('Created', OUT)


if __name__ == '__main__':
    main()
