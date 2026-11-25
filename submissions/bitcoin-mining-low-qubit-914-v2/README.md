# Bitcoin mining on 914 qubits, with half the Toffolis

A phase oracle for the problem `bitcoin-mining-v1` on 914 qubits. The contract is
[bitcoin-mining-v1.md](../../sha256_verifier/docs/bitcoin-mining-v1.md).

| | This | [914 qubits, first](../bitcoin-mining-low-qubit-914) | [1,072 qubits](../bitcoin-mining-low-qubit) | [Baseline](../bitcoin-mining-baseline) |
|---|---:|---:|---:|---:|
| Qubits (Q) | 914 | 914 | 1,072 | 2,000 |
| Toffolis per shot (C) | 514,395 | 1,068,545 | 522,269 | 262,158 |
| Score (Q × C) | 470,157,033 | 976,650,129 | 559,872,368 | 524,316,000 |
| Reaction depth (D) | 167,687 | 237,143 | 130,657 | 108,224 |
| Operations | 8,618,158 | 12,429,973 | 5,688,103 | 3,526,903 |

It keeps the qubit count of [`../bitcoin-mining-low-qubit-914`](../bitcoin-mining-low-qubit-914)
and the same layout, and cuts the Toffolis by 52%. Verified at full strength: 2,848 shots
on 16 real blocks and 1,048,576 random shots, all correct. The official receipt is recorded
in `../../results/bitcoin-mining-v1/` when this directory is merged.

## What changed from the first 914-qubit circuit

| Change | Toffolis after it |
|---|---:|
| The first circuit | 1,068,547 |
| Arithmetic that takes what is free; classical parts summed and added once; an old word is added to both registers that need it | 606,809 |
| An old word that stays is turned into the word two after it | 544,529 |
| The base registers stay where they were last read, and both move | 537,629 |
| Classical message words get no qubits until overwritten; classical rounds | 514,397 |

Each line is the count of the whole circuit as it was built at that point. The sections
below describe the result.

## The frame

It starts from [`../bitcoin-mining-low-qubit`](../bitcoin-mining-low-qubit), whose README
explains the frame: every intermediate hash is measured away as soon as the next one exists,
and the phase that leaves is removed later by computing the value again. In that circuit one
step sets the count, the header's second block, because it holds its starting state, its
working state and 16 schedule words at once. This circuit changes that block.

## A schedule that is not held

Only two of the block's 16 message words depend on the search register: `W_0`, the root's
last word, and `W_3`, the nonce. The rest are `time`, `bits` and padding. So every schedule
word is a function of two words, and a word that is not held can be computed again. The
price grows by about a quarter for each step further into the schedule, which is why this
works for one block and not for the others, whose blocks have seven or eight quantum words.

A schedule step is `W_t = W_(t−16) + σ0(W_(t−15)) + W_(t−7) + σ1(W_(t−2))`.

- **Seven registers hold the words in progress.** `W_t` is built in the register of
  `W_(t−7)`. As soon as `W_t` exists, `σ1(W_t)` is added to the register that will become
  `W_(t+2)`. After its own round, `W_t` is then needed only as the start of `W_(t+7)`.
- **The two old words are computed again.** Each old word `W_u` is computed once more, in
  the two registers that are left, and added to the registers that will become `W_(u+15)`
  and `W_(u+16)`. Those exist for six steps before they are used, so the order in which
  old words are computed is free within that window.
- **An old word that stays is turned into the next one.** `W_u` is `σ1(W_(u−2))` plus three
  more terms, so a register that still holds `W_(u−2)` becomes `W_u` for much less than
  computing `W_u` from the two base words. With two registers only one word can stay, since
  the other register is the workspace. A dynamic program over the steps chooses which
  words stay and for how long. Near the end the words in progress die and free their
  registers, and then an even and an odd word both stay.
- **An input without a σ needs no register.** `W_(t−7)` and `W_(t−16)` enter a word as plain
  additions, so in the recursion they are added term by term instead of being computed
  whole. Only the arguments of σ0 and σ1 need a register of their own.
- **A planner chooses.** For each word and each number of free registers it finds the
  cheapest plan in Toffolis: which input to build on, and for each input without a σ
  whether to compute it or to expand it.
- **The base registers move.** The nonce's register is turned in place into `W_19`, `W_21`,
  `W_23`, or into `W_18`, `W_20`, `W_22`, `W_24`. The register of the root's last word holds
  `W_16`, or takes over `W_18` to `W_24` while the nonce's register is on the odd side, so
  that even and odd words can be read together. Each stays where it was last read, and both
  go home at the end.

A schedule word that is measured away leaves a phase like any other value. Its measured
bits are XORed into one classical word per `W_s`, and all of them are paid when the block
is uncomputed.

## Uncomputing needs no kept state

Computing the block needs mid twice: as the starting state and for the final addition. That
is why a copy is held. Uncomputing does not: mid is subtracted from the result first and
then measured away. That leaves room for the ordinary 16-word schedule in place. The rounds
run backwards and turn the working state into mid again, and the phase of the measurement
is removed there. As the schedule is expanded each `W_s` passes through its register once,
which is where the phases owed on schedule words are removed.

So the short schedule is used only where the block is computed, twice, and its
uncomputation is an ordinary compression on 848 qubits.

## Where the 914 qubits go

At the peak, while an old schedule word is being computed again in the header's second
block:

| Qubits | What |
|---:|---|
| 48 | `extranonce`, idle |
| 256 | mid, kept for the addition that ends the compression |
| 256 | the state being worked on |
| 64 | the two base registers, of the root's last word and the nonce |
| 224 | seven schedule words in progress |
| 64 | two registers for the old words |
| 2 | the carries of a classical addition |
| **914** | |

The other steps fit in 880 (coinbase block, root, hash), 912 (header's first block) and
848 (uncomputing the header's second block). They use what is left of the 914 as
workspace.

## Arithmetic that takes what is free

How much workspace a step has changes from one addition to the next, so every operation
looks at the free qubits when it is emitted:

- **Additions.** Kickmix's adder uses each free qubit as a carry, up to 30. It costs 61
  Toffolis with none and 31 with 30.
- **Ch and Maj.** With 32 qubits free the value goes into a temporary, and its ANDs are
  erased by measurement: 32 Toffolis. Without them it is made in place, as
  [`../zero-scratch`](../zero-scratch) does: 64.
- **Classical additions.** With a register free, Kickmix's adder: 30 Toffolis. Without
  one, the adder of Gidney ([arXiv:2507.23079](https://arxiv.org/abs/2507.23079)), which
  ripples the carries through two clean qubits and borrows busy ones: 91. `time` and `bits`
  are known only when the circuit runs, so that adder takes its offset as classical bits.
- **Classical sums cost nothing.** Everything classical that is added to one register is
  summed by classical instructions first and added once.

Two more things hold for every compression, not only the header's second block:

- **Classical message words get no qubits until the schedule overwrites them.** That was
  already so for padding. Here it also holds for the coinbase tail, the version, the
  previous hash, `time` and `bits`.
- **Rounds that see only classical data are classical.** The header's first block starts
  from a constant and its first nine message words are classical, so its first nine rounds
  are done by classical instructions.

## Where the Toffolis go

| Part | Count |
|---|---:|
| Header's second block: computed twice, 67,600 each | 135,200 |
| Its uncomputation, once | 25,356 |
| Coinbase block: computed 4 times at 21,537, uncomputed once at 25,348 | 111,496 |
| Root: computed 4 times and uncomputed once, 21,939 each | 109,695 |
| Header's first block: computed 3 times and uncomputed once, 22,096 each | 88,384 |
| Hash: computed and uncomputed, 21,939 each | 43,878 |
| The comparison, done twice | 388 |
| Total in the circuit | 514,397 |

A few Toffolis sit under classical conditions, so the mean executed per shot, 514,395, is
just below the count in the circuit.

Of the 67,600 for one computation of the header's second block, 22,400 are the rounds and
the words in progress, and 45,200 are the old words computed again.

## What bounds it

- **Qubits.** I found no way to 10 schedule registers. A word that needs two σ arguments
  which are not at hand cannot be computed in one register, and that is the case for
  `W_35` and most words after it. This is the floor of this design, not a proven lower
  bound for the problem.
- **Toffolis.** The ordinary compressions are 16 of the 19 and cost about 22,000 each,
  which is what their additions and ANDs come to. What is left to gain there is small: the
  first four rounds of a compression that starts from a classical state (I estimate 350
  Toffolis each time), and the last rounds of the hash, of which only three output words
  are compared (I estimate 900). Neither is built. In the header's second block a third
  register for the old words would make them much cheaper, but that is 946 qubits.

## Files

| File | What |
|---|---|
| `circuit.kmb.zst` | The circuit that is verified, zstd-compressed |
| `meta.json` | Name, authors, kind, problem and description, carried into the receipt |
| `build.py` | How the circuit was generated. Never run by the verifier. |

## Rebuild and verify

```bash
uv run --project ../../sha256_verifier python build.py
```

```bash
uv run --project ../../sha256_verifier sha-verify run --problem bitcoin-mining-v1 circuit.kmb.zst
```

`build.py` imports the generator of `../bitcoin-mining-low-qubit`, which imports those of
`../bitcoin-mining-baseline` and `../zero-scratch`. It tests its classical adder on random
inputs and checks the circuit against `hashlib` on 1,024 made-up blocks before writing it.
