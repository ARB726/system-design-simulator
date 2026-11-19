# Project walkthrough

Open the guest demo with **Try without signing in**, then expand **Watch the 75-second walkthrough**. The player loads the video on demand and includes controls, English captions and a written transcript. It does not require audio, authentication or model calls.

The video is a captioned slideshow of five views captured from the actual application. The data comes from the Python/SimPy engine at 500 offered requests/s, seed 7, two database connections and 15 simulated seconds. Only the read cache changes between baseline and candidate. The interactive guest fixture uses 120 offered requests/s, so its measurements differ from those in the video.

The sequence covers an overloaded baseline, database pressure, the cached candidate, measured comparison deltas and read-only sharing. Simulated resource cost is illustrative. One paired synthetic run does not establish production capacity, causal certainty or real hosting costs.

## Reproduce the asset

Install the frontend and backend dependencies using the repository setup instructions. Create `.local` if it does not exist. From the repository root:

```text
python tools/build_guest_demo.py --rps 500 --output .local/walkthrough-fixture.json
```

Start the frontend development server on port 8080 in another terminal. Install Playwright's official FFmpeg helper from the frontend directory with `node node_modules/playwright/cli.js install ffmpeg`, then pass its executable path to the recorder:

```text
node tools/record_walkthrough.cjs .local/walkthrough-fixture.json <ffmpeg-executable-path> http://127.0.0.1:8080
```

The recorder uses Chrome by default. Set `PLAYWRIGHT_CHANNEL=chromium` when using Playwright's installed Chromium instead. It intercepts the guest fixture and public settings/catalog calls, captures five captioned UI views and encodes each for 15 seconds. It checks that the baseline has failed requests and the candidate improves success. It does not submit jobs to a live backend.

Outputs are `fullstack/frontend/public/walkthrough.webm` and `walkthrough-poster.jpg`. Review frames in `.local/walkthrough-frames` before committing. The matching captions are in `walkthrough.vtt`; update the player transcript and captions if the story changes.

From the frontend directory, run `npm run test:e2e -- tests/walkthrough.spec.ts` against the local application. The test verifies playable media, a 60–90 second duration, captions and transcript access. Include the generated assets in the normal static production build.

## Read-only links

Completed simulations and guest samples offer **Share read-only snapshot**. Inspect the visibility notice before creating a link. The link includes the experiment name, allowlisted configuration and measurements, up to 40 timeline samples and 50 histogram buckets. It excludes private owner identifiers, login tokens and AI conversations.

Anyone holding a link can inspect its contents. Links cannot be revoked and the embedded data can be edited, so recipients see an **Unverified shared snapshot** notice. Opening a link does not run an experiment, mutate the original or make protected API calls.
