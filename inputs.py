"""Bounded image and report ingestion. Never sends data to a model."""
from io import BytesIO
import warnings
from PIL import Image
from pypdf import PdfReader

MAX_IMAGE = 10 * 1024 * 1024
MAX_REPORT = 2 * 1024 * 1024

def validate_image(data):
    if not data or len(data) > MAX_IMAGE:
        raise ValueError('Each image must be between 1 byte and 10 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as im:
                if im.format not in ('PNG', 'JPEG'):
                    raise ValueError('Use a PNG or JPEG image.')
                if not all(128 <= n <= 8192 for n in im.size) or im.width * im.height > 25_000_000:
                    raise ValueError('Images must be 128–8192 pixels per side and at most 25 megapixels.')
                info = {'width':im.width, 'height':im.height, 'format':im.format, 'projection':'unknown', 'quality':'not assessed'}
                im.verify()
            with Image.open(BytesIO(data)) as im:
                im.load()
        return info
    except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError('The image is corrupt or too large to decode safely.') from exc

def extract_report(data, filename):
    if len(data) > MAX_REPORT:
        raise ValueError('Report files must be 2 MB or smaller.')
    if filename.lower().endswith('.pdf'):
        try:
            pdf = PdfReader(BytesIO(data))
            if pdf.is_encrypted or len(pdf.pages) > 20:
                raise ValueError('Use an unencrypted PDF with at most 20 pages.')
            text = '\n'.join(page.extract_text() or '' for page in pdf.pages)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('This PDF could not be read. Paste its report text instead.') from exc
    elif filename.lower().endswith('.txt'):
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise ValueError('TXT reports must use UTF-8 encoding.') from exc
    else:
        raise ValueError('Use a TXT file or a PDF with selectable text.')
    return validate_text(text)

def validate_text(text):
    text = text.strip()
    if not text:
        raise ValueError('No readable text found. Scanned PDFs are not supported; paste the text instead.')
    if len(text) > 50000:
        raise ValueError('Each report must be at most 50,000 characters.')
    return text
