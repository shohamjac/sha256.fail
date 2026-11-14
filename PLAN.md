# sha256.fail — plan

Date: 2026-11-14. Supersedes `preplan_codex.md` (see §10 for what I kept and what I changed).

Goal: a public benchmark for quantum circuits that compute SHA-256, verified with Google's
Kickmix simulator, with a qubit–Toffoli Pareto front and leaderboard in the style of ecdsa.fail.

## 1. Decisions

### Decided (by you, 2026-11-14)

| # | Decision | Choice |
|---|---|---|
| D1 | Headline task | One SHA-256 compression: 512-bit quantum block, standard IV, 256-bit digest out |
| D2 | Random test inputs | N = 2^20 = 1,048,576 per official run, zero failures allowed |
| D3 | Hash functions | SHA-256 only at launch; verifier is generic over a table of problem specs |
| D4 | Hosting | Git PRs + CI + static site now; hosted service (ecdsa.fail-style) later, so design for it |
| D5 | Layout | `sha256_verifier/` (backend), `sha_front/` (frontend), `submissions/example/` |
| D6 | Output register | Starts at \|0⟩, ends holding the digest. Behaviour on a non-zero `digest` register is unspecified and untested, so circuits may use those 256 qubits as workspace. |

| D15 | Name | sha256.fail (domain availability not checked) |
| D16 | Literature results | No unverified markers on the chart. A published construction appears only once it has been rebuilt as a Kickmix circuit for this contract and passed the verifier like any other submission. Deferred until after launch. |

### My defaults — say so if you disagree

| # | Decision | Default | Why / alternative |
|---|---|---|---|
| D7 | Gate set | Everything Kickmix has except `Z_POW`: X, CX, CCX, SWAP, CSWAP, Z, CZ, CCZ, NEG, HMR, R, classical bits, conditioned gates | Codex proposed X/CX/CCX/SWAP only. That forbids measurement-based uncomputation, which roughly halves Toffoli counts and is what Kickmix's own adder uses. Kickmix simulates it natively. |
| D8 | Toffoli metric C | Mean executed CCX + CCZ + CSWAP per shot, as Google and ecdsa.fail do | Static count is also recorded. They differ only when a Toffoli sits under a classical condition. |
| D9 | Qubit metric Q | `circuit.num_qubits` = highest qubit index + 1 | Checked: `X q5000` alone gives 5001, so sparse numbering cannot hide qubits. |
| D10 | Score | Q × C shown as a ranking column; the Pareto front is the main view | Same as ecdsa.fail. |
| D11 | Submission artifact | A circuit file (`.kmb` or `.kmx`), never code | The verifier must not execute submitter code. ecdsa.fail runs contestant Rust and needs a bubblewrap sandbox for it. |
| D12 | Seed | SHA-256(domain ‖ circuit hash ‖ salt). Local runs: empty salt. Official runs: fresh random salt drawn by CI, published in the receipt | Unpredictable before, reproducible after. See §4.3. |
| D13 | Frontend stack | Vite + React + TypeScript, static build, D3 for the chart | One `loadResults()` function is the only place that knows data comes from a JSON file, so the hosted version swaps it for an API call. |
| D14 | Licence | Apache-2.0 | Matches Kickmix and Google's verifiers. |

### Still open

- Which published constructions to rebuild first (candidates: Amy et al. 2016, Kim et al. 2018,
  Lee et al. 2023). Each is its own circuit-building job; a paper's reported counts may not be
  reproduced exactly, since its contract and gate set can differ from ours.
- Second instance after launch: SHA-512, SHA3-256, or Bitcoin double-SHA (§8).

## 2. What I checked (facts, not assumptions)

Local Kickmix 0.1 binary from the Kaggle competition (`google_quantum_kaggle/official/kickmix`):

- **Speed.** A random 1M-gate circuit on 2,500 qubits: 65,536 shots in 2.8 s on one core, so
  2^20 shots ≈ 45 s on one core. This machine has 128 cores. Test count is not limited by compute.
- **Adder cost.** `CircuitBuilder.iadd` on 32 bits: 31 CCX, 30 HMR, 30 R, 94 qubits total
  (measurement-based uncomputation).
- **Dirty resets are caught probabilistically.** `R` or `HMR` on a qubit in |1⟩ with no fixup
  flips the phase in ~46% of shots. A conditional `R` whose condition is false leaves the qubit
  dirty (so the scratch check catches it).
- **Input validation.** Kickmix rejects aliased operands (`CCX q0 q0 q1`) and unknown gates.
  It accepts `Z_POW` and conditional `R`/`HMR`, so our own allowlist is needed.
- **Portability.** The `.so` is x86-64 Linux, AVX2, needs GLIBCXX_3.4.32 (needed `LD_PRELOAD` of
  the system libstdc++ here).
- **Source and release.** Kickmix lives in `quantumlib/Qualtran` under `kickmix/` and is
  published on PyPI as `kickmix 1.0.0`, built from the signed tag `v1.0.0-kickmix`
  (commit `e8e4971bf44a`, Craig Gidney, 2026-10-27). The PyPI wheel runs here without
  `LD_PRELOAD` and has the same API as the Kaggle binary. Its `km.__version__` still says
  `0.1`, so the verifier reads the version from the package metadata.

From the web (read by sub-agents; I did not see the live ecdsa.fail chart — it is a JS app and
Chrome was not connected):

- ecdsa.fail: 9,024 random points, seed = SHAKE256 of the op stream (no salt), score =
  mean executed Toffoli × qubits, simulator is vendored Rust reading the Kickmix text format.
  Its NOTICE mentions hardening against operand aliasing, conditional R/HMR, and a malformed
  binary file that bypassed the Toffoli counter in Google's challenge.
- Google's paper (arXiv:2610.23832): seed = SHA-256 of the `.kmb` bytes plus a private salt;
  zero failures in N shots bounds the failure rate by ≈ 88.7/N at confidence 1 − 2^-128.
- `tatra-labs/kickmix-arena` on GitHub describes itself as an open arena for cheaper Kickmix
  circuits. Not read; worth a look before building the frontend.

## 3. The benchmark contract (problem `sha256-compress-v1`)

Registers (names and sizes are checked; no others allowed):

- `block` — 512 qubits. Must be restored.
- `digest` — 256 qubits. Starts |0⟩, must end equal to `compress(IV, block)` including the
  final feed-forward addition. For any message of ≤ 55 bytes, this equals its SHA-256 digest
  when `block` holds the padded message.
- Every other qubit is scratch: starts |0⟩, must end |0⟩.
- Phase: no shot may end with a flipped phase.

Bit order (frozen in M1): `block[32j + k]` is bit k (LSB = 0) of message word W_j;
`digest[32j + k]` is bit k of H_j; words are big-endian over bytes as in FIPS 180-4.
The full contract, with test vectors, is `sha256_verifier/docs/sha256-compress-v1.md`.

Pass = structural checks + all directed tests + all 2^20 random shots correct.

## 4. Backend — `sha256_verifier/`

A Python package and CLI. No knowledge of leaderboards or websites.

```
sha256_verifier/
  pyproject.toml
  src/sha_verifier/
    problems.py     # registry: name -> ProblemSpec(registers, reference fn, directed tests)
    sha2.py         # vectorized numpy SHA-2 compression (SHA-256 and SHA-512 parameters)
    bits.py         # words <-> register bit arrays
    validate.py     # allowlist, register schema, independent op walk
    simulate.py     # batched Kickmix runs, multiprocess, checks
    sampling.py     # seed derivation, input generation
    receipt.py      # result JSON + schema
    cli.py          # sha-verify run | collect | selftest
  schema/result.schema.json
  tests/
```

### 4.1 Reference function

`hashlib` cannot be used directly: it always pads, and the task is a raw compression. So the
reference is our own numpy implementation over `uint32` arrays (also needed for 2^20 inputs at
once). It is validated against `hashlib` three ways: full digests at every message length
across three blocks; one compression of every single-block padded length (0–55 bytes); and
raw random blocks, using the fact that hashing a 64-byte message compresses that block
unpadded and then a fixed padding block. The FIPS 180-4 example digests are pinned too. Its
round constants are derived from the primes rather than typed in. The baseline circuit
generator must not import it — the two are written separately so one bug cannot make both
agree.

### 4.2 Checks, in order

1. **Load and canonicalize.** Parse the file, re-serialize to canonical `.kmb`, hash that.
2. **Structural.** Register names/sizes/distinctness; gate allowlist (reject `Z_POW`); size
   limits (ops, qubits, file bytes). An independent pure-Python walk of the `.kmx` text
   recomputes qubit count and static gate counts and must agree with Kickmix's own numbers —
   this is the defence against a crafted file fooling the counter.
3. **Directed tests** (1,179 shots, frozen in M1): constant patterns, each single bit set
   and clear, carry-heavy words, and padded messages of every length 0–55.
4. **Random tests.** 2^20 uniform 512-bit blocks, one shot each, batch 256, chunks spread over
   cores. Each shot uses a fresh input and fresh measurement outcomes, which is exactly the
   joint sample Google's bound is stated for. No "repeats per input".
5. **Per shot:** `digest` equals reference; `block` restored; all scratch zero; phase not
   flipped (vector read via `read_phase_flipped_across_shots`).
6. **Counts.** Mean executed Toffoli-like per shot from the simulator; static counts,
   reaction depth, op count.

### 4.3 What passing means, and seeds

- Zero failures in 2^20 shots certifies failure rate < 8.5 × 10^-5 at confidence 1 − 2^-128
  (< 2.9 × 10^-6 at 95%). It is not a proof of exactness, and there is no separate "exact
  track": a circuit wrong on 1 input in 10^7 passes 90% of the time, 1 in 10^6 passes 35%,
  1 in 10^5 essentially never. N *is* the approximation tolerance. I would state this on the
  site rather than hide it.
- A phase bug that shows up in a fraction f of inputs is caught per shot with probability f/2.
- Seed grinding: if the seed depended only on the circuit, a submitter could add no-op gates
  and retry until a slightly-wrong circuit passes. The per-run CI salt (D12) removes that;
  resubmission through CI is the only retry path and is rate-limited by PR review. The receipt
  records the salt so anyone can replay the exact run.

### 4.4 Receipt (the only interface to the frontend)

One JSON per run, validated against `schema/result.schema.json`:
problem id, status, failure detail, circuit SHA-256, Q, C (mean executed), static Toffoli,
reaction depth, op count, shots, directed-test count, salt, seed, verifier version, Kickmix
version/hash, timestamp, and submission metadata (name, authors, description, links).
`sha-verify collect` concatenates receipts into `results/index.json`. No ranking logic here.

### 4.5 Verifier self-tests (mutation tests)

A fixed set of deliberately broken circuits that must all be rejected: one wrong output bit,
block not restored, dirty scratch, dirty `HMR` without fixup, stray `NEG`, extra register,
wrong register size, `Z_POW` present, conditional `R` leaving dirt, a rare-failure circuit
(wrong on ~1% of inputs), aliased operands. Runs in CI on every change to the verifier.

### 4.6 Kickmix dependency

Settled in M0: depend on `kickmix==1.0.0` from PyPI, with wheel hashes pinned in `uv.lock`
and CI installing with `uv sync --locked`. No source build or vendored binary. Every receipt
records the Kickmix version and the SHA-256 of the loaded binary.

## 5. Submissions — `submissions/`

```
submissions/
  example/
    circuit.kmb       # the artifact that is verified
    meta.json         # name, authors, description, problem id, kind, optional links
    build.py          # optional: how the circuit was generated (never run by CI)
    README.md
  <team>-<name>/ ...
results/
  sha256-compress-v1/<circuit_sha256>.json
  index.json
```

`submissions/example/` is where the baseline circuit will be built (next phase, after this
plan). Rough expectation for a straightforward baseline — in-place message schedule, reversible
round function, compute/copy/uncompute, Kickmix's adder — is on the order of 1,100–1,300 qubits
and a few tens of thousands of Toffolis. That is my estimate, not a measurement.

PR flow: a PR adds one directory under `submissions/`. CI (GitHub Actions, no secrets, no
network during verification) checks that the PR touches only that directory, runs
`sha-verify run`, commits the receipt to `results/`, comments Q / C / Q×C and whether the point
is on the frontier. Merging to `main` triggers the site build. Failed runs are recorded too.

## 6. Frontend — `sha_front/`

A separate project that reads `results/index.json` and nothing else.

- **Pareto chart.** Qubits vs Toffolis, log-log. Verified points; the nondominated set joined
  as a staircase; dominated points greyed; faint iso-score (Q×C = const) guide lines; hover
  for details, click to open the submission. Every point is a verified circuit; points are
  styled by `kind` (baseline, literature reconstruction, submission) from `meta.json`.
  A dominates B when Q_A ≤ Q_B and C_A ≤ C_B with at least one strict. Computed client-side.
- **Frontier progress.** Best Q×C over time and a date slider that replays the frontier
  (ecdsa.fail labels this "Frontier Progress").
- **Leaderboard.** Sortable table: rank by Q×C, name, authors, Q, C, Q×C, reaction depth,
  date, frontier badge, links to the submission directory and its receipt.
- **Pages.** Rules/contract, how to submit, what verification does and does not guarantee.
- **Problem switcher** keyed on problem id, hidden while there is only one.
- Deployed as static files (GitHub Pages) from CI on `main`.

## 7. Designing for the later hosted service

Things done now so the move is additive, not a rewrite:

- The verifier is a library with a pure function `verify(circuit_bytes, problem, salt) → receipt`;
  the CLI and CI are thin wrappers, and a queue worker would be another.
- The receipt schema is versioned and is the storage format in either world (file now, DB row later).
- The frontend's data access is one function; static JSON now, API later.
- Submissions are data, not code, so workers need resource limits but not a code sandbox.
- Identity is a `meta.json` field now (GitHub handle); becomes an account later.

Deferred to that phase: API, auth, upload CLI, database, object storage, rate limits, terms.

## 8. Other hash functions

Adding one is: a `ProblemSpec` entry (registers, reference function, directed tests) + a
baseline circuit + its own leaderboard. Verifier cost is small each time; the circuit is the work.

| Variant | Verifier work | Baseline circuit work | Note |
|---|---|---|---|
| SHA-224 | trivial | trivial | Different IV, truncated output. Low interest. |
| SHA-512 / 384 | small (uint64 reference) | moderate | Same structure, 64-bit words, 80 rounds. Natural second instance. |
| SHA3-256 (Keccak-f[1600]) | small | new design | No adders, only AND layers; a different optimization game. |
| SHA-256d / Bitcoin header | small | 3× compression + plumbing | Best "headline", needs a decision on which header bits are quantum. |

## 9. Milestones

| # | Milestone | Done when |
|---|---|---|
| M0 | Repo skeleton, `git init`, Kickmix pinned from PyPI, toy circuit runs in CI | `sha-verify selftest` passes on a clean Ubuntu runner |
| M1 | Contract frozen: registers, bit order, reference function, directed tests | Reference matches `hashlib` on all 56 single-block lengths and NIST vectors |
| M2 | Verifier: validation, simulation, sampling, receipts | Mutation suite (§4.5) all rejected; identical salt replays identical receipt |
| M3 | Baseline circuit in `submissions/example/` | Passes the full 2^20 official run; first point on the chart |
| M4 | Frontend with Pareto chart, leaderboard, rules pages | Renders `results/index.json` with ≥ 3 points (baseline + variants) |
| M5 | PR-based CI flow and site deploy | An external-style PR gets verified, commented, and appears on the site after merge |
| M6 | Literature reconstructions as verified circuits under `submissions/literature-*/` | Each passes the official run and appears on the chart tagged `literature` |
| M7 | Second instance and/or hosted service | Separate plan |

M2 and M4 are independent once the receipt schema exists (end of M1), so the two projects can
be built in parallel. M3 can be developed against M2 as it comes together.

## 10. What I changed from `preplan_codex.md`

Kept: the overall pipeline, Fiat-Shamir seeding with a post-commitment salt, receipts, the
dominance rule, the insistence on separate frontiers per task, the reference/generator
independence rule.

Changed:

- **Task.** Codex proposed fixed 32-byte messages; you chose the full 512-bit block.
- **N.** 65,536 → 2^20, since measured cost is seconds.
- **No exact/approximate split.** Codex's "exact main track" cannot be delivered by sampling;
  N sets the tolerance (§4.3). Its approximate-track section (tiers, Grover analysis) is dropped
  from v1.
- **No profile matrix or repeats per input.** One shot per fresh input.
- **Gate set.** Measurement-based uncomputation allowed from day one (D7).
- **Output register.** Zero-initialised rather than arbitrary `y` (D6, confirmed by you).
- **No SQLite.** Receipts as JSON files in git are the store.
- **No forward-then-inverse check.** It adds nothing to the four checks and is undefined for
  circuits with measurements.
- **Added:** `hashlib` cannot be the reference for raw compression; the independent op-walk
  against file-format attacks; the mutation suite; measured throughput; Kickmix source location
  and binary platform limits; the backend/frontend/submissions split.
