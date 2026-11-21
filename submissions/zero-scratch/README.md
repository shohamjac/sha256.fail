# Zero scratch

SHA-256 compression on 768 qubits: the 512 of `block` and the 256 of `digest`, and nothing
else. That is the fewest qubits the contract allows.

| | This | Low-qubit adder | Baseline |
|---|---:|---:|---:|
| Qubits (Q) | 768 | 801 | 831 |
| Toffolis per shot (C) | 85,297 | 50,224 | 27,088 |
| Score (Q × C) | 65,508,096 | 40,229,424 | 22,510,128 |

It is not a good score. It is the end of the Pareto front: no circuit can use fewer qubits.

The circuit has no measurement and no classical bit. It is X, CNOT and Toffoli gates only,
so it is also an ordinary reversible classical circuit.

## How each piece does without scratch

- **Additions keep their carries in the operand.** To add `a` into `b`, the carry into bit
  i + 1 is XORed into wire a[i + 1], and taken out again afterwards (Takahashi, Tani and
  Kunihiro, [arXiv:0910.2530](https://arxiv.org/abs/0910.2530)). The carry into the top bit
  goes straight into the top bit of `b`. That is 61 Toffolis for 32 bits, against 31 for an
  adder with 30 carry qubits.
- **Sigma operands are made in place.** All four sigma functions are invertible linear maps,
  so CNOTs turn a register into Sigma(register); it is added and then turned back. `build.py`
  finds the CNOTs by Gaussian elimination.
- **Ch and Maj are computed onto one of their own inputs.** Ch(e, f, g) = g ⊕ e(f ⊕ g) is
  written onto g, and Maj(a, b, c) = c ⊕ (a ⊕ c)(b ⊕ c) onto c. The result is added and the
  same Toffolis undo it. The top bit only flips the top bit of the target, so it is never
  written.
- **Constants are added as signed binary digits.** A constant has no wires to hold carries.
  To subtract 2^j, add any unrelated register y to the bits from j up, then add its
  complement: y + ¬y is all ones, which is −1, whatever y holds. With a carry-in of one on
  both additions the net is +2^j. A digit at a high bit is cheap because its two additions
  are narrow, so `build.py` picks the cheapest digits, not the fewest, and first hands out
  free carry-ins of one to the other additions to clear the constant's low bits.
- **The first rounds use the registers that are still empty.** In rounds 0 to 3 part of the
  state is a known constant and part of `digest` is still zero. One constant is written
  into each new register with X gates before anything is added to it. A zero register holds
  Ch or Maj when one of its arguments is a constant, and is used to give the round-4
  constant to the register that round 4 will add to.

The schedule is expanded in place over `block` up to W_61 and rewound, W_62 and W_63 are
added term by term, and the initial hash value for H_0 and H_4 is merged into round 63, as
in `../trimmed-constants-and-tail`.

## Where the Toffolis go

| Part | Toffolis |
|---|---:|
| Rounds 4 to 63, without their constants | 29,886 |
| Round constants, 59 of them | 32,828 |
| Final additions of the initial hash value, 6 constants | 4,212 |
| Schedule, forward | 8,418 |
| Schedule, rewind | 8,418 |
| Rounds 0 to 3 | 1,535 |
| Total | 85,297 |

Constants are 43% of the circuit: about 556 Toffolis each in the rounds, where an adder with
carry qubits spends about 28. This is the part most likely to improve. A constant adder
with linear cost is known for two or three clean qubits (Gidney,
[arXiv:2507.23079](https://arxiv.org/abs/2507.23079)); with none, the known general method
costs n log n (Häner, Roetteler and Svore, [arXiv:1611.07995](https://arxiv.org/abs/1611.07995)).

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

`build.py` also runs the gates itself on 64 random blocks and compares the result with a
plain SHA-256, before it writes the file.
