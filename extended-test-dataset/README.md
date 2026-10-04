# Five additional upload tests

All ten images were already available locally; no new download was needed. Images are unmodified copies verified against the existing provenance hashes. Each pair has the same NIH patient ID, increasing consecutive follow-up numbers, and PA views in the metadata.

The reports are SIMULATED, not original NIH reports. Definite statements are based on dataset labels; uncertainty and omission are deliberately constructed extraction tests. Missing Effusion labels do not prove absence. No laterality, size, treatment, dates, or elapsed time is inferred.

These pairs are new to the six current UI examples and the existing six upload fixtures. They were already candidates in the local pilot catalog, so they are not a held-out accuracy dataset. The first pair extends a resolution pattern attempted in an older upload; the other scenarios add specific extraction and image-complexity challenges.

## Upload

Open http://127.0.0.1:8765/workspace and select New comparison. For each folder, use the name below, attach 1_earlier_PA.png and 2_current_PA.png, set BOTH views to Taken from the back (PA), and attach the supplied TXT reports to their matching earlier/current fields. In test 11 leave the earlier report empty. Confirm same patient and order, save, then compare. Do not upload README or manifest files as reports.

Reports already contain a synthetic-data header. Keep that header when pasting or attaching them.

## Cases

- **Fluid resolves — label challenge** (`07_fluid_resolution`): Resolution on a new patient. The two films look quite similar, so this is also a useful label-versus-model challenge. The current NIH No Finding label is not proof of a normal image.

- **Fluid resolves, other changes remain** (`08_other_changes_remain`): Separating fluid from other abnormalities: pleural thickening means thickening of the lung lining, not necessarily fluid. Visible devices and other shadows make this a harder image pair. Absence of fluid must not become a claim that the entire X-ray is normal.

- **Report is unsure about fluid** (`09_uncertain_report`): The current report deliberately hedges despite Effusion labels on both images. Extract uncertainty, not a definite absence or contradiction. Presence in both images does not establish unchanged severity.

- **Reports discuss something else** (`10_report_silent_on_fluid`): Both reports are real text inputs but contain no statement about fluid. Missing mention must not be interpreted as no fluid, agreement, or no report uploaded. Hernia is the NIH label on both studies; do not invent a subtype or a severity.

- **Current report mentions the past** (`11_history_in_current_report`): Upload only a CURRENT report. It contains both a historical negative and a current positive. Extract present for the current study; do not turn the historical sentence into a current negative or manufacture an uploaded earlier report. The visible change is subtle, so model agreement with the NIH label is not guaranteed.

## Record results

Use results-template.csv to record run IDs, image patterns, report extractions, and unexpected behavior. These are manual functional tests, not diagnostic accuracy measurements.

Rebuild with `.venv/bin/python scripts/make_extended_test_pack.py` from the project directory. This overwrites generated fixture files but leaves the results sheet intact.
