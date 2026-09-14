# tests/test_mutation_vacuity_boundary.py
# THE LAST SURVIVOR IN THE GATE: THE VACUITY BOUNDARY.
#
# THE MUTANT was `measured_count(stats) <= 0` becoming `<= 1`. It survived every
# test because no fixture produced a run in which EXACTLY ONE mutant was
# measured. The existing cases measured 474, or 2, or 0 -- and at every one of
# those values the two comparisons agree.
#
# WHAT THE MUTANT WOULD DO. A run that generated one mutant and executed it
# would be reported as having measured nothing: UNKNOWN instead of a real
# verdict, so a survivor in that single mutant would be silently downgraded from
# "the suite failed to kill it" to "we could not tell". That is the vacuity
# clause turned against itself -- the mechanism written to stop a gate claiming
# too much, made to claim too little.
#
# ONE MUTANT IS NOT A HYPOTHETICAL SCALE. `mutmut run <pattern>` scoped to a
# single changed function is the normal way to iterate, and it is precisely when
# a developer is looking closely at one thing that a downgraded verdict does the
# most damage.
#
# THE LESSON REPEATS: every comparison has a boundary, and a boundary is only
# tested by a value sitting exactly on it. This is the same defect class as
# `months >= 12` and `hours >= guarantee` in the FMLA rules, in the code that
# polices them.

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cs1090a_spec_driven_development.contracts.verdict import GateVerdict
from cs1090a_spec_driven_development.mutation import (
    MutationStats,
    evaluate_mutation_stats,
    is_inconclusive,
    measured_count,
)

CLEAN = {
    "killed": 474,
    "survived": 0,
    "total": 474,
    "no_tests": 0,
    "skipped": 0,
    "suspicious": 0,
    "timeout": 0,
    "check_was_interrupted_by_user": 0,
    "segfault": 0,
}


def stats(**overrides: int) -> MutationStats:
    return MutationStats.model_validate(CLEAN | overrides)


class TestOneMeasuredMutant:
    def test_a_single_measured_mutant_is_a_real_run(self) -> None:
        """THE BOUNDARY VALUE. measured_count is exactly 1 here.

        `<= 0` says this run measured something; `<= 1` says it measured
        nothing. Only a fixture sitting on 1 can tell them apart.
        """
        subject = stats(killed=1, survived=0, total=1, no_tests=0)

        assert measured_count(subject) == 1
        assert is_inconclusive(subject) is False
        assert evaluate_mutation_stats(subject).verdict is GateVerdict.PASS

    def test_a_single_surviving_mutant_fails_rather_than_being_unknown(self) -> None:
        """THE DAMAGE THE MUTANT WOULD DO, STATED AS A REQUIREMENT.

        One mutant, generated and executed, and the suite failed to kill it.
        That is a FAILURE. Reporting UNKNOWN would let a scoped run on the one
        function a developer is actively changing pass unnoticed.
        """
        subject = stats(killed=0, survived=1, total=1, no_tests=0)

        assert measured_count(subject) == 1
        assert evaluate_mutation_stats(subject).verdict is GateVerdict.FAIL
        assert evaluate_mutation_stats(subject).reasons == ["zero_survivors"]

    def test_a_single_unmeasured_mutant_is_vacuous(self) -> None:
        """THE OTHER SIDE OF THE SAME BOUNDARY: measured_count is 0.

        One mutant generated, nothing ran against it. Both comparisons agree
        here, which is why this case alone never revealed the mutation -- it is
        included so the boundary is pinned from both directions.
        """
        subject = stats(killed=0, survived=0, total=1, no_tests=1)

        assert measured_count(subject) == 0
        assert is_inconclusive(subject) is True
        assert evaluate_mutation_stats(subject).verdict is GateVerdict.UNKNOWN

    def test_two_measured_mutants_are_a_real_run(self) -> None:
        """One past the boundary, so the pair brackets it."""
        subject = stats(killed=2, survived=0, total=2, no_tests=0)

        assert measured_count(subject) == 2
        assert is_inconclusive(subject) is False


@given(measured=st.integers(min_value=1, max_value=50))
def test_any_run_that_measured_something_is_conclusive(measured: int) -> None:
    """ACROSS THE WHOLE POSITIVE RANGE, so no single value is the reason.

    Generated at 1 as well as above it, which is what makes the boundary
    unavoidable rather than incidental.
    """
    subject = stats(killed=measured, survived=0, total=measured, no_tests=0)

    assert is_inconclusive(subject) is False


@given(total=st.integers(min_value=0, max_value=50))
def test_a_run_where_nothing_was_measured_is_always_inconclusive(total: int) -> None:
    """Every mutant unmeasured, at any scale, including zero mutants at all."""
    subject = stats(killed=0, survived=0, total=total, no_tests=total)

    assert is_inconclusive(subject) is True


@pytest.mark.parametrize(
    ("total", "no_tests", "expected"),
    [
        (0, 0, GateVerdict.UNKNOWN),
        (1, 1, GateVerdict.UNKNOWN),
        (1, 0, GateVerdict.PASS),
        (2, 1, GateVerdict.FAIL),
        (2, 0, GateVerdict.PASS),
    ],
)
def test_the_vacuity_boundary_as_a_table(total: int, no_tests: int, expected: GateVerdict) -> None:
    """THE WHOLE SMALL-NUMBER REGION IN ONE PLACE.

    (2, 1) FAILS rather than passing: one mutant ran and one did not, so the
    gate has something to judge AND an unmeasured mutant to object to. That row
    is the one that distinguishes "measured something" from "measured
    everything", which are different requirements.
    """
    subject = stats(killed=total - no_tests, survived=0, total=total, no_tests=no_tests)

    assert evaluate_mutation_stats(subject).verdict is expected
