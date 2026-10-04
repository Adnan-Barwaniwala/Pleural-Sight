# TimeLens

Local chest X-ray comparison research prototype. The workflow compares pleural-effusion presence across two studies and optionally checks uploaded reports. Every result requires human review; the four demo pairs are not an accuracy evaluation.

## Run locally

```sh
cd "/Users/Adnan/Documents/ChatGPT/College Work/timelens"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

Before starting, either export `GEMINI_API_KEY` or place `GEMINI_API_KEY=...` in the Git-ignored `.env` file. Open http://127.0.0.1:8765. The server binds to loopback only. Uploaded images, reports, run manifests and results persist under `runtime/`; the directory is Git-ignored but not encrypted. Use permitted, de-identified research data. The key is never returned to the browser or written by TimeLens.

The local OpenSwarm app must also be running and connected to the user's Gemini account. `TIMELENS_OPENSWARM_MODEL` optionally changes the agent model and defaults to `gemini-3.8-flash`.

`TIMELENS_GEMINI_MODEL` optionally changes the model; it defaults to `gemini-3.5-flash`, which was the newest explicitly versioned Flash endpoint that passed the live availability check on October 3, 2026. The key can access 3.8, but Google returned temporary high-demand errors for every 3.8 request during validation. A Gemini subscription is separate from Gemini API access and quota.

## Implemented

- Fresh shared source reference, Drive IDs and SHA-256 manifest, with shared secrets/logs excluded.
- Seven unchanged NIH PNGs and provenance; four demonstration pairs, three patients.
- Responsive dark comparison viewer using the requested Frontend Design, UI/UX Pro Max and Apple Design skills.
- Case selection and reload persistence, original image links, report scope and provenance.
- Local PNG/JPEG upload with decoding, dimensions and size checks; pasted/TXT/text-PDF report ingestion; same-patient/chronology confirmations.
- Persistent SQLite intake storage, cross-origin write protection, local-only serving, no external assets.
- Cross-platform OpenSwarm token discovery and an official-MCP-SDK nonclinical acceptance probe.
- Required two-agent OpenSwarm orchestration with visible, fresh Image Analyst and Report Reader sessions. The Report Reader is skipped when there is no report.
- Per-run, role-specific MCP connectors: each exposes exactly one no-argument tool and is removed after the agent reaches a terminal state.
- The MCP worker sends image bytes or scoped report text directly to an independent Gemini call. Raw inputs and API keys never enter OpenSwarm prompts or agent workspaces.
- Concurrent image/report agents, exact report-quote validation and deterministic temporal comparison in backend code. There is no Investigator or Reassessment agent.
- Background queued/running/comparing/complete/failed states, immutable MCP stage storage, model/timing/session traces and result restoration after reload.

## Why images do not pass through OpenSwarm

The installed OpenSwarm API lists `gemini-3.8-flash`. The nonclinical session resolved to provider `gemini-cli`, lane `antigravity`.

Created only these TimeLens-owned test objects:

- Connector: `timelens-probe-3267c919`, ID `587f47a63dfd4bcc8890df981a5a57a4`.
- Mode: `8b859f4e5e8349eda04ff79019b48616`.
- Session: `64e9e4bc9dae46cda2cb9964bf931713`.

The registration is repaired using OpenSwarm's supported state for a local no-auth MCP: `auth_type=none`, `auth_status=configured`. OpenSwarm also requires a server-level allowlist marker (`mcp:timelens-probe-3267c919`) in addition to individual tool names. The connector now activates and both custom tools execute.

The original OpenSwarm image-transport experiment failed:

- Standard MCP image blocks were dropped before Gemini: it saw only `Image 1` and `Image 2` labels.
- The restricted session exposed the general `Read` tool. A deliberately authorized denial probe successfully read the harmless sentinel, proving this is not an enforceable filesystem boundary.
- A fallback using `Read` did transmit two nonclinical image files, but Gemini swapped their known color/shape identities. That route is not sufficiently reliable for prior/current medical-image identity.

Do not change global OpenSwarm built-in permissions to work around this: those settings affect unrelated chats. The implemented architecture makes OpenSwarm the required orchestrator while keeping raw inputs inside role-bound MCP workers. OpenSwarm invokes the tools and receives structured text results; it does not transport image pixels or enforce the data boundary.

The probe script reuses the TimeLens-owned connector and mode, updates their supported configuration, and creates a fresh test session. Existing test sessions are retained as evidence.

## Current limits

Human accept/edit/escalate actions, cancellation, explicit failed-stage recovery and authenticated reviewer identity are not implemented. An interrupted or failed paid model stage is intentionally not retried automatically; a new run preserves the earlier failure. OpenSwarm still exposes its built-in tools at the session level, so TimeLens keeps raw inputs and manifest paths out of prompts/workspaces and treats only persisted MCP results as authoritative.

The shared document's audit script, 60-patient manifest and 15-test decision contract were not provided. Do not describe these as included or passing. `reference/original` is archival source; do not run its setup/server scripts as the current app.

## Validation

```sh
.venv/bin/python -m pytest -q
node --check static/app.js
```

Nineteen automated tests pass, including distinct labeled image payloads, invalid report-quotation rejection, deterministic comparison, MCP caller-input denial, cross-role denial, role-specific connector configuration, concurrent agent launch, no-report skipping, required-OpenSwarm failure behavior, run persistence and reload restoration. JavaScript syntax and Git whitespace checks pass.

Live acceptance passed on October 3, 2026. A public no-report NIH case completed through one visible OpenSwarm Image Analyst session with the Report Reader recorded as skipped. A synthetic-report case completed through separate visible Image Analyst and Report Reader sessions, produced one successful role tool call each, validated the exact quotation and returned report/image agreement. Temporary connectors and modes were absent after both runs. These are engineering checks, not diagnostic validation.
