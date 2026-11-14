# Low-qubit adder

The baseline (`../example`) with its adder replaced by the ripple-carry adder of Cuccaro,
Draper, Kutin and Moulton ([arXiv:quant-ph/0410184](https://arxiv.org/abs/quant-ph/0410184)).
That adder keeps each carry in the addend and needs one extra qubit instead of 31, at two
Toffolis per bit instead of one.

| | This | Baseline |
|---|---:|---:|
| Qubits (Q) | 801 | 831 |
| Toffolis per shot (C) | 50,224 | 27,088 |
| Score (Q × C) | 40,229,424 | 22,510,128 |

Fewer qubits, more Toffolis: neither circuit dominates the other, so both are on the Pareto
front.

`build.py` imports the baseline's builder and overrides its one `add` method.
