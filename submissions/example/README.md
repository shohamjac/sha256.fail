# Baseline submission

A plain, readable SHA-256 compression circuit for the problem `sha256-compress-v1`. It is the
starting point of the leaderboard and an example of what a submission looks like.

| | |
|---|---:|
| Qubits (Q) | 831 |
| Toffolis per shot (C) | 27,088 |
| Score (Q × C) | 22,510,128 |
| Operations | 350,816 |

Verified at full strength: 1,179 directed and 1,048,576 random blocks, all correct. The
receipt is in `../../results/sha256-compress-v1/`.

## Files

| File | What |
|---|---|
| `circuit.kmb` | The circuit that is verified |
| `meta.json` | Name, authors, kind, problem and description, carried into the receipt |
| `build.py` | How the circuit was generated. Never run by the verifier. |

## How it works

- The working state lives in the `digest` register. It is set to the initial hash value, run
  through the 64 rounds in place, and has the initial hash value added back. A round is
  reversible given its message word, so the rounds are never uncomputed.
- The message schedule is expanded in place over `block` (word W_t overwrites W_(t-16)) and
  run backwards after the last round to restore the block.
- Additions are Kickmix's ripple-carry adder, which clears its carries by measurement. Ch and
  Maj cost one AND per bit, also cleared by measurement.
- Scratch is one 32-qubit temporary plus the adder's 31 carries: 63 qubits beyond the 768 in
  the registers.

Where the Toffolis go: 64 rounds at 280 each (17,920), 96 schedule steps (48 forward, 48
back) at 93 each (8,928), and 240 for the eight final additions.

## Known slack

This is a baseline, not an optimized circuit. For example, the first round operates on the
fixed initial hash value until the first message word is added, so some of its gates never do
anything; a carry there is always zero. Removing such a gate gives an equally correct circuit.

## Rebuild and verify

```bash
uv run --project ../../sha256_verifier python build.py
```

```bash
uv run --project ../../sha256_verifier sha-verify run circuit.kmb
```

`build.py` checks the circuit against `hashlib.sha256` and does not import the verifier, so
the circuit and the verifier's reference function are two independent implementations.
