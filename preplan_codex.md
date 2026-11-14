# SHA quantum-circuit verifier: pre-plan

Date: 2026-11-14  
Project: /home/shoham/projects/sha-256-verifier  
Status: planning document; records the discussion, agreed requirements, proposed defaults, and unresolved choices.

## 1. Goal and agreed direction

Build a verifier for reversible quantum circuits implementing SHA-256, based on Google's open-source Kickmix circuit simulation and verification approach. Provide reproducible evaluation results and an interactive qubit–Toffoli Pareto front inspired by ecdsa.fail.

"SHA-265" in the initial request is understood to mean SHA-256.

The user confirmed the central policy:

> The main track targets exact SHA semantics, qualified by 65,536 verification tests.

Operationally, a qualifying main-track submission must produce zero observed failures on 65,536 fresh random verification inputs, plus the directed checks defined by the benchmark. It must preserve its inputs, implement the specified output transformation, clean its scratch qubits, and satisfy phase requirements.

This is a sampled verification result, not a proof of correctness for all inputs. Results must identify the verification profile and avoid presenting a sampled pass as universal equivalence.

Other settings in this document are recommendations unless explicitly identified as agreed. In particular, the initial message length, launch algorithms, circuit tasks, measurement support, and public hosting scope remain choices.

## 2. Proposed launch configuration

| Decision | Proposed default | Alternatives and implications |
|---|---|---|
| Headline algorithm | SHA-256 | Other SHA-2 algorithms can share infrastructure; SHA-3 needs a separate circuit core |
| Main-track correctness | Exact target semantics; zero observed failures | Confirmed by user; approximate solutions use separate tracks |
| Qualification sample size | 65,536 fresh random inputs plus directed checks | Confirmed main-track sample size; larger audits strengthen evidence |
| Circuit task | Full hash XOR oracle | Compression and Grover comparison are distinct tasks |
| Message length | Fixed 32-byte messages | Other lengths create separate instances; 64 bytes requires two SHA-256 compression blocks |
| Initial gate policy | X, CX, CCX, SWAP | Measurement-assisted uncomputation is a subsequent milestone |
| Pareto axes | Logical qubits and Toffoli count | Depth is an additional metric; qubits × depth could be another view |
| Scalar score | Q × C | Display alongside the full frontier, not as the only promotion criterion |
| Approximation | Define approximate tracks in the architecture from the beginning | Run approximation experiments after the exact baseline and evaluator are established |
| First delivery | Local CLI, receipts, results store, interactive report | A public submission service is a separate deployment milestone |

## 3. Basis in Google's verifier and local inspection

The local project at /home/shoham/projects/google_quantum_kaggle was inspected during the discussion. Relevant artifacts include:

- official/kickmix/kickmix.so
- official/verifiers/invsqrt/verify_submission_invsqrt.py
- official/verifiers/invsqrt/nr_reference_circuit.py
- official/metric/google-quantum-ai-metric.ipynb
- scripts/run_invsqrt.py

The earlier inspection confirmed that the supplied Kickmix 0.1 binary imports and executes a small circuit successfully in the local environment. It required the compatible system C++ runtime through LD_PRELOAD=/usr/lib/libstdc++.so.6. This was a compatibility check, not a SHA benchmark.

Useful patterns to reuse:

- Circuit loading in readable .kmx and binary .kmb formats.
- Register-schema validation.
- Batched, bit-packed trajectory simulation.
- Multiprocess execution.
- Output, preserved-input, scratch, and phase checks.
- Static and executed operation statistics.
- Circuit-hash- and salt-derived seeds.
- Structured results and complete run receipts.
- Explicit records of evaluator, circuit, and dependency hashes.

The inverse-square-root benchmark has numerical tolerances and an enumerable input domain. Those policies are problem-specific. SHA requires a new problem specification and sampling policy.

The inspected Google artifacts include Apache-2.0 license files. Preserve applicable attribution and notices when reusing code. Pin the upstream revision or distributed artifact and record its provenance.

The new project should install independently of the neighboring Kaggle workspace. Portable Kickmix installation and runtime compatibility are early implementation tasks. A matching upstream source revision for the supplied binary must not be assumed without evidence.

## 4. Define the quantum circuit contract

### 4.1 Recommended headline task: full hash XOR oracle

For a fixed message length, require:

$$
|m\rangle |y\rangle |0^a\rangle
\longmapsto
|m\rangle |y \oplus \operatorname{SHA256}(m)\rangle |0^a\rangle.
$$

Requirements:

- m is a quantum input register and must be preserved.
- y is an arbitrary quantum output register, not only an initially zero register.
- The full digest is XORed into y.
- All scratch qubits start and finish at zero.
- There is no unintended input-dependent phase. Use a fixed exact phase convention in the evaluator.
- Implement standard padding, initial values, message expansion, all 64 rounds, and final feed-forward.
- Registers must have the specified sizes, contain distinct qubits, and not overlap.
- Bit and byte ordering must be explicitly documented and tested against standard SHA byte strings. A possible internal convention is little-endian word registers with explicit conversion to SHA's external byte order; the final convention remains to be frozen.

Testing only y = 0 would establish a weaker contract. Directed and random checks must include nonzero output-register values.

A standard hash loses information. Keeping the message while XORing the digest into a separate register makes the required transformation reversible.

### 4.2 Message length and padding

Proposed headline instance: 32-byte messages.

- A 32-byte SHA-256 message fits into one padded 512-bit block.
- A 64-byte SHA-256 message requires two compression blocks because padding requires another block.
- Different message lengths must have separate benchmark identities and frontiers.
- Fixed length means the length and padding layout are part of the benchmark; the circuit does not need to support arbitrary runtime lengths.
- The reference model and generator should cover padding boundaries around 55/56 and 63/64 bytes, including representative lengths such as 0, 1, 55, 56, 63, 64, and 65 bytes.
- A submitted fixed-length circuit is checked only for its declared length. Boundary checks across lengths apply to the reference and generator, not to a single 32-byte circuit.

### 4.3 Other useful circuit tasks

| Task | Required behavior | Purpose |
|---|---|---|
| Full hash oracle | XOR a complete standard digest into an output register while preserving the message | Headline benchmark |
| Compression oracle | Preserve a supplied message block and chaining state; XOR the next chaining value into a separate output | General compression-core research |
| Grover comparison oracle | Apply the specified flag or phase for matching a target digest, with cleanup | Search-oracle resource analysis |

An arbitrary compression update must not simply be assumed reversible in place.

The Grover task must include comparison and cleanup costs and specify whether the target is fixed in the circuit or supplied as an input. An application-specific comparison oracle can have optimization opportunities different from a general digest oracle.

Do not compare these tasks on one Pareto front.

## 5. Supporting additional SHA algorithms

Adding a classical expected-digest function is relatively easy. Building and validating a reversible reference circuit is the substantial work.

| Algorithm | Additional circuit effort | Proposed priority |
|---|---|---|
| SHA-224 | Small after SHA-256: shared compression core, different initial values, shorter output | Next |
| SHA-512 | Moderate: 64-bit arithmetic, 80 rounds, different constants and larger blocks | Second SHA-2 milestone |
| SHA-384 | Small after SHA-512 works | Alongside SHA-512 |
| SHA-512/224 and SHA-512/256 | Small after SHA-512; use their specified initial values | Alongside SHA-512 |
| SHA3-256 and other SHA-3 variants | Substantial: separate Keccak-based circuit core | Separate milestone |
| SHA-256d | Moderate composition work: two complete hashes and intermediate cleanup | If Bitcoin-related workloads matter |

SHA-512/256 is not obtained by taking the first 256 bits of an ordinary SHA-512 digest.

Parameterize the SHA-2 engine by word size, constants, rounds, initial values, block size, and output width, while completing and validating SHA-256 first. Truncating the public output does not remove the obligation to clean internal state.

SHA-3 uses a different construction and should have its own circuit engine. Carry-approximation ideas for SHA-2 do not automatically apply to SHA-3.

Each algorithm and task gets separate benchmark identities, results, and frontiers.

## 6. Architecture

~~~text
Candidate generator
    -> frozen circuit + benchmark manifest
    -> SHA evaluator using Kickmix + independent classical reference
    -> immutable verification receipt
    -> results store
    -> interactive Pareto report
~~~

Recommended components:

- Python problem specifications, reference functions, circuit generators, evaluator, and CLI.
- Kickmix for circuit representation, simulation, phase tracking, and operation counting.
- hashlib for independent complete standard hashes.
- A separate readable classical compression model for intermediate-state debugging.
- NIST vectors and intermediate results for cross-checking.
- SQLite for the initial local results store.
- JSON receipts and exports, with circuit artifacts retained separately.
- A local interactive report before a hosted submission service.

The manifest identifies algorithm, task, message length, register schema, gate policy, and benchmark version. The evaluator independently determines validity and resource counts; submitted metadata is not authoritative.

Reference code and candidate circuit code should not share so much implementation that the same bug can make both agree. In particular, cross-check the classical compression model against independent standard hashes and published vectors.

## 7. Verification policy

### 7.1 Main-track checks

Reject the submission if any required check fails:

1. Structural validity: register layout, instruction allowlist, valid operands, format, and resource limits.
2. Functional correctness: correct complete digest XOR.
3. Input preservation.
4. Scratch cleanup.
5. Phase correctness.
6. Artifact and evaluator consistency throughout the run.

For purely reversible circuits, forward-then-inverse identity is an additional consistency check. It does not establish SHA correctness by itself.

Reversing a measurement-assisted instruction sequence is not generally an inverse; those circuits need suitable semantic and phase checks.

Circuit-builder allocation/free bookkeeping must not be treated as proof that scratch is clean. The accepted circuit and evaluator checks establish behavior.

### 7.2 Directed tests

Include:

- All-zero and all-one messages.
- Alternating-bit and repeating-word messages.
- Single-bit changes and word-boundary cases.
- Carry-heavy patterns.
- Zero, all-one, patterned, and random initial output registers.
- Standard vectors compatible with the instance.
- Reference-model and generator tests across padding boundaries.
- Exhaustive verification of suitably small arithmetic primitives.

Directed cases complement uniform random sampling. They do not increase the independent uniform sample count used in statistical claims.

### 7.3 Verification profiles

| Profile | Independent random input pairs | Proposed measurement trials per pair |
|---|---:|---:|
| Quick development | 256 | 1 |
| Normal development | 4,096 | 4 |
| Official main-track qualification | 65,536 | 16 |
| Frontier audit | 1,048,576 | 32 |

An input pair consists of a message and an initial output-register value. Sample them independently under the declared distribution. Distinct messages are overwhelmingly likely at the proposed message width; the exact sampling/uniqueness policy must be documented.

For deterministic reversible circuits, use one trial per pair. Repeating the identical deterministic execution adds no input coverage.

Measurement repeats probe additional measurement outcomes. They do not multiply the number of distinct messages. Do not apply an independent-trial binomial formula to N × R grouped shots without handling their shared-input dependence. One independent measurement record per independent input can supply an independent joint sample; additional repeats can be treated as extra branch checks.

Directed cases are additional to the table. The exact directed suite remains to be frozen.

Measure actual SHA reference runtime and memory before freezing worker counts, batch sizes, time limits, and the frontier-audit policy.

### 7.4 What a sampled pass establishes

For a fixed deterministic candidate with failure fraction p under the sampled distribution:

$$
P(\text{zero failures in }N\text{ independent tests})=(1-p)^N.
$$

With zero failures, the one-sided upper bound is:

$$
p_{\mathrm{upper}}=1-\delta^{1/N}
\approx \frac{\ln(1/\delta)}{N}.
$$

| Independent random inputs | Approximate 95% upper bound with zero failures |
|---:|---:|
| 4,096 | 0.073% |
| 65,536 | 0.0046% |
| 1,048,576 | 0.00029% |

For 65,536 zero-failure inputs and Google's stronger confidence choice delta = 2^-128, the upper failure-rate bound is about 0.135%.

A bug affecting one in a million inputs is detected by 65,536 random inputs with probability only about 6.3%.

These are distributional, fixed-candidate statements. They are not universal correctness proofs, worst-case guarantees, or guarantees against unrestricted adaptive test selection. Unlimited repeated submissions also require care when interpreting an overall false-accept probability.

Use a result label such as "PASS: main qualification profile, 65,536 random inputs plus directed checks." The exact target remains a requirement even though its verification is sampled.

Universal equivalence would be a separate formal-verification effort, potentially using component proofs and composition. Exhaustively checking 2^256 messages is infeasible.

## 8. Frozen submissions, seeds, and reproducibility

Test generation should depend on:

- Canonical circuit artifact hash.
- Manifest and benchmark identity.
- Evaluator and sampling-policy versions.
- Salt.

Use an unambiguous, versioned encoding for these inputs and a reproducible sampler.

Local runs may use public salts. Official evaluation should:

1. Freeze the circuit and manifest.
2. Select a fresh unpredictable salt after commitment.
3. Evaluate those exact artifacts.
4. Record the salt and complete receipt for replay.

A public circuit-derived seed alone does not eliminate seed grinding: a submitter can change harmless circuit details or retry candidates to search for favorable tests. Fresh post-commitment salts reduce that opportunity.

A receipt should record:

- Circuit and manifest hashes.
- Algorithm, task, message length, and benchmark version.
- Evaluator, Kickmix, dependency, and cost-model identifiers.
- Gate policy and register schema.
- Sampling policy, salt, and reproducibility information.
- Directed-test count, independent random-input count, measurement repeats, and total trajectories.
- Status and failure details.
- Resource metrics and how they were counted.
- Runtime, memory information where available, worker count, and batch configuration.
- Whether the run meets the official profile or is a development run.

Retain immutable artifacts and replayable failure witnesses. Record whether artifacts remained unchanged during evaluation.

## 9. Resources, scoring, and Pareto fronts

### 9.1 Metrics

Initial definitions:

$$
Q=\text{allocated logical wire count, including inputs, outputs, and scratch}
$$

$$
C=\text{Toffoli count}, \qquad S=Q \times C.
$$

Use Kickmix's circuit qubit count consistently with explicit scratch-wire reuse. Document the handling of sparse wire identifiers. Do not call this "peak live qubits" unless an evaluator actually establishes that lifetime-based definition.

The initial reversible gate policy yields exact static Toffoli counts. Counts of other operations should also be retained.

With broader gate policies, explicitly specify treatment of CCX, CCZ, CSWAP, T gates, and rotations. Google's broader metric uses Toffoli-equivalent costs, including T/4 and a rotation-synthesis model. Do not silently introduce those conversions into a benchmark advertised as raw Toffoli count.

For measurement-dependent execution, distinguish:

- Static gates present in the circuit.
- Mean gates actually executed per shot.
- Variability and evaluation sample size.
- Maximum/static resource figures where meaningful.

Define a stable promotion policy before using stochastic mean counts to distinguish very close submissions.

Record depth and Kickmix reaction depth with their definitions. Q × C is a resource proxy, not an end-to-end physical runtime estimate. A qubits × depth view needs explicit scheduling assumptions.

### 9.2 Frontier definition

Circuit A dominates B if:

- Q_A <= Q_B.
- C_A <= C_B.
- At least one inequality is strict.

Retain every verified nondominated circuit even if it does not improve Q × C.

Example:

| Circuit | Qubits | Toffolis | Product | Frontier status |
|---|---:|---:|---:|---|
| A | 1,000 | 100,000 | 100 million | Nondominated |
| B | 800 | 140,000 | 112 million | Nondominated |
| C | 1,100 | 120,000 | 132 million | Dominated by A |

B remains useful because it uses fewer qubits despite having a larger product score.

Frontier comparison requires matching algorithm, circuit task, message length, semantic contract, cost model, and applicable verification policy. Cost-model or benchmark changes need versioned results and, where necessary, reevaluation.

### 9.3 Interactive report

Show:

- Qubits versus Toffolis.
- Connected frontier points.
- Dominated points in gray.
- Baselines and best-product points.
- Filters by benchmark and verification status.
- Clickable metrics, notes, source/artifact references, and receipts.
- Frontier history over time.
- Downloadable JSON/tabular results.
- Accuracy-budget filters for approximate tracks.

Literature estimates must be visibly distinguished from reproduced, fully comparable circuit measurements.

## 10. Reference circuits and optimization directions

Build a readable full SHA-256 reference from:

- Reversible modular addition.
- SHA Boolean functions.
- Rotations and shifts.
- Message-schedule generation.
- Round computation.
- Final feed-forward.
- Digest extraction into the XOR output.
- Complete cleanup.

Rotations can often be represented through wire bookkeeping, provided the external register mapping stays correct.

Explore several storage/recomputation designs:

| Design | Intended tradeoff |
|---|---|
| Store more intermediate values | More qubits, less recomputation |
| Rolling message schedule | Reduced schedule storage |
| Recompute selected intermediates | Fewer qubits, more gates |
| Alternative adders | Different Toffoli, scratch, and depth costs |

Several designs provide initial frontier candidates. Do not assume all will be nondominated before measurement.

Start with X, CX, CCX, and SWAP. Add measurement-assisted uncomputation using validated phase-correct cleanup templates after the reversible baseline works. Google's Kickmix builder already provides relevant mechanisms, including temporary-AND cleanup.

Changing the gate policy may require a benchmark/cost-model version change or reevaluation so comparisons remain meaningful.

## 11. Approximate solutions

### 11.1 Why retain an approximate track

Approximate solutions are relevant enough to represent in the architecture from the beginning. They may trade a small rate of wrong digests for lower gate or qubit costs.

The useful initial metric is the probability that the complete digest is wrong:

$$
\varepsilon =
\Pr_{m \sim D}[
\widetilde{\operatorname{SHA}}(m) \ne \operatorname{SHA}(m)
].
$$

Here D is the declared input distribution, initially uniform fixed-length messages.

Any incorrect digest bit counts as a failure. Numerical closeness or a high fraction of matching digest bits is not the relevant success criterion for exact digest comparison.

This is separate from exact truncated-output hashing: computing a specified digest prefix exactly is a different task, not an approximate full SHA digest.

### 11.2 Proposed accuracy budgets

| Failure budget | Complete digest correct on | Suggested role |
|---:|---:|---|
| 10^-2 | At least 99% of sampled-distribution inputs | Exploratory tier |
| 10^-3 | At least 99.9% | Proposed primary approximate tier |
| 10^-4 | At least 99.99% | Stronger accuracy tier |
| 10^-6 | At least 99.9999% | Ambitious and expensive to establish |

These are proposed research tiers, not established tolerances for every application.

The discussion recommended starting approximation experiments at a 0.1% full-digest failure budget. The main track remains the user's agreed exact-target, zero-observed-failure track.

Initially require preserved input, clean scratch, and correct phase behavior even in the approximate track. Budget approximation in the computed digest only. Measurement/phase faults would be a distinct error model rather than an interchangeable way to spend this budget.

### 11.3 Candidate approximation: shortened carry propagation

A plausible direction is bounding carry propagation in adders, accepting errors on rare longer chains.

Important constraints:

- Measure complete digest agreement, not internal arithmetic error magnitude.
- SHA uses many additions; their failure contributions accumulate.
- If a design has 600 potentially failing additions, a conservative bound is epsilon_hash <= sum(epsilon_i).
- An equally divided total budget of 10^-3 would permit about 1.7 × 10^-6 failure probability per addition in that illustrative design.
- Each per-operation bound must apply to the actual intermediate operands. Independence and uniformity of intermediate words must not be assumed without justification.
- Changes can propagate through later SHA rounds, so a small internal arithmetic discrepancy may produce an entirely wrong final digest.
- Substantial resource savings are a hypothesis to test, not a result already established in this project.

### 11.4 Deterministic approximation versus random execution errors

Distinguish:

1. A clean reversible circuit computing a fixed approximate function, where the same messages are wrong on every call.
2. A circuit introducing fresh random phase or execution errors on repeated calls.

These have different effects in a quantum algorithm.

For preimage search, study whether a fixed approximate function:

- Preserves genuine target preimages.
- Creates false target matches.
- Changes the number and distribution of marked inputs.
- Requires additional verification or repetitions.

An exact classical check can reject a false returned candidate. It cannot recover a genuine preimage that the approximate oracle never marks.

A 99.9% average digest-agreement rate alone does not establish that repeated Grover search remains useful. Conversely, it is too strong to conclude that every useful coherent approximation needs an exponentially small average digest-error rate.

Google's single-application analysis gives a state-error bound scaling as 2 × sqrt(epsilon), under structural assumptions and sampling from the relevant input-state distribution. That is not automatically a bound for an entire sequence of Grover iterations, whose input amplitudes evolve.

Some faulty-oracle noise models eliminate Grover's speedup, while coherent access to bounded-error verifiers admits robust search constructions. Application-specific analysis is required.

Do not apply a generic C/(1-epsilon) cost correction as if it established quantum search performance.

### 11.5 Approximate-track verification and frontier

Allow observed digest failures and compute a one-sided upper confidence bound from the count. Compare that bound with the declared accuracy budget.

Requiring zero observed failures would unnecessarily reject many intentional approximations. The zero-failure formula in Section 7 is a useful reference point, not the whole approximate-track acceptance rule.

For scale, establishing an error bound near 10^-6 with zero failures needs roughly:

- 3 million independent inputs at 95% confidence.
- 89 million at confidence 1 - 2^-128.

Sampling, confidence level, evaluator cost, and acceptable error budget are separate choices.

Record Q, C, the observed digest failure rate, sample size, and the upper failure-rate bound. Show a Q–C frontier for each fixed error budget, or an additional three-dimensional Q/C/error view.

Do not place approximate circuits and exact-target circuits on an undifferentiated frontier. Claims about a complete search algorithm require their own success and cost analysis.

## 12. Implementation milestones and completion criteria

1. **Freeze the benchmark specification.** Define task, message length, bit ordering, registers, gate policy, exact-target acceptance, sample count, metric definitions, and versions. Specify approximate-track data fields even if its experiments come later.  
   Completion: required behavior is unambiguous.

2. **Establish independent classical references.** Implement the readable compression model and cross-check complete hashes, intermediate values, and padding boundaries.  
   Completion: agreement with independent hashes and published vectors.

3. **Build the reversible SHA-256 baseline.** Validate small primitives, then all rounds, digest extraction, and cleanup.  
   Completion: the fixed-length full hash XOR oracle passes directed and random evaluation.

4. **Implement the evaluator and receipts.** Add structural checks, batched simulation, sampling, operation counts, phase checks, reproducible seeds, and failure diagnostics.  
   Completion: identical inputs replay identical results; deliberately broken outputs, preservation, cleanup, and register handling are rejected. Add phase-fault rejection checks when the gate policy includes phases or measurements.

5. **Add results storage and Pareto reporting.** Implement SQLite storage, artifact retention, JSON export, dominance calculation, interactive point inspection, and frontier history.  
   Completion: multiple measured circuit designs can be compared and replayed.

6. **Calibrate verification cost.** Measure qualification and audit runtime/memory; freeze batching, worker limits, and promotion/audit policy.  
   Completion: official evaluation budgets are based on measured SHA performance.

7. **Extend circuit optimization and algorithms.** Add SHA-224, measurement-assisted cleanup, additional message lengths, SHA-512-family support, and approximation experiments. Their relative order remains a prioritization choice.  
   Completion: each new track has a validated reference, declared contract, and comparable metrics.

8. **Add public submissions if desired.** Introduce isolated evaluator workers, fresh post-commitment salts, artifact storage, authentication, and a queue.  
   Completion: public results are produced by the official evaluator and remain locally replayable.

Do not commit to an implementation timeline or throughput estimate before the baseline circuit and evaluation profile are measured.

## 13. Open decisions before implementation

The following are proposed defaults, not additional user approvals already obtained:

- Confirm 32-byte messages as the headline SHA-256 instance.
- Decide whether compression launches alongside the full hash oracle.
- Decide whether SHA-224 is part of the first release or the first extension.
- Freeze bit/byte ordering and manifest details.
- Freeze the directed test suite.
- Choose the confidence level used for statistical reporting.
- Decide whether every frontier promotion requires the million-input audit.
- Freeze the initial gate allowlist and the measurement-support milestone.
- Define any mean-executed-count promotion policy before permitting stochastic resource comparisons.
- Confirm approximate tiers and whether 0.1% is the primary experimental tier.
- Decide when to add a full Grover comparison task and application-specific approximation analysis.
- Decide whether the first product remains local or includes public submissions.

Already agreed: the main track targets exact behavior and uses 65,536 verification tests as its random qualification sample.

## 14. Sources discussed

- Google Quantum AI, "Leveraging verifiable structure in quantum circuits to find more efficient compilations with agentic AI": https://arxiv.org/abs/2610.23832
- Google's verification, approximation, and confidence-bound analysis: https://arxiv.org/html/2610.23832v1
- ECDSA.fail challenge and scoring contract: https://github.com/Layr-Labs/ecdsafail-challenge
- ECDSA.fail Pareto presentation: https://ecdsa.fail/
- NIST FIPS 180-4, SHA-2 specification: https://csrc.nist.gov/pubs/fips/180-4/upd1/final
- NIST FIPS 202, SHA-3 specification: https://csrc.nist.gov/pubs/fips/202/final
- NIST secure-hashing vectors and intermediate results: https://csrc.nist.gov/projects/cryptographic-algorithm-validation-program/secure-hashing
- Høyer, Mosca, and de Wolf, "Quantum Search on Bounded-Error Inputs": https://arxiv.org/abs/quant-ph/0304052
- Regev and Schiff, "Impossibility of a Quantum Speed-up with a Faulty Oracle": https://arxiv.org/abs/1202.1027

Local observations above come from the earlier inspection of /home/shoham/projects/google_quantum_kaggle. No SHA circuit implementation or SHA performance measurement was completed during that planning inspection.
