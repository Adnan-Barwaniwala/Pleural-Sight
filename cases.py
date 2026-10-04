"""Curated case catalog and the deterministic comparability gate. No model calls."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parent
IMAGES = ROOT/'data'/'images'
CATALOG = ROOT/'data'/'cases.json'


def catalog():
    """Curated demo + pilot cases. `truth` is never placed in a run manifest."""
    if not CATALOG.exists():
        return []
    return json.loads(CATALOG.read_text())


def public(case):
    """Case view for the browser; the reference label is shown, labelled as noisy."""
    return {key: value for key, value in case.items() if key != 'truth'} | (
        {'reference': case['truth']} if case.get('truth') else {})


def gate(prior_path, current_path, prior_view, current_view):
    """Server-side comparability gate computed before any agent or model runs."""
    flags, reasons = [], []
    prior_bytes, current_bytes = Path(prior_path).read_bytes(), Path(current_path).read_bytes()
    if hashlib.sha256(prior_bytes).digest() == hashlib.sha256(current_bytes).digest():
        reasons.append('The two files are byte-identical, so this is not a follow-up comparison.')
    known = prior_view in ('PA', 'AP') and current_view in ('PA', 'AP')
    if known and prior_view != current_view:
        reasons.append(f'Projection mismatch: prior {prior_view} vs current {current_view}. '
                       'AP films are usually supine or portable, which spreads fluid and magnifies the heart, '
                       'so a change in effusion cannot be judged reliably.')
    elif not known:
        flags.append('View position not supplied for one or both films; projection was not verified.')
    return {'comparable': not reasons, 'reasons': reasons, 'flags': flags,
            'views': {'prior': prior_view or 'unknown', 'current': current_view or 'unknown'}}
