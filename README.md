# TimeLens

**A second-reader worklist for follow-up chest X-rays that reads the images before it is allowed to see the report.**

TimeLens targets two named radiology error types (Kim–Mansfield): *type 7, prior examination error* (the current film is read without the prior) and *type 12, satisfaction of report* (an earlier report anchors the read). Every case is a prior + current pair. The image reader cannot access any report. Disagreements rise to the top of the worklist for clinician sign-off. Pleural effusion only. Research prototype — not for clinical use.

## Run it (Windows)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
# .env (Git-ignored) must contain: GEMINI_API_KEY=...
.venv\Scripts\python server.py
```

Open http://127.0.0.1:8765. If port 8765 is taken, set `TIMELENS_PORT=8766` first. For live agent runs, the OpenSwarm desktop app must be running and signed in (its token is discovered automatically). Without OpenSwarm, cases still run with the **headless** engine. Without a key, cached **replays** still display.

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | — | Direct Gemini calls made inside the MCP tools |
| `TIMELENS_GEMINI_MODEL` | `gemini-3.5-flash` | Vision/text model |
| `TIMELENS_GEMINI_FALLBACKS` | `gemini-3.7-flash,gemini-3.6-flash,gemini-3.8-flash` | Used only on 429/503 capacity errors; the model that answered is shown in the trace |
| `TIMELENS_OPENSWARM_MODEL` | `gemini-3.8-flash` | Model that drives the OpenSwarm agents |
| `GEMINI_API_KEYS` | — | Optional comma-separated pool (keys from different Cloud projects), rotated on 429 |
| `TIMELENS_RESPONSE_CACHE` | `1` | Identical requests reuse the stored answer (trace shows *cached response*); set `0` for a fresh live call |
| `TIMELENS_PORT` | `8765` | Local port |

## Rate limits

Google AI Pro (the consumer Gemini subscription) does **not** apply to the Gemini API. An API key whose Cloud project has no billing is on the free tier: **20 requests per model per day**. One live case uses 3–4 requests and the evaluation about 100. Fix: in AI Studio → API keys, **set up billing** on the key's project (Tier 1, about a fraction of a cent per case). Mitigations built in: a key pool (`GEMINI_API_KEYS`), model fallbacks, a local response cache, and cached replays.

## How a case is investigated

1. **Comparability gate** (server code, before any model call). AP-vs-PA projection mismatch or byte-identical files → *Cannot compare*.
2. **Blind Reader** (OpenSwarm agent → `read_pair`). Two independent Gemini reads, with the films' slots swapped and chronology withheld. Positions are mapped back in code. If the answers differ → *Unstable read*.
3. **Report Reader** (OpenSwarm agent → `read_reports`, in parallel). Sees report text only. Every supporting quotation is verified verbatim in code.
4. **Investigator** (OpenSwarm agent → `reassess`). Runs only if the stable blind read contradicts the report: one targeted, still report-blind second look, enforced once per run by the server.
5. **Status** (`verdict.py`, plain Python). The statuses are *Disagreement*, *Cannot compare*, *Unstable read*, *Image only* and *Agrees with report*.
6. **Sign-off.** A clinician approves, overrides (a reason is required) or escalates. Each action is logged in SQLite.

Each agent gets a fresh per-run MCP connector exposing exactly **one** no-argument tool. The MCP server rejects cross-role calls. Image bytes and report text never enter OpenSwarm prompts: the tool sends them straight to Gemini and returns only structured findings. The run's stage table is the shared blackboard between agents. Connectors and modes are deleted when each agent finishes. The headless engine (`direct_workflow.py`) calls the same tools without agents.

| File | Role |
|---|---|
| `server.py` | FastAPI worklist/review API, sign-off log, replay and evaluation endpoints |
| `pipeline.py` | One investigation, shared by both engines |
| `openswarm_workflow.py` / `direct_workflow.py` | OpenSwarm agent engine / headless engine |
| `analysis_mcp.py` | Run-bound, role-restricted MCP tools |
| `gemini_direct.py` | Tool-free Gemini calls (swapped blind read, reassessment, report extraction, eval baselines) |
| `verdict.py` / `cases.py` | Status rules / case catalog and comparability gate |
| `static/` | Web UI (worklist rail, image desk with sync/flicker/swipe, review, sign-off, Evaluation, About) |

## Data

NIH ChestX-ray14 (public, de-identified). Labels, views and follow-up order come from `data/nih/Data_Entry_2017_v2020.csv`. `scripts/fetch_nih_cases.py` streams only the 37 needed films from NIH's archive; `scripts/build_cases.py` writes `data/cases.json`. NIH labels are report-mined and noisy. They are shown as *reference* labels and never enter a model prompt.

Demo slots: **A** new effusion (PA→PA) · **B** AP vs PA (expected *Cannot compare*) · **C** same films as A with a synthetic report that misses the effusion · **D** persistent effusion with an agreeing synthetic report · **E** near-duplicate control (cropped/brightened copy). The pilot set has 19 pairs: 16 PA→PA (4 per label) and 3 AP-vs-PA.

## Replay and evaluation

```powershell
.venv\Scripts\python scripts\build_replay.py --engine openswarm --all-demo   # cache demo results (Replay tag)
.venv\Scripts\python scripts\run_eval.py                                     # Evaluation page data
.venv\Scripts\python -m pytest -q
```

## Limits

- Small pilot: behaviour, not accuracy (roughly ±20 points).
- Gemini readings vary between runs. The order-swap check exists to surface that variance.
- No PACS, login or authenticated reviewer identity.
- OpenSwarm still exposes built-in tools at session level. The data boundary is enforced by keeping raw inputs inside the MCP tools.
- `reference/original` is archival source; do not run it.
