# TimeLens demo guide

## Before you present

1. Open OpenSwarm and make sure you are signed in.
2. Make sure `.env` contains `GEMINI_API_KEY=...`.
3. Start the app with `.venv\Scripts\python server.py` and open http://127.0.0.1:8765. If the port is busy, run `$env:TIMELENS_PORT=8766` first and use 8766.
4. The top card should say **Ready to compare**. The left list should show cases **1–4**.
5. **Rehearse all four cases once.** Their answers are saved, so on stage they appear reliably and use no new AI requests.

## Avoiding rate limits

- The app uses **Gemini 3.5 Flash-Lite** first, then moves through the other Gemini models whenever one hits its daily limit.
- One comparison uses 2 requests, or 3–5 with reports. A free API key allows about 20 requests per model per day, and the app can use several models.
- Running a case again reuses the saved answer and makes no new request. For a brand-new answer, upload a new case.
- **To remove the limit completely,** turn on billing for the API key: aistudio.google.com → API keys → Set up billing. It costs well under a cent per comparison.
- **Extra keys:** add keys from teammates' Google accounts as `GEMINI_API_KEYS=key1,key2` in `.env`.

## Three-minute demo

| Time | Show | Say |
|---|---|---|
| 0:00–0:25 | The workspace | "When doctors compare a new X-ray with an old one, the old written report can sway them. TimeLens looks at the images before it ever reads the report." |
| 0:25–1:00 | **1 · No fluid, then fluid** → Compare → Flicker | New fluid appears, and both reports agree with their own X-rays. |
| 1:00–1:20 | **3 · Front and back views** → Compare | "These X-rays were taken from different sides, so TimeLens refuses to compare them. That's the right answer." |
| 1:20–2:30 | **4 · Report disagrees** → Compare, with OpenSwarm open beside it | Image, report and second-look reviewers appear in OpenSwarm. The current report wrongly says "clear", so the card flags **Sources disagree**. |
| 2:30–3:00 | **2 · Images only**, then wrap up | It works without reports too. It's a second reader, not a diagnosis; every result needs a person to review it. |

See **TEST-CASES.md** for every test and its expected result, including the two extra upload sets.
