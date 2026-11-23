# Bitcoin mining on 1,074 qubits

[`../bitcoin-mining-low-qubit`](../bitcoin-mining-low-qubit) with two more qubits, spent on
a cheaper way to add a constant. The contract is
[bitcoin-mining-v1.md](../../sha256_verifier/docs/bitcoin-mining-v1.md).

| | This | [1,072 qubits](../bitcoin-mining-low-qubit) | [Baseline](../bitcoin-mining-baseline) |
|---|---:|---:|---:|
| Qubits (Q) | 1,074 | 1,072 | 2,000 |
| Toffolis per shot (C) | 473,501 | 522,269 | 262,158 |
| Score (Q × C) | 508,540,074 | 559,872,368 | 524,316,000 |
| Reaction depth (D) | 130,657 | 130,657 | 108,224 |
| Operations | 5,486,555 | 5,688,103 | 3,526,903 |

Verified at full strength: 2,848 shots on 16 real blocks and 1,048,576 random shots, all
correct. The official receipt is recorded in `../../results/bitcoin-mining-v1/` when this
directory is merged.

## What the two qubits buy

The 1,072-qubit circuit measures each intermediate hash away and removes the phase later,
so that it holds one compression at a time. Its largest step is the header's second block,
which has every qubit in use from round 30 to round 63. In those 34 rounds a round constant
has no carry qubits to use and is added as signed binary digits: 558 Toffolis on average,
102 times in the whole circuit.

With two clean qubits a constant can be added in 3n − 7 Toffolis, 89 for 32 bits, by the
adder of Gidney, "A classical-quantum adder with constant workspace and linear gates"
([arXiv:2507.23079](https://arxiv.org/abs/2507.23079)). That is the only change here, and
it saves 48,768 Toffolis.

## The constant adder

To add a constant `d` whose lowest bit is one (lower zero bits are skipped):

1. **Ripple with two carry qubits.** The carry into bit k is computed from the carry into
   bit k − 1, used, XORed into a borrowed busy qubit `g_k`, and measured in the X basis.
   The two carry qubits take turns. Each measurement leaves the phase `(−1)^(m_k c_k)`,
   with `m_k` the measured bit and `c_k` the carry. One Toffoli per carry.
2. **`Z` on `g_k` when `m_k` is one.**
3. **XOR every carry into the borrowed qubits a second time,** which restores them. The
   carries of `x + d` are the borrows of `(x + d) − d`, so they can be computed from the
   sum. The borrowed qubits are the workspace: each Toffoli is applied twice, once before
   its control is toggled by the carry below and once after, so the control's own unknown
   value cancels (Häner, Roetteler and Svore,
   [arXiv:1611.07995](https://arxiv.org/abs/1611.07995)). Two Toffolis per carry.
4. **`Z` on `g_k` when `m_k` is one, again.** The two `Z`s see `g_k` with and without the
   carry, so together they are `(−1)^(m_k c_k)`, which removes the phase of step 1.

The borrowed qubits are 30 qubits of a state word that the addition does not touch. To
undo an addition, the negated constant is added.

`build.py` tests the adder by itself at seven widths, on random numbers, constants and
borrowed values: the sum, the borrowed qubits, the carry qubits and the phase.

## Where the qubits go

| Qubits | What |
|---:|---|
| 48 | `extranonce`, idle |
| 256 | mid, kept for the addition that ends the compression |
| 256 | the state being worked on |
| 512 | the message schedule, which runs in place over the nonce and the root's last word |
| 2 | the constant adder's carries |
| **1,074** | |

## Where the Toffolis go

| Part | Count |
|---|---:|
| Coinbase block: computed 4 times at 22,624, uncomputed once at 27,088 | 117,584 |
| Root: computed 4 times and uncomputed once, 21,969 each | 109,845 |
| Header's first block: computed 3 times and uncomputed once, 22,624 each | 90,496 |
| Header's second block: computed once with its schedule rewound (41,568), then computed and uncomputed (69,880) | 111,448 |
| Hash: computed and uncomputed, 21,969 each | 43,938 |
| The comparison, done twice | 190 |
| Total | 473,501 |

No Toffoli is under a classical condition, so the count executed per shot is the count in
the circuit.

## Known slack

- **Rounds 30 to 63 still pay for having no scratch.** Their other additions keep carries in
  the operand's wires at 61 Toffolis each, against 31 with carry qubits, and Ch and Maj are
  computed twice. Each further clean qubit given to carries saves about one Toffoli per
  addition.
- **Classical inputs are still treated as quantum,** except for the padding.
- **The whole hash is computed.** Only `H_5`, `H_6` and `H_7` are compared.

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

`build.py` imports the generator of `../bitcoin-mining-low-qubit`, and through it those of
`../bitcoin-mining-baseline` and `../zero-scratch`.
