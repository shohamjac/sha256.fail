"""Pins Kickmix's reaction depth, which the reaction-depth track scores.

The problem spec defines a circuit's reaction depth as what `Circuit.reaction_depth()` of
Kickmix 1.0.0 returns. These cases come from Kickmix's own tests and Craig Gidney's talk
"How to eat magic states" (APS March Meeting 2026). If a Kickmix upgrade changes the rule,
they fail, rather than scores shifting unnoticed.
"""

import kickmix
import pytest

TALK = 'CCX q0 q1 q2\nCCX q2 q3 q4\nCCX q0 q1 q2\nCCX q2 q3 q4\n'


@pytest.mark.parametrize('text, depth', [
    ('', 0),
    ('CX q0 q1\nCZ q1 q2\nSWAP q0 q2\n', 0),  # Clifford gates add no reactions.
    ('CCX q0 q1 q2\n', 1),
    # Four Toffolis in a row, each not commuting with the next: 2 with auto-corrected
    # Toffolis (not 4), however often the pattern repeats.
    (TALK, 2),
    (TALK * 2, 2),
    (TALK * 4, 2),
    ('CCX q0 q1 q2\nCCX q4 q3 q2\n', 1),  # A shared target.
    # The Toffoli leaves q0 one reaction deep; measuring it adds a second, and a gate
    # conditioned on the result inherits both.
    ('CCX q0 q1 q2\nHMR q0 b0\n', 2),
    ('CCX q0 q1 q2\nHMR q0 b0\nCX q3 q4 if b0\nBIT_STORE0 b0\n', 2),
    # Depth that nothing later depends on is dropped: here the measured bit is overwritten.
    ('CCX q0 q1 q2\nHMR q0 b0\nBIT_STORE0 b0\n', 1),
])
def test_kickmix_reaction_depth(text, depth):
    assert kickmix.Circuit(text).reaction_depth() == depth
