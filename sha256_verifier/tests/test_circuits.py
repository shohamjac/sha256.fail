import hashlib

import kickmix as km
import pytest

import toy
from sha_verifier import circuits, kmx, problems


def test_load_good_circuit():
    loaded = circuits.load(toy.GOOD.encode())
    assert loaded.circuit == km.Circuit(toy.GOOD)
    assert loaded.file_sha256 == hashlib.sha256(toy.GOOD.encode()).hexdigest()
    assert loaded.sha256 == hashlib.sha256(toy.kmb(toy.GOOD)).hexdigest()
    assert loaded.summary == kmx.walk(toy.GOOD)
    assert loaded.toffoli_static == toy.TOFFOLIS
    assert km.Circuit(loaded.text) == loaded.circuit


def test_layout():
    layout = circuits.check_structure(circuits.load(toy.GOOD.encode()), toy.PROBLEM)
    assert list(layout.registers) == ['a', 'b', 'sum']
    assert list(layout.registers['sum']) == [km.q(i) for i in range(8, 12)]
    assert list(layout.scratch) == [km.q(12), km.q(13)]


def test_scratch_includes_gaps_in_the_numbering():
    """A qubit index that is skipped still counts, and is checked as scratch."""
    loaded = circuits.load((toy.GOOD + 'X q20\nX q20\n').encode())
    layout = circuits.check_structure(loaded, toy.PROBLEM)
    assert loaded.summary.num_qubits == 21
    assert list(layout.scratch) == [km.q(i) for i in range(12, 21)]


def test_registers_need_not_be_contiguous_or_ordered():
    text = toy.GOOD.replace('APPEND_TO_REGISTER q0 r0\nAPPEND_TO_REGISTER q1 r0',
                            'APPEND_TO_REGISTER q1 r0\nAPPEND_TO_REGISTER q0 r0')
    layout = circuits.check_structure(circuits.load(text.encode()), toy.PROBLEM)
    assert list(layout.registers['a']) == [km.q(1), km.q(0), km.q(2), km.q(3)]


@pytest.mark.parametrize('limits,code', [
    (circuits.Limits(max_file_bytes=100), 'file_too_large'),
    (circuits.Limits(max_operations=10), 'too_many_operations'),
    (circuits.Limits(max_qubits=13), 'too_many_qubits'),
    (circuits.Limits(max_bits=0), 'too_many_bits'),
])
def test_limits(limits, code):
    with pytest.raises(circuits.Rejected) as caught:
        circuits.load(toy.GOOD.encode(), limits)
    assert (caught.value.stage, caught.value.code) == ('load', code)
    circuits.load(toy.GOOD.encode())  # Within the default limits.


def test_default_limits_are_far_above_a_hash_circuit():
    assert circuits.LIMITS.max_qubits >= 16 * 1024 and circuits.LIMITS.max_operations >= 10_000_000


def test_count_mismatch_is_rejected(monkeypatch):
    """If Kickmix and the independent walk ever disagree, the circuit is not simulated."""
    real = kmx.walk

    def miscount(text):
        summary = real(text)
        return kmx.Summary(counts={**summary.counts, 'CCX': summary.counts['CCX'] - 1},
                           conditional_counts=summary.conditional_counts, num_qubits=summary.num_qubits,
                           num_bits=summary.num_bits, registers=summary.registers)

    monkeypatch.setattr(kmx, 'walk', miscount)
    with pytest.raises(circuits.Rejected) as caught:
        circuits.load(toy.GOOD.encode())
    assert caught.value.code == 'count_mismatch'
    assert 'Toffoli count' in caught.value.message


def test_every_allowed_instruction_passes_the_structure_check():
    extra = ('X q14\nX q14\nSWAP q14 q15\nCSWAP q14 q15 q16\nZ q14\nCZ q14 q15\nCCZ q14 q15 q16\n'
             'NEG\nNEG\nBIT_INVERT b3\nBIT_STORE0 b3\nBIT_STORE1 b3\nPUSH_CONDITION if b3\nPOP_CONDITION\n'
             'DEBUG_PRINT q14\nINFO_TAG "tag"\n')
    loaded = circuits.load((toy.GOOD + extra).encode())
    assert loaded.summary.instructions == problems.INSTRUCTIONS_WITHOUT_ROTATIONS
    circuits.check_structure(loaded, toy.PROBLEM)
