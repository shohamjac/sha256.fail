# Compute, copy, uncompute

The baseline (`../example`) built the textbook way. The baseline computes the hash state
directly in the `digest` register, which it may do because the problem starts `digest` at
zero. This variant computes the state in 256 scratch qubits, copies it into `digest` with
CNOTs, and runs the computation backwards to clean up.

| | This | Baseline |
|---|---:|---:|
| Qubits (Q) | 1,087 | 831 |
| Toffolis per shot (C) | 45,248 | 27,088 |
| Score (Q × C) | 49,184,576 | 22,510,128 |

More qubits and more Toffolis: the baseline dominates it. It is here as a point of
comparison, and because it is what a circuit must do if the output register cannot be
assumed to start at zero.

`build.py` imports the baseline's builder and adds the inverse of a round.
