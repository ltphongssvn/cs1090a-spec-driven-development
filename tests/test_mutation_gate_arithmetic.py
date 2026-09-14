# tests/test_mutation_gate_arithmetic.py
# THE GATE'S OWN ARITHMETIC AND EVIDENCE, WHERE ONE-VARIABLE FIXTURES CANNOT SEE.
#
# THREE SURVIVOR CLASSES IN mutation.py, each hidden for a different reason.
#
# --- SUMS THAT NEED MORE THAN ONE NON-ZERO TERM -------------------------------
#
#   suspicious + timeout + segfault  ->  suspicious + timeout - segfault
#   suspicious + timeout + segfault  ->  suspicious - timeout + segfault
#
# Every existing test set ONE of the three and left the others at zero, so every
# operator produced the same answer: `1 + 0 - 0` and `1 + 0 + 0` are both 1. A
# sum is only tested when at least two terms are non-zero AND the terms differ.
#
# --- A SUBTRACTION WHOSE SIGN NEVER MATTERED ----------------------------------
#
#   total - no_tests  ->  total + no_tests
#
# measured_count feeds one decision: whether the run was vacuous. With total=474
# both 471 and 477 are comfortably positive, so the verdict is identical. The
# operator only reveals itself where the result crosses zero, which needs a run
# whose mutants were ALL unmeasured.
#
# --- EVIDENCE FIELDS NOBODY READ ----------------------------------------------
#
#   observed=stats.no_tests -> None,  expected=0 -> None,  arguments deleted
#
# The same class that survived in the FMLA rules, for the same reason: the tests
# asserted VERDICTS and REASONS, never the numbers that justify them. The gate's
# own record is evidence, and evidence nobody asserts can silently go blank.
#
# check_named RETURNS Check, NOT object. It was first written returning object
# and each assertion carried a type: ignore[attr-defined] -- three suppressions
# caused by one lazy annotation, in a file whose subject is unasserted evidence.

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cs1090a_spec_driven_development.contracts.verdict import (
    Check,
    CheckVerdict,
    GateVerdict,
)
from cs1090a_spec_driven_development.mutation import (
    MutationStats,
    evaluate_mutation_stats,
    indeterminate_count,
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


def check_named(name: str, **overrides: int) -> Check:
    verdict = evaluate_mutation_stats(stats(**overrides))
    return next(check for check in verdict.checks if check.id == name)


# --- Properties ---------------------------------------------------------------


@given(
    suspicious=st.integers(min_value=0, max_value=20),
    timeout=st.integers(min_value=0, max_value=20),
    segfault=st.integers(min_value=0, max_value=20),
)
def test_indeterminate_is_the_sum_of_all_three_outcomes(
    suspicious: int, timeout: int, segfault: int
) -> None:
    """THE SUM, STATED INDEPENDENTLY AND ACROSS DISTINCT VALUES.

    Generated triples include cases where the three differ, which is what makes
    `a + b - c` and `a - b + c` disagree with `a + b + c`.
    """
    subject = stats(suspicious=suspicious, timeout=timeout, segfault=segfault)

    assert indeterminate_count(subject) == suspicious + timeout + segfault


@given(
    total=st.integers(min_value=0, max_value=500),
    no_tests=st.integers(min_value=0, max_value=500),
)
def test_measured_is_total_less_the_unmeasured(total: int, no_tests: int) -> None:
    assert measured_count(stats(total=total, no_tests=no_tests)) == total - no_tests


# --- The sum, with several non-zero terms -------------------------------------


class TestIndeterminateArithmetic:
    def test_all_three_outcomes_are_counted_together(self) -> None:
        """DISTINCT VALUES, so no pair of operators agrees by accident.

        1 + 2 + 4 is 7; 1 + 2 - 4 is -1; 1 - 2 + 4 is 3. Equal values would let
        a sign error hide.
        """
        assert indeterminate_count(stats(suspicious=1, timeout=2, segfault=4)) == 7

    def test_segfaults_add_rather_than_subtract(self) -> None:
        """THE `- segfault` MUTANT, ISOLATED.

        BOTH SIDES ARE COMPARED. An earlier version computed a baseline and
        never used it, which ruff caught as F841 -- a test that measures
        something and then ignores it is weaker than it looks.
        """
        without = indeterminate_count(stats(suspicious=3))
        with_segfault = indeterminate_count(stats(suspicious=3, segfault=2))

        assert without == 3
        assert with_segfault == 5
        assert with_segfault > without

    def test_timeouts_add_rather_than_subtract(self) -> None:
        without = indeterminate_count(stats(suspicious=3, segfault=1))
        with_timeout = indeterminate_count(stats(suspicious=3, timeout=2, segfault=1))

        assert without == 4
        assert with_timeout == 6
        assert with_timeout > without

    def test_suspicious_results_add_rather_than_subtract(self) -> None:
        without = indeterminate_count(stats(timeout=2, segfault=1))
        with_suspicious = indeterminate_count(stats(suspicious=3, timeout=2, segfault=1))

        assert without == 3
        assert with_suspicious == 6
        assert with_suspicious > without

    def test_none_of_the_three_yields_zero(self) -> None:
        assert indeterminate_count(stats()) == 0

    def test_a_mix_of_outcomes_fails_the_gate_once(self) -> None:
        """ONE CHECK, NOT THREE. The three outcomes share a verdict because they
        share a cause: the mutant's fate is unknown.
        """
        verdict = evaluate_mutation_stats(stats(suspicious=1, timeout=2, segfault=3, killed=468))

        assert verdict.reasons == ["no_indeterminate_outcomes"]


class TestMeasuredArithmetic:
    def test_a_run_where_every_mutant_was_unmeasured_is_vacuous(self) -> None:
        """THE `total + no_tests` MUTANT, WHICH NEEDS THE RESULT TO CROSS ZERO.

        Three mutants, none measured: total - no_tests is 0 and the run judged
        nothing. The mutant computes 6 and would report a real verdict over a
        run that executed nothing at all.
        """
        subject = stats(killed=0, survived=0, total=3, no_tests=3)

        assert measured_count(subject) == 0
        assert is_inconclusive(subject) is True
        assert evaluate_mutation_stats(subject).verdict is GateVerdict.UNKNOWN

    def test_a_partially_measured_run_is_still_judged(self) -> None:
        """THE OTHER SIDE: some mutants ran, so the gate has something to say --
        and what it says is that the unmeasured ones are a failure.
        """
        subject = stats(killed=2, survived=0, total=3, no_tests=1)

        assert measured_count(subject) == 2
        assert is_inconclusive(subject) is False
        assert evaluate_mutation_stats(subject).reasons == ["every_mutant_measured"]

    def test_an_empty_run_is_vacuous(self) -> None:
        assert is_inconclusive(stats(killed=0, survived=0, total=0)) is True

    def test_a_fully_measured_run_is_not_vacuous(self) -> None:
        assert is_inconclusive(stats()) is False


# --- Evidence -----------------------------------------------------------------


class TestCheckEvidence:
    def test_the_measured_check_reports_the_unmeasured_count_against_zero(self) -> None:
        """observed AND expected, both of which mutated to None and survived."""
        check = check_named("every_mutant_measured", no_tests=5, killed=469)

        assert check.observed == 5
        assert check.expected == 0

    def test_the_measured_check_reports_zero_on_a_clean_run(self) -> None:
        check = check_named("every_mutant_measured")

        assert check.observed == 0
        assert check.verdict is CheckVerdict.PASS

    def test_the_indeterminate_check_reports_the_total_against_zero(self) -> None:
        check = check_named("no_indeterminate_outcomes", suspicious=1, timeout=2, killed=471)

        assert check.observed == 3
        assert check.expected == 0

    def test_the_indeterminate_check_reports_zero_on_a_clean_run(self) -> None:
        check = check_named("no_indeterminate_outcomes")

        assert check.observed == 0
        assert check.verdict is CheckVerdict.PASS

    def test_the_survivor_check_reports_the_count_against_zero(self) -> None:
        check = check_named("zero_survivors", survived=9, killed=465)

        assert check.observed == 9
        assert check.expected == 0

    def test_the_context_checks_report_the_run_totals(self) -> None:
        """EACH ID AND EACH VALUE, because a mutant blanked them one at a time."""
        verdict = evaluate_mutation_stats(stats(killed=470, survived=4, skipped=7))
        context = {
            check.id: check.observed
            for check in verdict.checks
            if check.verdict is CheckVerdict.INFORMATIONAL
        }

        assert context == {"mutants_killed": 470, "mutants_total": 474, "skipped": 7}

    def test_every_check_carries_an_identifier(self) -> None:
        """id=None MUTANTS. A check the reasons list cannot name is not evidence."""
        verdict = evaluate_mutation_stats(stats(survived=1, killed=473))

        assert all(check.id for check in verdict.checks)

    def test_the_deciding_checks_are_exactly_these_three(self) -> None:
        """A FOURTH APPEARING, OR ONE VANISHING, IS A CONTRACT CHANGE."""
        verdict = evaluate_mutation_stats(stats())
        deciding = [
            check.id for check in verdict.checks if check.verdict is not CheckVerdict.INFORMATIONAL
        ]

        assert deciding == [
            "zero_survivors",
            "every_mutant_measured",
            "no_indeterminate_outcomes",
        ]

    def test_a_vacuous_run_emits_only_informational_checks(self) -> None:
        """THAT IS HOW UNKNOWN IS DERIVED rather than special-cased: with nothing
        deciding, the contract itself returns UNKNOWN.
        """
        verdict = evaluate_mutation_stats(stats(killed=0, survived=0, total=0))

        assert all(check.verdict is CheckVerdict.INFORMATIONAL for check in verdict.checks)
        assert verdict.verdict is GateVerdict.UNKNOWN


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("survived", "zero_survivors"),
        ("no_tests", "every_mutant_measured"),
        ("suspicious", "no_indeterminate_outcomes"),
        ("timeout", "no_indeterminate_outcomes"),
        ("segfault", "no_indeterminate_outcomes"),
    ],
)
def test_each_failing_outcome_maps_to_its_reason(field: str, reason: str) -> None:
    """THE WHOLE MAPPING IN ONE TABLE, so an outcome added without a reason is
    visible as a missing row rather than as silence."""
    verdict = evaluate_mutation_stats(stats(**{field: 1}, killed=473))

    assert reason in verdict.reasons
