"""Loading a submitted circuit file and checking its structure against a problem.

A submission is untrusted bytes. `load` turns it into a circuit the verifier is willing to
simulate; `check_structure` checks the registers and instructions a problem requires.
Both raise `Rejected` with a stage and a short machine-readable code.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io

import kickmix as km

try:
    from compression import zstd  # Python 3.14 and later.
except ImportError:
    from backports import zstd

from sha_verifier import kmx
from sha_verifier.problems import TOFFOLI_LIKE, ProblemSpec


class Rejected(Exception):
    """A circuit failed a check. `stage` and `code` identify which."""

    def __init__(self, stage: str, code: str, message: str):
        super().__init__(message)
        self.stage, self.code, self.message = stage, code, message


@dataclasses.dataclass(frozen=True)
class Limits:
    """Resource limits on a submission. Far above what a hash circuit needs."""
    max_file_bytes: int = 512 * 1024 * 1024
    max_operations: int = 20_000_000
    max_qubits: int = 65_536
    max_bits: int = 1_048_576


LIMITS = Limits()


@dataclasses.dataclass(frozen=True)
class Loaded:
    """A circuit that parsed, with its identity and contents.

    Attributes:
        circuit: Built from `text`, every line of which `kmx.walk` accepted.
        text: The circuit as Kickmix text.
        sha256: SHA-256 of the canonical `.kmb` serialization. Identifies the circuit
            whichever format it was submitted in.
        file_sha256: SHA-256 of the circuit file, after decompression if it was compressed.
        summary: Instruction counts and registers, counted independently of Kickmix.
    """
    circuit: km.Circuit
    text: str
    sha256: str
    file_sha256: str
    summary: kmx.Summary

    @property
    def toffoli_static(self) -> int:
        return self.summary.total(TOFFOLI_LIKE)


@dataclasses.dataclass(frozen=True)
class Layout:
    """Where a problem's registers and the scratch qubits are in a circuit."""
    registers: dict[str, km.array]
    scratch: km.array


def _serialize(circuit: km.Circuit, fmt: str) -> bytes:
    buffer = io.BytesIO()
    circuit.to_file(buffer, format=fmt)
    return buffer.getvalue()


ZSTD_MAGIC = b'\x28\xb5\x2f\xfd'
PACK_LEVEL = 19


def decompress(data: bytes, limits: Limits = LIMITS) -> bytes:
    """The circuit file in `data`: decompressed if it is zstd, otherwise `data` unchanged.

    A compressed file must be exactly one zstd frame. Its decompressed size is held to the
    same limit as an uncompressed file, without ever producing more than that.
    """

    def reject(code: str, message: str) -> Rejected:
        return Rejected('load', code, message)

    limit = limits.max_file_bytes
    if len(data) > limit:
        raise reject('file_too_large', f'File is {len(data)} bytes; the limit is {limit}.')
    if not data.startswith(ZSTD_MAGIC):
        return data
    decompressor = zstd.ZstdDecompressor()
    try:
        out = decompressor.decompress(data, max_length=limit + 1)
    except zstd.ZstdError as ex:
        raise reject('unreadable', f'The file is not valid zstd: {str(ex)[:300]}') from None
    if len(out) > limit:
        raise reject('file_too_large', f'The file decompresses to more than {limit} bytes, the limit.')
    if not decompressor.eof:
        raise reject('unreadable', 'The zstd file is truncated.')
    if decompressor.unused_data:
        raise reject('unreadable', 'The zstd file has data after its end; it must be a single zstd frame.')
    # Otherwise load() would decompress again and the receipt would hash the inner frame.
    if out.startswith(ZSTD_MAGIC):
        raise reject('unreadable', 'The file is zstd-compressed twice; compress it once.')
    return out


def pack(data: bytes) -> bytes:
    """Compresses a circuit file with zstd, as `decompress` reads it."""
    return zstd.compress(data, level=PACK_LEVEL)


def load(data: bytes, limits: Limits = LIMITS) -> Loaded:
    """Parses a `.kmb` or `.kmx` file, optionally zstd-compressed, and cross-checks Kickmix's reading of it."""

    def reject(code: str, message: str) -> Rejected:
        return Rejected('load', code, message)

    data = decompress(data, limits)
    try:
        first = km.Circuit.from_file(io.BytesIO(data), format='auto')
    except Exception as ex:
        raise reject('unreadable', f'Kickmix could not parse the file: {str(ex)[:300]}') from None

    for what, value, limit in (('operations', len(first), limits.max_operations),
                               ('qubits', first.num_qubits, limits.max_qubits),
                               ('classical bits', first.num_bits, limits.max_bits)):
        if value > limit:
            code = 'too_many_' + what.split()[-1]
            raise reject(code, f'Circuit has {value} {what}; the limit is {limit}.')

    # Re-read the circuit from Kickmix's own text with an independent parser, and simulate
    # only a circuit rebuilt from that text. Nothing can then run that the walk did not see.
    text = _serialize(first, 'kmx').decode('utf-8')
    try:
        summary = kmx.walk(text)
    except kmx.KmxError as ex:
        raise reject('malformed', str(ex)) from None
    try:
        circuit = km.Circuit(text)
    except Exception as ex:
        raise reject('malformed', f'Kickmix rejected its own text form: {str(ex)[:300]}') from None
    canonical = _serialize(circuit, 'kmb')
    if circuit != first or canonical != _serialize(first, 'kmb'):
        raise reject('not_canonical', 'The circuit changes when written as text and read back.')

    stats = dict(circuit.operation_statistics())
    mismatches = [name for name, ours, theirs in (
        ('qubit count', summary.num_qubits, circuit.num_qubits),
        ('bit count', summary.num_bits, circuit.num_bits),
        ('operation count', summary.num_operations, len(circuit)),
        ('instruction counts', summary.counts, stats),
        ('Toffoli count', summary.total(TOFFOLI_LIKE), circuit.operation_statistics().num_toffoli_like),
    ) if ours != theirs]
    if mismatches:
        raise reject('count_mismatch',
                     f'Kickmix and the independent count disagree on: {", ".join(mismatches)}.')

    return Loaded(circuit=circuit, text=text, sha256=hashlib.sha256(canonical).hexdigest(),
                  file_sha256=hashlib.sha256(data).hexdigest(), summary=summary)


def check_structure(loaded: Loaded, problem: ProblemSpec) -> Layout:
    """Checks the instructions and registers `problem` requires; returns where they are."""

    def reject(code: str, message: str) -> Rejected:
        return Rejected('structure', code, message)

    forbidden = sorted(loaded.summary.instructions - problem.allowed_instructions)
    if forbidden:
        raise reject('instruction_not_allowed',
                     f'Instructions not allowed in {problem.name}: {", ".join(forbidden)}.')

    declared = list(loaded.summary.registers.values())
    names = [r.name for r in declared]
    expected = [r.name for r in problem.registers]
    if names != expected:
        raise reject('wrong_registers',
                     f'Expected registers {expected} in that order, got {names}.')

    used: set[int] = set()
    registers: dict[str, km.array] = {}
    for spec, register in zip(problem.registers, declared):
        if any(kind != 'q' for kind, _ in register.elements):
            raise reject('register_has_bits', f'Register {spec.name!r} must contain only qubits.')
        if len(register.elements) != spec.size:
            raise reject('wrong_register_size',
                         f'Register {spec.name!r} must have {spec.size} qubits, has {len(register.elements)}.')
        indices = [index for _, index in register.elements]
        if len(set(indices)) != len(indices) or used & set(indices):
            raise reject('register_overlap',
                         f'Register {spec.name!r} repeats a qubit or shares one with another register.')
        used |= set(indices)
        registers[spec.name] = km.array([km.q(i) for i in indices])

    scratch = km.array([km.q(i) for i in range(loaded.summary.num_qubits) if i not in used])
    return Layout(registers=registers, scratch=scratch)
