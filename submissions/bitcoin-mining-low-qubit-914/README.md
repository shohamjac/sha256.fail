# Bitcoin mining on 914 qubits

A phase oracle for the problem `bitcoin-mining-v1` on 914 qubits. The contract is
[bitcoin-mining-v1.md](../../sha256_verifier/docs/bitcoin-mining-v1.md).

| | This | [1,072 qubits](../bitcoin-mining-low-qubit) | [Baseline](../bitcoin-mining-baseline) |
|---|---:|---:|---:|
| Qubits (Q) | 914 | 1,072 | 2,000 |
| Toffolis per shot (C) | 1,068,545 | 522,269 | 262,158 |
| Score (Q × C) | 976,650,129 | 559,872,368 | 524,316,000 |
| Reaction depth (D) | 237,143 | 130,657 | 108,224 |
| Operations | 12,429,973 | 5,688,103 | 3,526,903 |

It is built for the fewest qubits, whatever that costs: it has four times the baseline's
Toffolis. Verified at full strength: 2,848 shots on 16 real blocks and 1,048,576 random
shots, all correct. The official receipt is recorded in `../../results/bitcoin-mining-v1/`
when this directory is merged.

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
- **The two old words are computed again.** `W_(t−15)` is computed from the two base words
  in the two registers that are left, used, kept for one step as the next `W_(t−16)`, and
  measured away.
- **An input without a σ needs no register.** `W_(t−7)` and `W_(t−16)` enter a word as plain
  additions, so in the recursion they are added term by term instead of being computed
  whole. Only the arguments of σ0 and σ1 need a register of their own.
- **A planner chooses.** For each word and each number of free registers it finds the
  cheapest plan: which input to build on, and for each input without a σ whether to compute
  it or to expand it.
- **The base words are `W_16` and `W_18`**, kept in the registers of the root's last word
  and the nonce. `W_19` to `W_24` are then each an invertible function of `W_18` (with
  `W_16`), made in place and undone, so the recursion reaches them with no register.

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
| 64 | the base words `W_16` and `W_18`, in the registers of the root's last word and the nonce |
| 224 | seven schedule words in progress |
| 64 | two registers for the word being computed again |
| 2 | the carries of a classical addition |
| **914** | |

The other steps peak at 880 (coinbase block, root, hash), 912 (header's first block) and
848 (uncomputing the header's second block).

Two smaller changes make room elsewhere:

- **No 32-qubit temporary.** The baseline writes a Sigma, Ch or Maj value into a temporary
  and adds that. Here the value is made in place, as [`../zero-scratch`](../zero-scratch)
  does, and Kickmix's adder adds it. Without this the header's first block would need 944.
- **Classical additions with two clean qubits.** Inside the recursion a classical word or a
  constant is added with the adder of Gidney
  ([arXiv:2507.23079](https://arxiv.org/abs/2507.23079)), which ripples the carries through
  two qubits and borrows busy ones. `time` and `bits` are known only when the circuit runs,
  so the adder takes its offset as classical bits; the sums of classical words it adds are
  worked out by classical instructions, which cost nothing.

I found no way to 10 schedule registers. A word that needs two σ arguments which are not
on a chain cannot be computed in one register, and that is the case for `W_35` and most
words after it. This is the floor of this design, not a proven lower bound for the problem.

## Where the Toffolis go

| Part | Count |
|---|---:|
| Header's second block: computed twice, 305,501 each | 611,002 |
| Its uncomputation, once | 29,758 |
| Coinbase block: computed 4 times at 26,720, uncomputed once at 31,184 | 138,064 |
| Root: computed 4 times and uncomputed once, 26,065 each | 130,325 |
| Header's first block: computed 3 times and uncomputed once, 26,720 each | 106,880 |
| Hash: computed and uncomputed, 26,065 each | 52,130 |
| The comparison, done twice | 388 |
| Total in the circuit | 1,068,547 |

A few Toffolis sit under classical conditions, so the mean executed per shot, 1,068,545, is
just below the count in the circuit. More than half of the operations, 6.3 of 12.4 million,
are the two computations of the header's second block. The contract allows 20 million.

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
