# TimeLens demo and test guide

## Before you present

1. Start OpenSwarm and confirm you are signed in (Settings → subscriptions shows Antigravity / Gemini 3.8 Flash).
2. `.env` contains `GEMINI_API_KEY=...`. **Enable billing on the key's project** (AI Studio → API keys → Set up billing). Google AI Pro does not raise API limits, and a free-tier key allows only 20 requests per model per day (one live case uses 3–4). Rehearse freely: repeated runs of the same case are served from the local cache (trace: *cached response*). For the one fresh on-stage run of Case C, set `TIMELENS_RESPONSE_CACHE=0`, or simply run a case you haven't run before.
3. Start the app: `.venv\Scripts\python server.py`, then open http://127.0.0.1:8765. If the port is busy, run `$env:TIMELENS_PORT=8766` first.
4. Refresh the cached demo results from real live runs:
   `.venv\Scripts\python scripts\build_replay.py --engine openswarm --all-demo`
5. Optional, needs about 100 Gemini calls: `.venv\Scripts\python scripts\run_eval.py`. The results then appear on the **Evaluation** page.

The connection card should say **Live**. The top bar should read *OpenSwarm connected · Gemini key set*.

## Three-minute script (from the build spec)

| Time | Show | Say |
|---|---|---|
| 0:00–0:25 | Worklist | "Readers skip priors, and prior reports anchor them. Radiology calls this *satisfaction of report*. TimeLens reads the images before it may see the report." |
| 0:25–1:00 | **Case A** → Flicker | Flick the films. Point at Reading A vs Reading B: the same films, read twice with their slots swapped. |
| 1:00–1:30 | **Case B** | *Cannot compare*: prior PA, current AP. "Refusing here is the right answer — and no model was even called." |
| 1:30–2:25 | **Case C** → *Run live in OpenSwarm* | Switch to OpenSwarm: a **Blind Reader** card and a **Report Reader** card appear in parallel, each with exactly one tool. If they disagree, an **Investigator** card makes one targeted second look. Back in TimeLens, review the result and click **Approve** or **Override**. |
| 2:25–3:00 | Evaluation / About | The limits, then the pitch line. |

## What to test, and what you should see

| # | Do this | Expected output |
|---|---|---|
| 1 | Open the app | Demo worklist sorted: Disagreement → Cannot compare → Unstable → Image only → Agrees. Each item shows a status and, if cached, *replay*. |
| 2 | Click **Case B** | Hero "These films cannot be compared reliably", with the projection-mismatch reason. Trace shows all three agents *skipped gate failed*: zero model calls. |
| 3 | Case B → **Run live** | Finishes in about a second with *Cannot compare*. No OpenSwarm agent is launched. |
| 4 | **Case C** → **Run live in OpenSwarm** | Progress stages: gate ✓ → launching → Blind Reader → Report Reader → (Investigator) → status. OpenSwarm shows sessions named *TimeLens · Blind Reader · Case C…* and *TimeLens · Report Reader · Case C…*. |
| 5 | When Case C completes | One of: **Disagreement** (blind read sees new fluid; the synthetic report says none; the Investigator re-checked), **Agrees** (the reader missed the effusion, which the NIH reference label in *Source, provenance* reveals), or **Unstable read** (the two slot orders disagreed). All three are honest outcomes. The report quote is highlighted, and the trace lists each agent's session ID, tool, time, model and tokens. |
| 6 | **Case E** | The near-duplicate control should be *Image only · absent*. A "new" call would be an over-call. |
| 7 | **Approve** / **Escalate** | The sign-off line updates with time and source (live or replay). The worklist item shows the action. |
| 8 | **Override…** with "no" | Rejected: "An override needs a reason of at least five characters." |
| 9 | Image desk: Zoom +, drag, Sync, Flicker, Swipe | Synced pan/zoom across both films. Flicker alternates every 0.7 s. The swipe slider reveals earlier/current. |
| 10 | Rail → **Pilot** | 19 NIH pilot pairs. Run any of them **headless** to see the same tools without agents. |
| 11 | **New comparison** | Upload two PNG/JPEGs and set the views to PA and AP → the case is gated *Cannot compare*. Set PA/PA plus a pasted report → a normal run. |
| 12 | Stop OpenSwarm, reload | The badge reads *Headless only*. Live runs return a clear 503 message; headless still works. |
| 13 | `.venv\Scripts\python -m pytest -q` | 25 passed. |

## Statuses

| Status | Meaning | Clinician action |
|---|---|---|
| Disagreement | A stable blind read contradicts the report, even after one reassessment | Review first |
| Cannot compare | The gate failed (AP vs PA, identical files), or the reader abstained | Read manually |
| Unstable read | The answer flipped when the films swapped slots | Read manually |
| Image only | No report, or no definite report claim | Read the result |
| Agrees with report | The blind read matches the report | Spot-check |

## Judge Q&A, short answers

- **Isn't this just an LLM looking at X-rays?** The reader is structurally blind to the report: its MCP connector exposes one tool, and the report text never reaches it.
- **Why several agents?** Each sees different information. Blinding is enforced by what each tool can access, and the evaluation compares against one strong prompt (condition B).
- **How accurate?** A pilot of 19 pairs, roughly ±20 points. It is a review aid, not a diagnosis.
- **Why OpenSwarm?** Visible agents, per-agent tool restriction, and a canvas the clinician can watch. Every connector is per-run and deleted afterwards.
