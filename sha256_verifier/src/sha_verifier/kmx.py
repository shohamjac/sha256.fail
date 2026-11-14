"""An independent reading of Kickmix circuit text (`.kmx`).

The verifier does not rely on Kickmix alone to say what is in a circuit. This module
walks the text line by line with its own strict grammar and produces its own counts,
which `circuits.load` compares against Kickmix's. It shares no code with Kickmix.

Format: https://github.com/quantumlib/Qualtran/blob/main/docs/kickmix/kickmix_format.md
"""

from __future__ import annotations

import dataclasses
import re

# Target kinds each ordinary instruction takes, in order: q = qubit, b = bit.
# All of these accept an optional trailing `if b<N>` condition.
_SHAPES: dict[str, str] = {
    'X': 'q', 'Z': 'q', 'R': 'q',
    'CX': 'qq', 'CZ': 'qq', 'SWAP': 'qq',
    'CCX': 'qqq', 'CCZ': 'qqq', 'CSWAP': 'qqq',
    'NEG': '',
    'HMR': 'qb',
    'BIT_INVERT': 'b', 'BIT_STORE0': 'b', 'BIT_STORE1': 'b',
}

# Instructions that define registers rather than act; Kickmix does not count them as operations.
METADATA = frozenset({'REGISTER', 'APPEND_TO_REGISTER'})

KNOWN = frozenset(_SHAPES) | METADATA | {
    'PUSH_CONDITION', 'POP_CONDITION', 'DEBUG_PRINT', 'INFO_TAG', 'Z_POW'}

_NAME = re.compile(r'[A-Z][A-Z0-9_]*\Z')
_ID = re.compile(r'[qbr](0|[1-9][0-9]*)\Z')
_EXPONENT = re.compile(r'[-+]?[0-9]+\.[0-9]+\Z')
_ESCAPE = re.compile(r'\\(.?)')


class KmxError(ValueError):
    """The text is not a well-formed circuit."""


@dataclasses.dataclass(frozen=True)
class Register:
    name: str | None  # None when the circuit never names it.
    elements: tuple[tuple[str, int], ...]  # ('q', 3) is qubit 3; ('b', 3) is bit 3.


@dataclasses.dataclass(frozen=True)
class Summary:
    """What a circuit contains, as counted by this module.

    Attributes:
        counts: Number of occurrences of each operation. Excludes register metadata.
        conditional_counts: Of those, how many sit under an `if` or inside a
            `PUSH_CONDITION` block, and so may be skipped when the circuit runs.
        num_qubits: Highest qubit index mentioned anywhere, plus one.
        num_bits: Highest classical bit index mentioned anywhere, plus one.
        registers: Register id to its name and elements, in id order.
    """
    counts: dict[str, int]
    conditional_counts: dict[str, int]
    num_qubits: int
    num_bits: int
    registers: dict[int, Register]

    @property
    def num_operations(self) -> int:
        return sum(self.counts.values())

    @property
    def instructions(self) -> frozenset[str]:
        """Every instruction name the circuit uses, including register metadata."""
        return frozenset(self.counts) | (METADATA if self.registers else frozenset())

    def total(self, names: frozenset[str]) -> int:
        return sum(self.counts.get(n, 0) for n in names)

    def conditional_total(self, names: frozenset[str]) -> int:
        return sum(self.conditional_counts.get(n, 0) for n in names)


def walk(text: str) -> Summary:
    """Reads circuit text; raises `KmxError` at the first line that is not valid."""
    counts: dict[str, int] = {}
    conditional: dict[str, int] = {}
    reg_names: dict[int, str | None] = {}
    reg_elements: dict[int, list[tuple[str, int]]] = {}
    max_q = max_b = -1
    depth = 0  # Open PUSH_CONDITION blocks.

    for number, raw in enumerate(text.split('\n'), start=1):
        line = raw.split('#', 1)[0].strip(' \t')
        if not line:
            continue

        def fail(why: str) -> KmxError:
            return KmxError(f'Line {number}: {why}: {raw.strip()[:120]!r}')

        quoted = None
        if '"' in line:
            line, _, rest = line.partition('"')
            if not rest.endswith('"') or '"' in rest[:-1]:
                raise fail('malformed quoted text')
            quoted = rest[:-1]
            if any(m.group(1) not in 'BQPnr' or not m.group(1) for m in _ESCAPE.finditer(quoted)):
                raise fail('bad escape in quoted text')

        tokens = line.split()
        if not tokens or not _NAME.match(tokens[0]):
            raise fail('expected an instruction name')
        name, targets = tokens[0], tokens[1:]
        if name not in KNOWN:
            raise fail('unknown instruction')

        condition = None
        if 'if' in targets:
            if targets.index('if') != len(targets) - 2 or not targets[-1].startswith('b'):
                raise fail('malformed condition')
            condition, targets = targets[-1], targets[:-2]

        parsed: list[tuple[str, int]] = []
        for target in (*targets, *([condition] if condition else [])):
            if _ID.match(target):
                kind, index = target[0], int(target[1:])
                parsed.append((kind, index))
                if kind == 'q':
                    max_q = max(max_q, index)
                elif kind == 'b':
                    max_b = max(max_b, index)
            elif not (name == 'Z_POW' and _EXPONENT.match(target)):
                raise fail('malformed target')
        if condition:
            parsed.pop()
        kinds = ''.join(kind for kind, _ in parsed)

        if quoted is not None and name not in ('REGISTER', 'INFO_TAG'):
            raise fail('unexpected quoted text')

        if name == 'REGISTER':
            if kinds != 'r' or condition:
                raise fail('expected one register id')
            rid = parsed[0][1]
            if reg_names.get(rid) is not None:
                raise fail('register named twice')
            reg_names[rid] = quoted
            reg_elements.setdefault(rid, [])
            continue
        if name == 'APPEND_TO_REGISTER':
            if kinds not in ('qr', 'br') or condition:
                raise fail('expected a qubit or bit, then a register id')
            rid = parsed[1][1]
            reg_names.setdefault(rid, None)
            reg_elements.setdefault(rid, []).append(parsed[0])
            continue

        if name == 'PUSH_CONDITION':
            if kinds or not condition:
                raise fail('expected only a condition')
            depth += 1
        elif name == 'POP_CONDITION':
            if kinds or condition:
                raise fail('expected no arguments')
        elif name == 'INFO_TAG':
            if kinds or condition or quoted is None:
                raise fail('expected only quoted text')
        elif name == 'DEBUG_PRINT':
            if kinds not in ('', 'q', 'b'):
                raise fail('expected at most one qubit or bit')
        elif name == 'Z_POW':
            if kinds != 'q' or len(targets) != 2 or not _EXPONENT.match(targets[1]):
                raise fail('expected a qubit and an exponent')
        else:
            if kinds != _SHAPES[name]:
                raise fail(f'expected targets of kinds {_SHAPES[name]!r}')
            if len(set(parsed)) != len(parsed):
                raise fail('the same qubit is used twice')

        counts[name] = counts.get(name, 0) + 1
        if condition or (depth and name not in ('PUSH_CONDITION', 'POP_CONDITION', 'INFO_TAG')):
            conditional[name] = conditional.get(name, 0) + 1
        if name == 'POP_CONDITION' and depth:
            depth -= 1

    registers = {rid: Register(reg_names[rid], tuple(reg_elements[rid])) for rid in sorted(reg_names)}
    return Summary(counts=counts, conditional_counts=conditional, num_qubits=max_q + 1,
                   num_bits=max_b + 1, registers=registers)
