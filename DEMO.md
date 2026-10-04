# TimeLens demo and test guide

## Before you present

1. Open OpenSwarm and make sure you are signed in.
2. Make sure `.env` contains `GEMINI_API_KEY=...`.
3. Start the app with `.venv\Scripts\python server.py` and open http://127.0.0.1:8765. If that port is busy, run `$env:TIMELENS_PORT=8766` first and use 8766.
4. The top card should say **Ready to compare**.

## Avoiding rate limits

- The app uses **Gemini 3.5 Flash-Lite** first. If that model is out of requests, it moves through the other Gemini models automatically.
- On a free API key, each model allows about 20 requests a day. One comparison uses 2 requests, or 3–4 with a report.
- **Running the same case again costs nothing.** The saved answer is reused. Rehearse on the same cases you will show.
- For a fresh answer on stage, either pick a case you have not run yet, or start the server with `$env:TIMELENS_RESPONSE_CACHE=0`.
- **To remove the limit completely,** turn on billing for the API key. Go to aistudio.google.com → API keys → Set up billing. It costs well under a cent per comparison.
- **Extra keys:** add keys from teammates' own Google accounts as `GEMINI_API_KEYS=key1,key2` in `.env`. Each one adds its own daily allowance.

## Three-minute demo

| Time | Show | Say |
|---|---|---|
| 0:00–0:25 | The workspace | "Doctors often compare a new X-ray with the old one, and an earlier written report can sway them. TimeLens looks at the images before it ever reads the report." |
| 0:25–1:00 | **Case D**: Compare studies, then Flicker | "Fluid on both X-rays, and the report agrees." Flick between the two images. |
| 1:00–1:30 | **Case B**: Compare studies | "These two X-rays were taken from different sides, so TimeLens refuses to compare them. That's the right answer." |
| 1:30–2:25 | **Case C**: Compare studies, live, with OpenSwarm open beside it | Show the image reviewer and report reviewer appearing in OpenSwarm. If the images and report disagree, a third agent takes one more focused look. Then open View evidence. |
| 2:25–3:00 | Wrap up | It's a second reader, not a diagnosis. Every result needs a person to review it. |

## What to test and what you should see

| # | Do this | You should see |
|---|---|---|
| 1 | Open the app | A case list on the left (Case A–E, then Pilot 01–19) and "Ready to compare". |
| 2 | **Case B** → Compare studies | Done in about a second: "Change could not be determined", explaining that the earlier X-ray was taken from the back (PA) and the current one from the front (AP). No AI calls are made. |
| 3 | **Case D** → Compare studies | After about a minute: fluid on both images. The written report card says "Sources agree" if the AI saw the fluid. |
| 4 | **Case C** → Compare studies | Images and report are reviewed separately. If the AI sees new fluid, the report card says **"Sources disagree"** and the summary mentions the second, focused look. If the AI sees no fluid, the cards agree. The NIH label for this pair is "new fluid", so that would be an AI miss. |
| 5 | **Case E** → Compare studies | "No fluid detected in either study". The second image is just an edited copy of the first. |
| 6 | Any case → Compare studies again | Instant result: the saved answer is reused and no new AI request is made. |
| 7 | While a case runs | Steps tick through: Preparing, Starting review, Reviewing images, Reviewing reports, Comparing findings, Preparing results. |
| 8 | Image controls: zoom +/−, drag, Side by side / Flicker / Swipe, full screen | Both images zoom and move together. Flicker and Swipe help spot changes. |
| 9 | **New comparison** | Upload two PNG or JPEG X-rays, tick both boxes, optionally paste a report, and save. It appears in the list, ready to compare. |
| 10 | Close OpenSwarm and reload | The top card shows that setup is needed, and Compare studies is disabled. |
| 11 | `.venv\Scripts\python -m pytest -q` and `node --test tests/test_ui_progress.cjs` | 29 passed and 1 passed. |

## Short answers for judges

- **Isn't this just AI reading an X-ray?** The image reviewer never sees the written report. Each OpenSwarm agent gets access to one task only.
- **Why several agents?** Each one sees different information. That separation is the point, and you can watch it in OpenSwarm.
- **How accurate is it?** It hasn't been clinically validated. It's a review aid, and every result needs a person.
