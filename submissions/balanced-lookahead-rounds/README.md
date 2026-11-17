# Balanced lookahead rounds

A circuit that is short on both counts at once: reaction depth below 1,000 and fewer than
100,000 Toffolis. The circuits built for one track pay heavily on the other.

| | This | Lean lookahead rounds | Trimmed constants and tail |
|---|---:|---:|---:|
| Qubits | 1,113 | 826 | 829 |
| Toffolis | 84,150 | 1,888,398 | 26,067 |
| Reaction depth | 728 | 581 | 3,892 |

It is not on the front of either track: it uses more qubits than both of the others, more
Toffolis than the one and more depth than the other. What it has is both limits together.
The Toffoli count is exact, not a mean: no Toffoli is under a classical condition.

## How it works

The fewest-Toffoli circuits use ripple adders, whose carries wait for one another. The
shallow circuits build values again and again in helper qubits, to avoid storing them. This
one stores them.

- **Every AND is computed once and measured away.** Each AND goes into a qubit of its own.
  When the step that needed it is over, the qubit is measured in the X basis and the phase
  fixed by a CZ on the AND's two inputs. That costs no Toffoli. A tree of ANDs is measured
  from the top down, so it costs as many reactions as the tree is deep.
- **Everything in between is an XOR.** A value is a row of bits, each the XOR of register
  qubits and AND qubits. Ch, Maj, the carry rows of carry-save steps and the nodes of an
  adder's prefix tree are all of that form, so none of them is stored as such.
- **Rounds.** e' and a' go into fresh registers, each from one carry-save sum and one carry
  tree:

      e' = h + (d + K + W + Σ1(e) + Ch(e, f, g))        h = e' − (the same rows)
      a' = −d + (e' + Σ0(a) + Maj(a, b, c))             d = (the same rows) − a'

  The sum in brackets is reduced to two rows once and used twice. The registers for d and h
  are measured in the X basis, and the phase is fixed directly on the bits of the sum on
  the right: a Z on every qubit that a bit is the XOR of, carries included. No copy of the
  value is made.
- **Schedule.** W<sub>t</sub> is formed in a fresh register and the register of
  W<sub>t−16</sub> is measured away against it. At the end the same is done backwards.
- **Carry trees.** A Sklansky network has AND-depth 5 and 158 ANDs for 32 bits, a
  Brent–Kung network depth 9 and 104. The sums of a round and the clearing step of
  the rewind use Sklansky; the rest use Brent–Kung.

## Where the depth and the Toffolis go

A round has AND-depth 8: Ch, two carry-save steps, and the tree's 5. After 64 rounds that is
509. The phase corrections of the schedule run a little ahead of it, 11 per word, and stand
at 536 when the last word is formed. The rewind is a chain of 24 steps of 8 reactions each,
which gives 728.

Toffolis: 833 a round (two Sklansky and two Brent–Kung trees, and about 310 for Ch, Maj and
the carry-save steps), 14,352 for the schedule, 16,896 for its rewind and 1,174 for the
final addition.

Qubits: 768 for the registers, and at the peak 345 more: 124 for Ch and the carry rows of a
round's shared sum, 31 for one more carry row, 158 for a Sklansky tree and 32 for the new
register.

## Other settings

The trees are chosen by eight constants at the top of `build.py`. Measured:

| Change | Qubits | Depth | Toffolis |
|---|---:|---:|---:|
| As submitted | 1,113 | 728 | 84,150 |
| Sklansky for clearing in rounds too | 1,113 | 728 | 90,570 |
| Sklansky for every sum but the last ([`../balanced-lookahead-sklansky`](../balanced-lookahead-sklansky)) | 1,113 | 717 | 98,202 |
| Brent–Kung for everything in a round ([`../balanced-lookahead-brent-kung`](../balanced-lookahead-brent-kung)) | 1,060 | 905 | 77,304 |
| Brent–Kung for the clearing step of the rewind | 1,113 | 798 | 88,026 |
| Ripple carries for clearing in the schedule | 1,113 | 1,139 | 88,506 |

The last row is why the schedule does not use ripple carries: clearing one word passes its
phase corrections to the next, and with ripple carries that chain grows by 19 a word.

## Rebuild and verify

`build.py` imports the constants and the hashlib check from `../example/build.py`. It checks
the circuit twice: once as written, and once without its resets, since a reset would hide
scratch that was not cleared.

```bash
uv run --project ../../sha256_verifier python build.py
```

```bash
uv run --project ../../sha256_verifier sha-verify pack circuit.kmb --rm
```

```bash
uv run --project ../../sha256_verifier sha-verify run circuit.kmb.zst
```
