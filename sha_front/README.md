# sha_front

The frontend of sha256.fail: for each problem the qubit–Toffoli Pareto front and the
leaderboard, and pages explaining the tasks, quantum Bitcoin mining, how to submit and how
verification works.

It is a static site built from three things in the repository: `../results/index.json`, the
receipts written by the verifier; each submission's `README.md`, shown as its notes; and the
figures of the Bitcoin mining contract in `../sha256_verifier/docs/img/`. It has no other
connection to the backend.

## Run it

```bash
npm ci
npm run dev
```

`npm run build` writes the site to `dist/`. Both commands first copy the receipts, the
notes and the figures into `public/data/` (`scripts/sync-data.mjs`). `npm test` runs the unit tests, which also check the site's logic
against the real results file.

## How it is put together

| File | What |
|---|---|
| `src/data.ts` | Loads receipts and turns them into leaderboard entries, and loads a submission's notes. `loadReceipts` and `loadNote` are the only functions that know where data comes from; a hosted service would change just those. |
| `src/pareto.ts` | Dominance, the frontier, ranking, record history. Pure functions. |
| `src/components/ParetoChart.tsx` | The chart: log-log axes, frontier staircase, equal-score lines, hover and keyboard tooltips |
| `src/components/Leaderboard.tsx` | The sortable table; also the chart's table view |
| `src/components/SubmissionDialog.tsx` | The popup a leaderboard row opens: a circuit's numbers, how it was verified, and its notes. Notes are submitter-written Markdown: raw HTML is not rendered, images are dropped, links are limited to web addresses. |
| `src/pages/` | Home, The tasks (one summary per problem), Quantum Bitcoin mining, Submit, Verification |
| `src/problems.ts` | Which problem is shown, kept in the URL (`?problem=`) so that it carries between pages. `src/tracks.ts` does the same for the track. |
| `src/config.ts` | Repository URL used for links to submissions and receipts; the problems the site knows, in the order it offers them (the first is the default) |
| `src/styles.css` | All styling, with light and dark colour tokens |

Only circuits that passed a full-strength run are shown. Where several are configurations of
one work (the same `group` in their metadata), only the best-scoring one is shown, and it
names the others in its details. A circuit is on the Pareto front
when no other circuit has at most as many qubits and at most as many Toffolis, with one of
the two strictly fewer.

React, TypeScript and Vite; `d3-scale` and `d3-array` for the chart's axes; `react-markdown`
for notes. Pages are
selected by the URL hash, so the built site works from any path without server configuration.
