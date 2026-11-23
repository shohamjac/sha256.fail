# Bitcoin mining with kept carries

A phase oracle for the problem `bitcoin-mining-v1` built for the fewest Toffolis, on every
qubit the problem allows. The contract is
[bitcoin-mining-v1.md](../../sha256_verifier/docs/bitcoin-mining-v1.md).

| | This | [Baseline](../bitcoin-mining-baseline) |
|---|---:|---:|
| Qubits (Q) | 65,536 | 2,000 |
| Toffolis per shot (C) | 140,592 | 262,158 |
| Toffolis in the circuit | 141,251 | 262,158 |
| Score (Q × C) | 9,213,828,018 | 524,316,000 |
| Reaction depth (D) | 17,169 | 108,224 |
| Operations | 1,907,548 | 3,526,903 |

It is built for the Toffoli count, not for the score, which is 18 times the baseline's.
Verified at full strength with a random salt: 2,848 shots on 16 real blocks and 1,048,576
random shots, all correct. The official receipt is recorded in
`../../results/bitcoin-mining-v1/` when this directory is merged.

## The idea: a carry that is kept costs nothing to undo

The oracle computes the hash, flips the phase, and then has to undo the hash. In the
baseline the way back costs as much as the way forward, because undoing an addition is a
subtraction, and a subtraction computes every carry again.

An addition here computes its carries with one AND each, as the baseline's does. The
baseline then measures each carry away, which is free. This circuit can leave the carries
where they are instead, one qubit each. On the way back the sum, the addend and the carries
are all present, so the old value of every bit is a CNOT away, and each carry is measured
away then. No Toffoli is spent.

So one spare qubit saves one Toffoli. The same holds for the ANDs of Ch and Maj. The
circuit keeps ANDs until its qubits run out and computes the rest twice:

| | ANDs |
|---|---:|
| Computed on the way forward | 101,985 |
| Of those, kept in qubits | 62,369 |
| Computed again on the way back | 39,266 |
| Toffolis in the circuit | 141,251 |

The other 3,167 qubits are the search register and the registers the five compressions work
in. Which ANDs are kept does not matter to the count; the first to be computed are kept.

The limit of 65,536 qubits is what sets the result. `build.py` takes the number of qubits as
an argument, and every qubit taken away costs one Toffoli:

| Qubits | Toffolis in the circuit |
|---:|---:|
| 3,167 | 203,620 |
| 8,192 | 198,595 |
| 16,384 | 190,403 |
| 32,768 | 174,019 |
| 65,536 | 141,251 |
| 104,802 | 101,985 |

The last row keeps every AND and is outside the problem's limits. Three of the other rows
are entries of their own, since no point on the line has both fewer qubits and fewer
Toffolis than another:
[3,167 qubits](../bitcoin-mining-low-toffoli-3167),
[16,384](../bitcoin-mining-low-toffoli-16384) and
[32,768](../bitcoin-mining-low-toffoli-32768).

## Fewer ANDs on the way forward

Each AND saved here is saved again on the way back.

- **Classical inputs stay classical.** Only 80 input bits are qubits. A word that depends on
  classical bits alone is worked out on classical bits, which costs nothing. In a sum, every
  classical term is added up classically first and reaches the qubits as one addend. Ch and
  Maj need no AND when two of their arguments are classical. The first nine rounds of the
  header's first block see no qubit at all, and in the header's second block `W_17` is
  classical and `W_20` and `W_21` need no AND.
- **No register is copied to hold a classical value.** A classical addend drives X gates on
  the carry qubit under classical conditions, so it needs no register and its lowest carry
  is free.
- **Pairs of additions and carry-ins**, as in
  [`../trimmed-constants-and-tail`](../trimmed-constants-and-tail). Two additions in a row
  into one register share their lowest bit: 61 ANDs instead of 62. A round constant gives up
  to three of its units to carry-ins, which are free, and is left with more trailing zeros;
  a constant costs one AND per bit above its lowest set bit.
- **The schedule is never rewound.** The baseline clears each block before the next
  compression. Here each compression leaves its last 16 schedule words where they are.
- **The last compression stops early.** Only `H_5`, `H_6` and `H_7` are compared. They need
  63 rounds, and the last four of those only their `e` half.
- **Easy exponents skip more.** `H_5` matters only at exponents up to `0x1a` and `H_6` up to
  `0x1e`, since the target is zero below its mantissa. The rounds and comparison bits that
  serve only those words sit under a classical condition. This is why the circuit executes
  140,592 Toffolis per shot on average, 659 fewer than it contains.

Forward ANDs by compression:

| Compression | ANDs forward | Computed again |
|---|---:|---:|
| Coinbase, last block | 20,824 | 0 |
| Merkle root | 20,956 | 0 |
| Header, first block | 19,141 | 0 |
| Header, second block | 20,868 | 19,228 |
| Block hash | 20,102 | 20,038 |
| Comparison | 94 | 0 |

## How the circuit is written

`build.py` writes the forward half as a list of steps: X and CX gates, some under a
classical condition, and "compute an AND into a clean qubit" or "measure an AND away and fix
the phase". The backward half is the same list in reverse with the two kinds of AND step
swapped. Nothing else is written for it, so an addition that kept its carries is undone for
free and one that measured them away is undone by computing them again.

The comparison is a borrow chain over the 96 compared bits. Its last AND is not computed:
the phase is a CZ on its two inputs.

## What is left

- With no limit on qubits the same circuit needs 101,985 Toffolis. Under the limit the count
  is twice the forward ANDs minus the qubits left for keeping them, so a forward AND saved
  counts twice and a register qubit saved counts once.
- The forward count is close to what the best single compression here achieves (21,835 for
  a compression with no classical input). Constant additions are the largest part that is
  not the function's own: about 27 ANDs in each round whose message word is a qubit.
- The low half of the coinbase's `W_1` is classical and is loaded into 16 qubits. Treating
  it as classical would save those qubits and about 80 ANDs.
- A classical addend known only when the circuit runs costs 30 ANDs whatever its value.
  Skipping its trailing zeros under classical conditions would save about one AND per
  addition on average.

## Rebuild and verify

```bash
uv run --project ../../sha256_verifier python build.py
```

```bash
uv run --project ../../sha256_verifier sha-verify run circuit.kmb.zst --problem bitcoin-mining-v1
```

`build.py` checks the circuit against `hashlib` and does not import the verifier. It imports
the baseline's `build.py` for the SHA-256 constants and that check.
