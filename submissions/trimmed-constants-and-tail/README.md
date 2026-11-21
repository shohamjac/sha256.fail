# Trimmed constants and tail

The baseline architecture (`../example`) with hand-written adders, a shorter message
schedule, and cheaper constants.

| | This | Folded first rounds | Baseline |
|---|---:|---:|---:|
| Qubits (Q) | 829 | 831 | 831 |
| Toffolis per shot (C) | 26,067 | 26,716 | 27,088 |
| Score (Q × C) | 21,609,543 | 22,200,996 | 22,510,128 |

Fewer qubits and fewer Toffolis than both: it dominates them. The score is 2.7% below
`../folded-first-rounds`.

## What changed

| Change | Toffolis saved |
|---|---:|
| Constants: trailing zeros, carry-ins, copies, merged final additions | 254 |
| Two additions in a row share their lowest bit | 209 |
| W_62 and W_63 are never stored | 186 |
| Total | 649 |

- **Constants are cheaper.** Adding a constant costs one Toffoli per bit above its lowest set
  bit: below that bit nothing changes, and the old value of that bit is the first carry. And
  an addition of two registers can take a carry-in of one for free, since the first carry
  becomes an OR instead of an AND. So each round adds K_t − j instead of K_t, with j chosen
  to give the most trailing zeros, and the additions around it take carry-ins worth j.
  Where the baseline adds into a register that holds a known constant, in rounds 0 to 3,
  this copies the value with CNOTs and adds the constant. The final additions of the initial
  hash value for H_0 and H_4 are merged into the last round, which then adds K_63 + IV_4 to
  one register and K_63 + IV_0 to the other instead of three constants.
- **Two additions in a row share their lowest bit.** When `x += a` is followed by `x += b`,
  each computes a carry out of bit 0, but the two carries are never both set: together they
  are Maj(x_0, a_0, b_0). So bit 0 is done once, with one AND, and the two additions run on
  bits 1 to 31, the second taking that majority as its carry-in. 61 Toffolis instead of 62.
  This applies once in every schedule step and twice in every round.
- **The last two schedule words are never stored.** W_62 and W_63 are each used once, by
  their own round, and no later word depends on them. Storing a word costs three additions,
  using it one, and removing it three more. Adding its four terms straight into the state
  costs four. The schedule is expanded only up to W_61 and rewound from there.
- **Two fewer qubits.** Bit 31 of an operand only ever flips bit 31 of the target, so the
  temporary that holds Sigma, Ch or Maj is 31 qubits. The constant adder uses the same 30
  carry qubits as the register adder, where Kickmix's uses 31. Scratch is 61 qubits.

The circuit is written as Kickmix text, one gate per line, by `build.py`. It does not use
Kickmix's arithmetic helpers. For each round `build.py` tries every way of handing out
carry-ins and keeps the cheapest.

## Where the Toffolis go

| Part | This | Folded first rounds |
|---|---:|---:|
| Rounds 4 to 63 | 16,707 | 16,800 |
| Schedule, forward | 4,232 | 4,464 |
| Schedule, rewind | 4,232 | 4,464 |
| Rounds 1 to 3 | 661 | 686 |
| Round 0 and the final additions | 235 | 302 |
| Total | 26,067 | 26,716 |

## What is left

Everything except the rewind computes something the digest needs: 21,835 Toffolis. A
Toffoli is the only gate here that can compute an AND, so no circuit can use fewer of them
than the function needs AND gates as a classical circuit. Nobody knows that number, and no
useful lower limit on it is proven. The smallest published count found for this function is
22,272 (Campanelli, Gennaro, Goldfeder and Nizzardo,
[CCS 2017](https://acmccs.github.io/papers/p229-campanelliA.pdf)); the
[NIST circuit library](https://csrc.nist.gov/Projects/circuit-complexity/list-of-circuits)
lists 22,385. Those are circuits somebody built, not limits: the forward part here is
already 437 below the smaller one.

So the slack that can be seen is the rewind of the schedule, 4,232 Toffolis, and the 61
scratch qubits. Removing both entirely would give 768 × 21,835, near 16.8 million, 22% below
this one. Going further needs fewer ANDs in the forward part. Each addition, Ch and Maj is
at its minimum taken alone, so the saving has to come from merging work across them, as the
shared lowest bit does.

Two trades that were tried and do not pay at this point on the front:

- Dropping the 31-qubit temporary by recomputing each Ch and Maj bit when its carry is
  cleared. The fix-up is a CCZ on half the shots: about 1,900 more Toffolis for 30 qubits.
- An adder that keeps its carries in the operand (Cuccaro) needs no carry qubits but twice
  the Toffolis.

## Rebuild and verify

```bash
uv run --project ../../sha256_verifier python build.py
```

```bash
uv run --project ../../sha256_verifier sha-verify pack circuit.kmb --rm
```

```bash
uv run --project ../../sha256_verifier sha-verify run circuit.kmb.zst
```
