# tests/test_mutation_gate.py
# THE GATE THAT ENFORCES ZERO SURVIVORS, DRIVEN BY ITS TEST.
#
# WHY A GATE AT ALL. Zero survivors was reached by hand: run mutmut, read the
# number, be satisfied. A standard nobody enforces lasts until the first
# inconvenient afternoon -- and this repository has already watched a mutation
# gate report green across ZERO mutants, which is the failure this module exists
# to make impossible.
#
# THE ANTI-VACUITY CLAUSE IS THE POINT, not a refinement of it. mutmut's own
# artifact makes the trap plain:
#
#   {"killed": 0, "survived": 0, "total": 0, "no_tests": 0, ...}
#
# That document satisfies "survived == 0" perfectly, and it describes a run that
# measured nothing.
#
# no_tests IS A SECOND VACUITY, MORE SUBTLE. A mutant nobody's tests cover was
# generated and never executed. It is not a survivor -- nothing failed to kill
# it, because nothing tried -- but counting it as anything other than a failure
# would let coverage rot while the survivor count stayed at zero.
#
# SUSPICIOUS, TIMEOUT AND SEGFAULT ARE NOT PASSES EITHER. Each means the
# mutant's fate is unknown: the suite behaved oddly, ran too long, or crashed
# the interpreter.
#
# THE MATCH PATTERNS COME FROM conftest.exactly / containing, because a bare
# string passed to pytest.raises(match=...) is a REGEX SEARCH: its dots are
# wildcards and it matches substrings. Both looseness modes have already let a
# mutant survive in this repository.

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from conftest import containing
from cs1090a_spec_driven_development.contracts.verdict import CheckVerdict, GateVerdict
from cs1090a_spec_driven_development.mutation import (
    MutationStats,
    evaluate_mutation_stats,
    load_mutation_stats,
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


class TestMutationStatsContract:
    def test_the_real_artifact_shape_validates(self) -> None:
        """THE FIELD NAMES ARE mutmut's, taken from a real run rather than
        guessed, so a rename upstream fails here instead of being ignored."""
        parsed = MutationStats.model_validate(CLEAN)

        assert parsed.killed == 474
        assert parsed.survived == 0
        assert parsed.total == 474
        assert parsed.no_tests == 0

    def test_an_unknown_field_is_rejected(self) -> None:
        """extra="forbid": a field mutmut adds is a contract change we must see."""
        with pytest.raises(ValidationError):
            MutationStats.model_validate(CLEAN | {"exploded": 1})

    def test_a_missing_field_is_rejected(self) -> None:
        incomplete = {key: value for key, value in CLEAN.items() if key != "survived"}

        with pytest.raises(ValidationError):
            MutationStats.model_validate(incomplete)

    def test_a_negative_count_is_rejected(self) -> None:
        """A COUNT IS NOT NEGATIVE. Such a document is corrupt, not merely bad
        news, and treating it as a failing gate would misreport the cause."""
        with pytest.raises(ValidationError):
            MutationStats.model_validate(CLEAN | {"survived": -1})

    def test_the_stats_are_frozen(self) -> None:
        parsed = MutationStats.model_validate(CLEAN)

        with pytest.raises(ValidationError):
            parsed.survived = 5


class TestVerdictDerivation:
    def test_a_clean_run_passes(self) -> None:
        verdict = evaluate_mutation_stats(stats())

        assert verdict.verdict is GateVerdict.PASS
        assert verdict.reasons == []
        assert verdict.gate == "mutation_zero_survivors"

    def test_any_survivor_fails_and_names_the_check(self) -> None:
        verdict = evaluate_mutation_stats(stats(survived=1, killed=473))

        assert verdict.verdict is GateVerdict.FAIL
        assert "zero_survivors" in verdict.reasons

    def test_the_survivor_check_reports_the_count_against_zero(self) -> None:
        """OBSERVED AND EXPECTED, so the record answers "how many" without a
        second lookup."""
        verdict = evaluate_mutation_stats(stats(survived=7, killed=467))
        check = next(item for item in verdict.checks if item.id == "zero_survivors")

        assert check.observed == 7
        assert check.expected == 0

    def test_a_run_with_no_mutants_is_unknown_rather_than_passing(self) -> None:
        """THE VACUITY THIS REPOSITORY ALREADY EXPERIENCED.

        Zero survivors out of zero mutants is not a passing gate; it is a gate
        that measured nothing, and the two must not be reported alike.
        """
        verdict = evaluate_mutation_stats(
            MutationStats.model_validate(CLEAN | {"killed": 0, "survived": 0, "total": 0})
        )

        assert verdict.verdict is GateVerdict.UNKNOWN

    def test_a_mutant_with_no_tests_fails(self) -> None:
        """NOT A SURVIVOR, AND STILL NOT ACCEPTABLE. Nothing tried to kill it."""
        verdict = evaluate_mutation_stats(stats(no_tests=3, killed=471))

        assert verdict.verdict is GateVerdict.FAIL
        assert "every_mutant_measured" in verdict.reasons

    def test_a_suspicious_mutant_fails(self) -> None:
        verdict = evaluate_mutation_stats(stats(suspicious=1, killed=473))

        assert verdict.verdict is GateVerdict.FAIL
        assert "no_indeterminate_outcomes" in verdict.reasons

    def test_a_timed_out_mutant_fails(self) -> None:
        """A TIMEOUT IS NOT A KILL. The mutant's fate is unknown, and an
        infinite loop is a defect the suite should describe, not absorb."""
        verdict = evaluate_mutation_stats(stats(timeout=2, killed=472))

        assert verdict.verdict is GateVerdict.FAIL
        assert "no_indeterminate_outcomes" in verdict.reasons

    def test_a_segfault_fails(self) -> None:
        verdict = evaluate_mutation_stats(stats(segfault=1, killed=473))

        assert verdict.verdict is GateVerdict.FAIL
        assert "no_indeterminate_outcomes" in verdict.reasons

    def test_an_interrupted_run_is_unknown_rather_than_failing(self) -> None:
        """SOMEONE PRESSED CTRL-C. The run is incomplete, which is neither a
        pass nor evidence of a defect -- exactly what UNKNOWN is for.
        """
        verdict = evaluate_mutation_stats(stats(check_was_interrupted_by_user=1))

        assert verdict.verdict is GateVerdict.UNKNOWN

    def test_a_skipped_mutant_is_reported_without_deciding(self) -> None:
        """Skips are context. They are recorded so a reader can see them, and
        they do not silently fail a gate nobody configured to care."""
        verdict = evaluate_mutation_stats(stats(skipped=4))
        check = next(item for item in verdict.checks if item.id == "skipped")

        assert check.verdict is CheckVerdict.INFORMATIONAL
        assert check.observed == 4

    def test_the_totals_are_reported_as_context(self) -> None:
        verdict = evaluate_mutation_stats(stats())
        check = next(item for item in verdict.checks if item.id == "mutants_killed")

        assert check.verdict is CheckVerdict.INFORMATIONAL
        assert check.observed == 474

    def test_several_failures_are_all_reported(self) -> None:
        """NO SHORT-CIRCUITING, for the same reason the FMLA rules do not: one
        fix per run is a treadmill.
        """
        verdict = evaluate_mutation_stats(stats(survived=1, no_tests=1, timeout=1, killed=471))

        assert set(verdict.reasons) == {
            "zero_survivors",
            "every_mutant_measured",
            "no_indeterminate_outcomes",
        }

    def test_the_subject_names_the_artifact_the_verdict_came_from(self) -> None:
        verdict = evaluate_mutation_stats(stats())

        assert verdict.subject == "mutants/mutmut-cicd-stats.json"


class TestLoading:
    def test_a_real_artifact_is_loaded_and_judged(self, tmp_path: Path) -> None:
        artifact = tmp_path / "mutmut-cicd-stats.json"
        artifact.write_text(json.dumps(CLEAN))

        assert load_mutation_stats(artifact) == MutationStats.model_validate(CLEAN)

    def test_a_missing_artifact_raises_rather_than_passing(self, tmp_path: Path) -> None:
        """THE MOST DANGEROUS FAILURE MODE OF ALL.

        A gate that treats an absent report as success passes on every machine
        where mutmut never ran -- which is every machine where someone forgot.
        """
        with pytest.raises(FileNotFoundError, match=containing("mutmut-cicd-stats.json")):
            load_mutation_stats(tmp_path / "mutmut-cicd-stats.json")

    def test_the_refusal_says_how_to_produce_the_report(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match=containing("mise run mutants")):
            load_mutation_stats(tmp_path / "mutmut-cicd-stats.json")

    def test_a_malformed_artifact_raises(self, tmp_path: Path) -> None:
        artifact = tmp_path / "mutmut-cicd-stats.json"
        artifact.write_text("not json")

        with pytest.raises(ValueError, match=containing("is not valid JSON")):
            load_mutation_stats(artifact)
