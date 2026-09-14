# tests/test_exact_messages_and_types.py
# THE MUTANTS THAT SURVIVED BECAUSE AN ASSERTION WAS LOOSER THAN IT LOOKED.
#
# --- THE XX MUTANTS -----------------------------------------------------------
#
# mutmut wraps string literals in sentinels:
#
#   "payload must not be empty"  ->  "XXpayload must not be emptyXX"
#
# Both survived a suite that already asserted the messages, because
# pytest.raises(match=...) treats its argument as a SEARCH, not a full match.
# The unmutated text is a substring of the mutated text, so the assertion passed
# against the mutant.
#
# THIS IS A WEAK ASSERTION HIDING INSIDE A STRONG-LOOKING ONE. It reads as "the
# message is X" and means "the message contains X". Anchoring makes it mean what
# it reads.
#
# --- THE INTEGER DIVISION MUTANT ----------------------------------------------
#
#   annual * 60 // 100   ->   annual * 60 / 100
#
# 504 == 504.0 is True, so every existing assertion passed. The type is not
# cosmetic: an hours requirement is a whole number of hours, and a float leaking
# into a Check's `required` field changes the published JSON from 504 to 504.0
# for every consumer of the determination.
#
# THE GENERAL LESSON: assert the TYPE wherever a numeric contract is integral,
# because equality across numeric types is silent.
#
# --- ON THE FIXTURE ANNOTATIONS -----------------------------------------------
#
# These were first written as `employee_builder: object` with a type: ignore on
# each call. mypy rejected it -- the ignore named the wrong error code, which is
# what `ignore-without-code` and `--strict` exist to catch. Annotating the
# fixtures properly removed all three suppressions instead of correcting them: a
# test file that cannot typecheck without ignores is one whose fixtures have
# drifted from what they actually return.

import re
from collections.abc import Callable
from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from cs1090a_spec_driven_development.authoring import reject_empty_payload
from cs1090a_spec_driven_development.contracts.fmla import (
    Employee,
    FlightCrewService,
    evaluate_flight_crew_hours,
    evaluate_hours,
    evaluate_tenure,
    evaluate_worksite,
    required_flight_crew_guarantee_hours,
)
from cs1090a_spec_driven_development.contracts.verdict import Check, CheckVerdict


def exactly(message: str) -> str:
    r"""A regex matching the whole string and nothing around it.

    \A AND \Z RATHER THAN ^ AND $, which match at line boundaries too -- a
    message with an injected newline would still pass an anchored-with-$ match.
    """
    return rf"\A{re.escape(message)}\Z"


class TestExactRefusalMessages:
    def test_the_empty_payload_message_is_exactly_this(self) -> None:
        """THE XX MUTANT. A substring match passes against the sentinel-wrapped
        version; an anchored match does not."""
        with pytest.raises(ValueError, match=exactly("payload must not be empty")):
            reject_empty_payload(b"")

    def test_the_blank_id_message_is_exactly_this(self) -> None:
        """Pydantic wraps the ValueError, so the exact text is asserted against
        the structured error rather than the wrapper's rendering."""
        with pytest.raises(ValidationError) as raised:
            Check(id="   ", verdict=CheckVerdict.PASS)

        messages = [error["msg"] for error in raised.value.errors()]

        assert messages == ["Value error, check id must not be blank"]


class TestGuaranteeHoursAreWholeHours:
    def test_the_requirement_is_an_integer_and_not_a_float(self) -> None:
        """THE // -> / MUTANT.

        504 == 504.0 is True, so only the type distinguishes them. `type(...) is
        int` rather than isinstance, because bool is a subclass of int and would
        pass an isinstance check.
        """
        service = FlightCrewService(duty_or_paid_hours=0, applicable_monthly_guarantee=70)

        requirement = required_flight_crew_guarantee_hours(service)

        assert requirement == 504
        assert type(requirement) is int

    def test_a_guarantee_that_does_not_divide_evenly_still_yields_an_integer(self) -> None:
        """A GUARANTEE OF 7 MAKES THE OPERATORS DISAGREE ON THE VALUE.

        7 * 12 * 60 is 5040; 5040 // 100 is 50 while 5040 / 100 is 50.4. The
        floor actually discards something here, so this case distinguishes the
        mutant on the number itself and not only on its type.
        """
        service = FlightCrewService(duty_or_paid_hours=0, applicable_monthly_guarantee=7)

        requirement = required_flight_crew_guarantee_hours(service)

        assert requirement == 50
        assert type(requirement) is int

    def test_the_published_requirement_is_an_integer(self) -> None:
        """THE FIELD A CONSUMER READS. A float here changes the JSON a
        determination publishes from 504 to 504.0 for everyone downstream.
        """
        service = FlightCrewService(duty_or_paid_hours=600, applicable_monthly_guarantee=70)

        evaluation = evaluate_flight_crew_hours(service)

        assert type(evaluation.required) is int


@given(guarantee=st.integers(min_value=0, max_value=500))
def test_the_guarantee_requirement_is_always_a_whole_number_of_hours(guarantee: int) -> None:
    """ACROSS THE WHOLE RANGE, so no single fixture can be the reason it passes."""
    service = FlightCrewService(duty_or_paid_hours=0, applicable_monthly_guarantee=guarantee)

    assert type(required_flight_crew_guarantee_hours(service)) is int


class TestObservedValuesAreIntegers:
    def test_the_tenure_evaluation_reports_whole_months(
        self, employee_builder: Callable[..., Employee], leave_start: date
    ) -> None:
        """Months are counted, not measured; a fractional month is not a fact."""
        evaluation = evaluate_tenure(employee_builder(), as_of=leave_start)

        assert type(evaluation.observed) is int

    def test_the_hours_evaluation_reports_whole_hours(
        self, employee_builder: Callable[..., Employee]
    ) -> None:
        evaluation = evaluate_hours(employee_builder())

        assert type(evaluation.observed) is int

    def test_the_userra_credited_hours_are_whole_hours(
        self, employee_builder: Callable[..., Employee]
    ) -> None:
        """THE CREDIT IS COMPUTED FROM 52/12 WEEKS PER MONTH, which is a float
        before int() truncates it. The published figure must still be whole.
        """
        subject = employee_builder(
            hours_worked_in_lookback=600,
            userra_service={"months_absent": 10, "pre_service_weekly_hours": 40},
        )

        evaluation = evaluate_hours(subject)

        assert type(evaluation.observed) is int
        assert evaluation.observed == 2333

    def test_the_worksite_evaluation_reports_a_whole_headcount(
        self, employee_builder: Callable[..., Employee]
    ) -> None:
        """PEOPLE ARE COUNTED IN WHOLE NUMBERS."""
        evaluation = evaluate_worksite(employee_builder())

        assert type(evaluation.observed) is int
