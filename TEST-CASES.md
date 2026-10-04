# TimeLens test cases

The website case list shows exactly four cases: **1–4** below. The same files, plus two extra upload sets (**5** and **6**), are in the **`demo-test-cases`** folder. Every folder has a `README.txt` with the exact steps. To recreate the folder, run `.venv\Scripts\python scripts\make_test_uploads.py`.

**To upload:**
1. Click **＋ New comparison**.
2. Choose *Earlier image* and *Current image*, and set each **"Taken from"** dropdown (the file names end in `_PA` = back or `_AP` = front).
3. Open **Add written reports** and paste the text, or attach the `.txt` file.
4. Tick both boxes, click **Save comparison**, then **Compare studies**.

X-rays are public NIH images. Reports were written by us for testing.

| # | Folder / website case | Reports | What you should see |
|---|---|---|---|
| **1** | `1_no_fluid_then_fluid` · website **"1 · No fluid, then fluid"** | Earlier: *The lungs are clear. No pleural effusion.* · Current: *New small bilateral pleural effusions, more prominent on the left.* | **"Possible new fluid in the current study."** Earlier image *No fluid detected*, current image *Fluid detected*. Both cards **Sources agree**. Summary: **"Images and reports agree."** |
| **2** | `2_images_only` · website **"2 · Images only"** | none | **"Fluid is detected in both X-rays."** "Image findings only. No report attached." The Reports step shows *Skipped*. |
| **3** | `3_front_and_back_views` · website **"3 · Front and back views"** | none | Instant, with no AI used. **"Change could not be determined."** "These images were not compared. The earlier X-ray was taken from the back (PA) and the current one from the front (AP)…" When uploading, set the dropdowns to *back (PA)* and *front (AP)*. |
| **4** | `4_report_disagrees` · website **"4 · Report disagrees"** | Earlier: *Large right pleural effusion.* · Current: *The lungs are clear. No pleural effusion.* | **"Fluid is detected in both X-rays."** Earlier card **Sources agree**, current card **Sources disagree**. Summary: **"A report differs from the images. A second, focused look at the images gave the same answer."** Run details list Images, Reports and **Second look**. |
| **5** | `5_upload_set_A_fluid_both_reports_agree` (upload) | Earlier: *Bilateral pleural effusions.* · Current: *Persistent bilateral pleural effusions, similar to the prior study.* | **"Fluid is detected in both X-rays."** Both cards **Sources agree**. "Images and reports agree." |
| **6** | `6_upload_set_B_report_says_fluid_but_images_clear` (upload) | Earlier: *No pleural effusion.* · Current: *New moderate left pleural effusion.* | **"No fluid detected in either study."** Earlier card **Sources agree**, current card **Sources disagree** (the report claims fluid the images don't show). The summary mentions the second, focused look. |
| **7** | `7_should_be_rejected` | — | Each bad file gives a clear error (see its README): not an image, image too small, scanned PDF, Word file, boxes not ticked. |

**Timing:** cases with images only take about 1 minute; with reports, 1–2 minutes (longer when the second look runs). Running a case again is instant, because the saved answer is reused.

**Clean up after testing:** uploads stay in the list as "Uploaded comparison". To get back to just cases 1–4, stop the server and delete `runtime\intake.sqlite`.
