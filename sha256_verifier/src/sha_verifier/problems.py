"""The benchmark problems the verifier knows.

A problem fixes what a circuit must do: its registers, the function it must compute, the
instructions it may use, and a fixed set of directed test inputs. Problems are versioned
by name; a change to any of these is a new problem with a new name, never an edit.

Adding a hash function means adding one `ProblemSpec` here.
"""

from __future__ import annotations

import dataclasses
from typing import Callable, Literal

import numpy as np

from sha_verifier import bits, sha2

# Register bit arrays by register name; each is boolean with shape `(size, n_shots)`.
RegisterBits = dict[str, np.ndarray]

# Every Kickmix 1.0.0 instruction except `Z_POW`. Hash circuits need no rotations, and
# excluding them keeps every phase exactly +1 or -1 and the cost a plain Toffoli count.
INSTRUCTIONS_WITHOUT_ROTATIONS = frozenset({
    'X', 'CX', 'CCX', 'SWAP', 'CSWAP',
    'Z', 'CZ', 'CCZ', 'NEG',
    'R', 'HMR',
    'BIT_INVERT', 'BIT_STORE0', 'BIT_STORE1',
    'PUSH_CONDITION', 'POP_CONDITION',
    'REGISTER', 'APPEND_TO_REGISTER', 'DEBUG_PRINT', 'INFO_TAG',
})

# Instructions counted as one Toffoli each in the cost.
TOFFOLI_LIKE = frozenset({'CCX', 'CCZ', 'CSWAP'})


@dataclasses.dataclass(frozen=True)
class RegisterSpec:
    """A named register a circuit must declare.

    Roles:
        input: Holds a test input. Must hold the same value when the circuit ends.
        output: Starts as all zeros. Must hold the reference value when the circuit ends.
    """
    name: str
    size: int
    role: Literal['input', 'output']


@dataclasses.dataclass(frozen=True)
class ProblemSpec:
    """A benchmark problem.

    Qubits outside the declared registers are scratch: they start and must end as zero.

    Attributes:
        registers: The registers a circuit must declare, exactly these and in this order.
        reference: Maps input register bits to the expected output register bits.
        directed_inputs: Returns the fixed directed test inputs, as input register bits.
        allowed_instructions: Kickmix instruction names a circuit may contain.
    """
    name: str
    title: str
    registers: tuple[RegisterSpec, ...]
    reference: Callable[[RegisterBits], RegisterBits]
    directed_inputs: Callable[[], RegisterBits]
    allowed_instructions: frozenset[str] = INSTRUCTIONS_WITHOUT_ROTATIONS

    @property
    def inputs(self) -> tuple[RegisterSpec, ...]:
        return tuple(r for r in self.registers if r.role == 'input')

    @property
    def outputs(self) -> tuple[RegisterSpec, ...]:
        return tuple(r for r in self.registers if r.role == 'output')


# sha256-compress-v1: one SHA-256 compression of a 512-bit block from the standard
# initial hash value. See docs/sha256-compress-v1.md.


def _sha256_compress_reference(inputs: RegisterBits) -> RegisterBits:
    block = bits.bits_to_words(inputs['block'], 32)
    state = np.array(sha2.SHA256.iv, dtype=np.uint32)
    return {'digest': bits.words_to_bits(sha2.compress(sha2.SHA256, state, block))}


def _sha256_compress_directed_blocks() -> np.ndarray:
    """The directed test blocks as words, shape `(n, 16)`. The order is part of the contract."""
    params = sha2.SHA256
    full = 0xFFFFFFFF
    rows: list[list[int]] = []

    # Constant blocks: every word the same pattern.
    for pattern in (0, full, 0x55555555, 0xAAAAAAAA, 0x80000000, 0x7FFFFFFF, 1, 0xFFFFFFFE):
        rows.append([pattern] * 16)

    # One bit set, and one bit clear, for each of the 512 block bits.
    for j in range(16):
        for k in range(32):
            rows.append([(1 << k) if i == j else 0 for i in range(16)])
    for j in range(16):
        for k in range(32):
            rows.append([full ^ (1 << k) if i == j else full for i in range(16)])

    # One word all ones in an otherwise zero block, and the reverse.
    for j in range(16):
        rows.append([full if i == j else 0 for i in range(16)])
        rows.append([0 if i == j else full for i in range(16)])

    # Blocks that make the first additions carry all the way: W_t = -K_t and W_t = ~K_t.
    rows.append([-params.k[t] & full for t in range(16)])
    rows.append([~params.k[t] & full for t in range(16)])

    # Padded messages of every length that fits one block, so the task agrees with the
    # ordinary SHA-256 of short messages: bytes 0, 1, 2, ... and then all-0xff bytes.
    for message_length in range(56):
        for message in (bytes(range(message_length)), b'\xff' * message_length):
            rows.append(sha2.words_from_bytes(params, sha2.pad(params, message))[0].tolist())
    rows.append(sha2.words_from_bytes(params, sha2.pad(params, b'abc'))[0].tolist())

    return np.array(rows, dtype=np.uint32)


def _sha256_compress_directed_inputs() -> RegisterBits:
    return {'block': bits.words_to_bits(_sha256_compress_directed_blocks())}


SHA256_COMPRESS_V1 = ProblemSpec(
    name='sha256-compress-v1',
    title='SHA-256 compression of one 512-bit block',
    registers=(
        RegisterSpec('block', 512, 'input'),
        RegisterSpec('digest', 256, 'output'),
    ),
    reference=_sha256_compress_reference,
    directed_inputs=_sha256_compress_directed_inputs,
)

PROBLEMS: dict[str, ProblemSpec] = {p.name: p for p in (SHA256_COMPRESS_V1,)}


def get(name: str) -> ProblemSpec:
    try:
        return PROBLEMS[name]
    except KeyError:
        raise ValueError(f'Unknown problem {name!r}. Known problems: {sorted(PROBLEMS)}.') from None
