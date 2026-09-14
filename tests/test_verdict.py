# tests/test_verdict.py
# THE CONTRACT THAT JUDGES EVERY GATE, TESTED DIRECTLY.
#
# WHY THIS FILE EXISTS. The first honest mutation run reported `exit_code_for`
# as "no tests": this module had no test file at all, and was exercised only
# incidentally through tests/test_authoring.py. A module that decides whether
# every other gate passed is the last one that should be covered by accident.
#
# WHAT THE SURVIVORS TAUGHT. Mutating `observed="absent"` to `observed=None`
# survived everywhere, in both modules. The suite asserted OUTCOMES and never
# EVIDENCE -- so a determination could report the right verdict with its
# observed and expected values silently blanked, and nothing would object. That
# is the weak assertion of section 2.1.2 in its purest form: pinning the
# conclusion while ignoring what justifies it. The evidence IS the product here,
# so the assertions below pin it.

import json
from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from cs1090a_spec_driven_development.contracts.verdict import (
    Check,
    CheckVerdict,
    GateVerdict,
    Verdict,
    deciding_checks,
    derive_gate_verdict,
    derive_reasons,
    exit_code_for,
    reject_blank_id,
    reject_duplicate_ids,
    utc_now,
)

check_verdicts = st.sampled_from(list(CheckVerdict))
gate_verdicts = st.sampled_from(list(GateVerdict))


def check(
    identifier: str = "a",
    verdict: CheckVerdict = CheckVerdict.PASS,
    observed: int | str | None = None,
    expected: int | str | None = None,
) -> Check:
    return Check(id=identifier, verdict=verdict, observed=observed, expected=expected)


def verdict_with(*checks: Check) -> Verdict:
    return Verdict(gate="g", subject="s", checks=list(checks))


# --- Properties. MODULE-LEVEL: a @given method binds to a class instance, and
# mutmut re-runs the suite in one process, which trips
# HealthCheck.differing_executors -- a correctness warning, not a style one.


@given(verdict=gate_verdicts)
def test_every_gate_verdict_maps_to_a_distinct_exit_code(verdict: GateVerdict) -> None:
    """THE MAPPING IS TOTAL, and this asserts it over the whole enum.

    A member added later with no branch would fall through to the final return
    and silently become 2. Generating across the enum means the new member is
    tested the moment it exists.
    """
    assert exit_code_for(verdict) in {0, 1, 2}


@given(verdicts=st.lists(check_verdicts, min_size=1, max_size=6))
def test_the_reasons_are_exactly_the_failing_check_ids(verdicts: list[CheckVerdict]) -> None:
    checks = [check(identifier=f"c{index}", verdict=value) for index, value in enumerate(verdicts)]

    reasons = derive_reasons(checks)

    expected = [f"c{index}" for index, value in enumerate(verdicts) if value is CheckVerdict.FAIL]
    assert reasons == expected


@given(verdicts=st.lists(check_verdicts, min_size=1, max_size=6))
def test_the_gate_verdict_follows_from_the_deciding_checks(
    verdicts: list[CheckVerdict],
) -> None:
    """THE DERIVATION, STATED INDEPENDENTLY OF ITS IMPLEMENTATION.

    Expressed as three exhaustive cases rather than by re-running the function's
    own logic, which would assert only that the code equals itself.
    """
    checks = [check(identifier=f"c{index}", verdict=value) for index, value in enumerate(verdicts)]

    result = derive_gate_verdict(checks)

    deciding = [value for value in verdicts if value is not CheckVerdict.INFORMATIONAL]
    if not deciding:
        assert result is GateVerdict.UNKNOWN
    elif CheckVerdict.FAIL in deciding:
        assert result is GateVerdict.FAIL
    else:
        assert result is GateVerdict.PASS


@given(verdicts=st.lists(check_verdicts, min_size=1, max_size=6))
def test_informational_checks_are_the_ones_excluded_from_deciding(
    verdicts: list[CheckVerdict],
) -> None:
    checks = [check(identifier=f"c{index}", verdict=value) for index, value in enumerate(verdicts)]

    deciding = deciding_checks(checks)

    assert all(item.verdict is not CheckVerdict.INFORMATIONAL for item in deciding)
    assert len(deciding) == sum(1 for v in verdicts if v is not CheckVerdict.INFORMATIONAL)


# --- Examples -----------------------------------------------------------------


class TestExitCode:
    def test_pass_exits_zero(self) -> None:
        assert exit_code_for(GateVerdict.PASS) == 0

    def test_fail_exits_one(self) -> None:
        assert exit_code_for(GateVerdict.FAIL) == 1

    def test_unknown_exits_two_and_is_not_treated_as_failure(self) -> None:
        """UNKNOWN IS A THIRD OUTCOME, GIVEN ITS OWN CODE.

        Collapsing it into 1 would make "the gate measured nothing"
        indistinguishable from "the gate measured something and it was wrong" --
        and only one of those is fixed by changing the code under test.
        """
        assert exit_code_for(GateVerdict.UNKNOWN) == 2

    def test_the_property_reads_through_to_the_mapping(self) -> None:
        assert verdict_with(check(verdict=CheckVerdict.FAIL)).exit_code == 1


class TestCheckContract:
    def test_a_check_records_what_was_observed_and_what_was_required(self) -> None:
        """THE EVIDENCE FIELDS, ASSERTED. A mutant blanking these survived the
        first run because nothing in the suite looked at them."""
        result = check(identifier="test_count", observed=24, expected=24)

        assert result.observed == 24
        assert result.expected == 24

    def test_observed_may_be_a_string(self) -> None:
        result = check(observed="absent", expected="present")

        assert result.observed == "absent"
        assert result.expected == "present"

    def test_a_blank_id_is_refused(self) -> None:
        """AN UNNAMED CHECK IS AN UNCITABLE ONE.

        min_length=1 admits "   ", so the validator does the work the constraint
        cannot.
        """
        with pytest.raises(ValidationError):
            check(identifier="   ")

    def test_an_empty_id_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            check(identifier="")

    def test_a_tab_only_id_is_refused(self) -> None:
        """Whitespace is not only the space character."""
        with pytest.raises(ValidationError):
            check(identifier="\t")

    def test_reject_blank_id_returns_the_check_it_was_given(self) -> None:
        original = check(identifier="ok")

        assert reject_blank_id(original) is original

    def test_an_unknown_verdict_value_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Check.model_validate({"id": "a", "verdict": "passed"})

    def test_a_check_is_frozen(self) -> None:
        result = check()

        with pytest.raises(ValidationError):
            result.verdict = CheckVerdict.FAIL

    def test_unknown_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Check.model_validate({"id": "a", "verdict": "pass", "severity": "high"})


class TestVerdictDerivation:
    def test_a_supplied_verdict_is_overwritten_by_the_derived_one(self) -> None:
        """THE CENTRAL INVARIANT.

        A caller able to assert its own verdict reintroduces `echo GATES_PASS`
        inside a type.
        """
        result = Verdict(
            gate="g",
            subject="s",
            checks=[check(identifier="a"), check(identifier="b", verdict=CheckVerdict.FAIL)],
            verdict=GateVerdict.PASS,
        )

        assert result.verdict is GateVerdict.FAIL

    def test_supplied_reasons_are_overwritten_too(self) -> None:
        result = Verdict(
            gate="g",
            subject="s",
            checks=[check(identifier="a", verdict=CheckVerdict.FAIL)],
            reasons=["something_else"],
        )

        assert result.reasons == ["a"]

    def test_all_checks_passing_yields_a_passing_gate(self) -> None:
        assert (
            verdict_with(check(identifier="a"), check(identifier="b")).verdict is GateVerdict.PASS
        )

    def test_informational_checks_do_not_decide_the_gate(self) -> None:
        result = verdict_with(
            check(identifier="a"),
            check(identifier="ctx", verdict=CheckVerdict.INFORMATIONAL, observed=412),
        )

        assert result.verdict is GateVerdict.PASS

    def test_a_gate_with_only_informational_checks_is_unknown(self) -> None:
        """THE ANTI-VACUITY CLAUSE, AS A TYPE.

        This repository has watched a mutation gate report green across zero
        mutants. A gate whose checks are all informational measured nothing, and
        measuring nothing is not passing.
        """
        result = verdict_with(check(identifier="ctx", verdict=CheckVerdict.INFORMATIONAL))

        assert result.verdict is GateVerdict.UNKNOWN

    def test_a_gate_must_carry_at_least_one_check(self) -> None:
        with pytest.raises(ValidationError):
            Verdict(gate="g", subject="s", checks=[])

    def test_reasons_name_every_failing_check_in_order(self) -> None:
        result = verdict_with(
            check(identifier="a"),
            check(identifier="b", verdict=CheckVerdict.FAIL),
            check(identifier="c", verdict=CheckVerdict.FAIL),
            check(identifier="d", verdict=CheckVerdict.INFORMATIONAL),
        )

        assert result.reasons == ["b", "c"]

    def test_a_passing_gate_has_no_reasons(self) -> None:
        assert verdict_with(check(identifier="a")).reasons == []

    def test_duplicate_check_ids_are_rejected(self) -> None:
        """TWO CHECKS WITH ONE NAME MAKE THE REASONS LIST AMBIGUOUS.

        Which one failed? A document that cannot answer that is not evidence.
        """
        with pytest.raises(ValidationError):
            verdict_with(check(identifier="a"), check(identifier="a"))

    def test_the_duplicate_message_names_the_offending_id(self) -> None:
        """A REFUSAL THAT DOES NOT SAY WHAT IT REFUSED costs a bisect to read."""
        with pytest.raises(ValidationError, match="hours"):
            verdict_with(check(identifier="hours"), check(identifier="hours"))

    def test_reject_duplicate_ids_returns_the_list_it_was_given(self) -> None:
        checks = [check(identifier="a"), check(identifier="b")]

        assert reject_duplicate_ids(checks) is checks

    def test_three_checks_with_two_duplicates_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            verdict_with(check(identifier="a"), check(identifier="b"), check(identifier="a"))


class TestVerdictDocument:
    def test_the_gate_and_subject_are_recorded(self) -> None:
        result = verdict_with(check())

        assert result.gate == "g"
        assert result.subject == "s"

    def test_a_blank_gate_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            Verdict(gate="", subject="s", checks=[check()])

    def test_a_blank_subject_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            Verdict(gate="g", subject="", checks=[check()])

    def test_the_spec_version_is_recorded(self) -> None:
        """A consumer must be able to tell which shape it is reading."""
        assert verdict_with(check()).spec_version == "1.0.0"

    def test_the_document_round_trips_through_json(self) -> None:
        """It is written to disk and read by other tools; that path is asserted."""
        original = verdict_with(check(identifier="a", observed=1, expected=1))

        restored = Verdict.model_validate(json.loads(original.model_dump_json()))

        assert restored == original

    def test_unknown_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Verdict.model_validate(
                {
                    "gate": "g",
                    "subject": "s",
                    "checks": [{"id": "a", "verdict": "pass"}],
                    "severity": "high",
                }
            )


class TestTimestamp:
    def test_the_run_timestamp_is_timezone_aware_and_defaults_to_now(self) -> None:
        """A NAIVE TIMESTAMP IS NOT A FACT ABOUT A MOMENT.

        Evidence compared across a laptop and a CI runner in different zones is
        unorderable without an offset.
        """
        before = datetime.now(UTC)
        result = verdict_with(check())
        after = datetime.now(UTC)

        assert result.run_timestamp.tzinfo is not None
        assert before <= result.run_timestamp <= after

    def test_utc_now_is_utc_specifically_and_not_merely_aware(self) -> None:
        """LOCAL TIME WITH AN OFFSET WOULD PASS AN AWARENESS CHECK.

        Two runs an hour apart in different zones would then sort wrongly, so
        the zone itself is asserted rather than its presence.
        """
        moment = utc_now()

        assert moment.tzinfo is not None
        assert moment.utcoffset() == datetime.now(UTC).utcoffset()
