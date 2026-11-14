# sha_front

The frontend of sha256.fail: the qubit–Toffoli Pareto front, the leaderboard, and pages
explaining the task, how to submit and how verification works.

It is a static site built from two things in the repository: `../results/index.json`, the
receipts written by the verifier, and each submission's `README.md`, shown as its notes. It
has no other connection to the backend.

## Run it

```bash
npm ci
npm run dev
```

`npm run build` writes the site to `dist/`. Both commands first copy the receipts and the
notes into `public/data/` (`scripts/sync-data.mjs`). `npm test` runs the unit tests, which also check the site's logic
against the real results file.

## How it is put together

| File | What |
|---|---|
| `src/data.ts` | Loads receipts and turns them into leaderboard entries, and loads a submission's notes. `loadReceipts` and `loadNote` are the only functions that know where data comes from; a hosted service would change just those. |
| `src/pareto.ts` | Dominance, the frontier, ranking, record history. Pure functions. |
| `src/components/ParetoChart.tsx` | The chart: log-log axes, frontier staircase, equal-score lines, hover and keyboard tooltips |
| `src/components/Leaderboard.tsx` | The sortable table; also the chart's table view |
| `src/components/SubmissionDialog.tsx` | The popup a leaderboard row opens: a circuit's numbers, how it was verified, and its notes. Notes are submitter-written Markdown: raw HTML is not rendered, images are dropped, links are limited to web addresses. |
| `src/pages/` | Home, The task, Submit, Verification |
| `src/config.ts` | Repository URL used for links to submissions and receipts |
| `src/styles.css` | All styling, with light and dark colour tokens |

Only circuits that passed a full-strength run are shown. Where several are configurations of
one work (the same `group` in their metadata), only the best-scoring one is shown, and it
names the others in its details. A circuit is on the Pareto front
when no other circuit has at most as many qubits and at most as many Toffolis, with one of
the two strictly fewer.

React, TypeScript and Vite; `d3-scale` and `d3-array` for the chart's axes; `react-markdown`
for notes. Pages are
selected by the URL hash, so the built site works from any path without server configuration.
