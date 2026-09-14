# tests/test_fmla_boundaries.py
# THE BOUNDARIES NO FIXTURE HAPPENED TO SIT ON.
#
# WHY THIS FILE EXISTS. After 189 passing tests, mutation testing still found
# these alive:
#
#   months >= TENURE_MONTHS   mutated to   months > TENURE_MONTHS
#   hours  >= guarantee       mutated to   hours  > guarantee
#
# BOTH ARE REAL STATUTORY DEFECTS, not academic ones. 825.110(a)(1) says AT
# LEAST 12 months, so `>` denies leave to an employee with exactly twelve. The
# flight-crew clause is the same shape. Each mutant denies FMLA leave to exactly
# the population sitting on the threshold -- the population the threshold was
# written to include -- and every existing test passed anyway, because no
# fixture landed on the boundary.
#
# THE TENURE CASE WAS DOUBLY HIDDEN. The suite's baseline employee has 26 months
# of service, so the comparison had fourteen months of slack. An off-by-one is
# only detectable where the value sits exactly on the line.
#
# THE FLIGHT-CREW CASE WAS HIDDEN BY THE OTHER CLAUSE. 825.801(b) requires 504
# hours AND 60% of the annualised guarantee, and the earlier tests used a
# 60-hour guarantee, whose 60% is 432 -- below the 504 floor. The floor decided
# every case, so the guarantee comparison never was the deciding one. A test
# that exercises a rule without letting it DECIDE has not tested that rule.
#
# THE as_of MUTANT is different again: countable_periods reads as_of only when
# an earlier period is still OPEN, and no fixture had one. The record is real --
# an employee rehired while a prior employment row was never closed -- so what
# was missing was the fixture, not the code.

from collections.abc import Callable
from datetime import date

from cs1090a_spec_driven_development.contracts.fmla import (
    FLIGHT_CREW_HOURS_FLOOR,
    HOURS_OF_SERVICE,
    TENURE_MONTHS,
    Employee,
    EmployeeClass,
    EmploymentPeriod,
    FlightCrewService,
    RuleOutcome,
    countable_periods,
    evaluate_hours,
    evaluate_tenure,
    flight_crew_hours_satisfied,
    months_of_service,
)


class TestTenureBoundary:
    def test_exactly_twelve_months_is_eligible(
        self, employee_builder: Callable[..., Employee], leave_start: date
    ) -> None:
        """825.110(a)(1): AT LEAST twelve months.

        `>` instead of `>=` denies leave to an employee on their first
        anniversary, which is the most common eligibility date there is.
        """
        subject = employee_builder(employment_periods=[EmploymentPeriod(start=date(2025, 3, 1))])

        evaluation = evaluate_tenure(subject, as_of=leave_start)

        assert evaluation.observed == TENURE_MONTHS
        assert evaluation.outcome is RuleOutcome.SATISFIED

    def test_one_month_short_is_ineligible(
        self, employee_builder: Callable[..., Employee], leave_start: date
    ) -> None:
        """The other side of the same line, so the pair pins a boundary rather
        than a direction."""
        subject = employee_builder(employment_periods=[EmploymentPeriod(start=date(2025, 4, 1))])

        evaluation = evaluate_tenure(subject, as_of=leave_start)

        assert evaluation.observed == 11
        assert evaluation.outcome is RuleOutcome.NOT_SATISFIED

    def test_one_day_short_of_twelve_months_is_ineligible(
        self, employee_builder: Callable[..., Employee], leave_start: date
    ) -> None:
        """THE DAY-OF-MONTH RULE AT THE ELIGIBILITY BOUNDARY.

        Hired 2 March, leave starting 1 March the following year: eleven months
        and some days, not twelve. This is where the month arithmetic and the
        statutory threshold interact, and it is the case a payroll system gets
        wrong.
        """
        subject = employee_builder(employment_periods=[EmploymentPeriod(start=date(2025, 3, 2))])

        assert evaluate_tenure(subject, as_of=leave_start).observed == 11


class TestHoursBoundary:
    def test_exactly_the_hours_threshold_is_satisfied(
        self, employee_builder: Callable[..., Employee]
    ) -> None:
        """825.110(a)(2): AT LEAST 1,250 hours."""
        evaluation = evaluate_hours(employee_builder(hours_worked_in_lookback=HOURS_OF_SERVICE))

        assert evaluation.observed == HOURS_OF_SERVICE
        assert evaluation.outcome is RuleOutcome.SATISFIED

    def test_one_hour_short_is_not_satisfied(
        self, employee_builder: Callable[..., Employee]
    ) -> None:
        evaluation = evaluate_hours(employee_builder(hours_worked_in_lookback=HOURS_OF_SERVICE - 1))

        assert evaluation.outcome is RuleOutcome.NOT_SATISFIED


class TestFlightCrewGuaranteeBoundary:
    def test_exactly_the_guarantee_requirement_is_satisfied(self) -> None:
        """825.801(b)(1): 60% of the applicable monthly guarantee, AT LEAST.

        A 70-hour guarantee annualises to 840; 60% is 504. Supplying exactly 504
        makes the GUARANTEE the deciding clause rather than the floor, which is
        what the earlier tests never arranged.
        """
        service = FlightCrewService(duty_or_paid_hours=504, applicable_monthly_guarantee=70)

        assert flight_crew_hours_satisfied(service) is True

    def test_the_guarantee_decides_when_the_floor_is_comfortably_met(self) -> None:
        """A 100-HOUR GUARANTEE ANNUALISES TO 1,200; 60% IS 720.

        720 clears the 504 floor with room to spare, so this pair isolates the
        guarantee comparison completely -- the floor cannot be what decides it.
        """
        at_requirement = FlightCrewService(duty_or_paid_hours=720, applicable_monthly_guarantee=100)
        below_requirement = FlightCrewService(
            duty_or_paid_hours=719, applicable_monthly_guarantee=100
        )

        assert flight_crew_hours_satisfied(at_requirement) is True
        assert flight_crew_hours_satisfied(below_requirement) is False

    def test_exactly_the_floor_is_satisfied_when_the_guarantee_cannot_bind(self) -> None:
        """The floor's own boundary, isolated by a guarantee too low to decide."""
        service = FlightCrewService(
            duty_or_paid_hours=FLIGHT_CREW_HOURS_FLOOR, applicable_monthly_guarantee=10
        )

        assert flight_crew_hours_satisfied(service) is True

    def test_one_hour_below_the_floor_is_not_satisfied(self) -> None:
        service = FlightCrewService(
            duty_or_paid_hours=FLIGHT_CREW_HOURS_FLOOR - 1, applicable_monthly_guarantee=10
        )

        assert flight_crew_hours_satisfied(service) is False

    def test_a_crew_member_meeting_both_clauses_is_judged_on_the_crew_rule(
        self, employee_builder: Callable[..., Employee]
    ) -> None:
        """The 1,250-hour rule is set aside rather than failed."""
        subject = employee_builder(
            employee_class=EmployeeClass.AIRLINE_FLIGHT_CREW,
            hours_worked_in_lookback=504,
            flight_crew_service=FlightCrewService(
                duty_or_paid_hours=504, applicable_monthly_guarantee=70
            ),
        )

        assert evaluate_hours(subject).outcome is RuleOutcome.NOT_APPLICABLE


class TestOpenPriorPeriod:
    def test_an_unclosed_earlier_period_is_measured_to_the_leave_date(
        self, leave_start: date
    ) -> None:
        """THE as_of MUTANT.

        countable_periods reads as_of only when an EARLIER period has no end --
        an employee rehired while a prior employment record was never closed. No
        fixture had one, so passing as_of=None survived every test. An unclosed
        period must run to the leave date rather than be treated as an instant.
        """
        open_early = EmploymentPeriod(start=date(2010, 1, 1), end=None)
        later = EmploymentPeriod(start=date(2025, 11, 1))

        kept = countable_periods(
            [open_early, later],
            as_of=leave_start,
            written_rehire_agreement=False,
            has_userra_service=False,
        )

        # The open period runs to the leave date, so the gap to the later period
        # is not a seven-year break and nothing is discarded.
        assert kept == [open_early, later]

    def test_two_open_periods_both_count_toward_service(
        self, employee_builder: Callable[..., Employee], leave_start: date
    ) -> None:
        subject = employee_builder(
            employment_periods=[
                EmploymentPeriod(start=date(2025, 1, 1), end=None),
                EmploymentPeriod(start=date(2025, 9, 1), end=None),
            ]
        )

        assert months_of_service(subject, as_of=leave_start) == 20
