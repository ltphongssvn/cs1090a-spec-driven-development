# tests/test_fmla_rules.py
# THE FMLA RULES, TESTED AS RULES RATHER THAN THROUGH HTTP.
#
# WHY THIS FILE EXISTS. The acceptance suite in tests/acceptance passed 24 tests
# while 136 mutants survived. It asserted VERDICTS and OUTCOMES and never the
# evidence beneath them, so mutating `observed=<value>` to `observed=None`
# survived on nearly every rule: a determination could carry the right answer
# with its observed and required values blanked, and the suite would applaud.
#
# THE EVIDENCE IS THE PRODUCT. This service exists to answer "why", and a rule
# that cannot say what it saw and what the regulation demanded is an opinion
# with an identifier. Every evaluation below is therefore asserted in full --
# rule_id, citation, outcome, observed, required.
#
# THE SECOND SURVIVOR CLASS WAS ARITHMETIC. `months -= 1` mutated to
# `months = 1` survived because every fixture date fell on the first of a month,
# so the day-of-month adjustment never executed. Fixtures that only ever use
# round numbers cannot detect an error in the rounding.
#
# THESE ARE UNIT TESTS OF UNDECORATED FUNCTIONS, which is the only form mutmut
# can measure: a rule reached solely through an @app.post handler is invisible
# to mutation testing.

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cs1090a_spec_driven_development.contracts.fmla import (
    CAREGIVER_ENTITLEMENT_WEEKS,
    COVERED_EMPLOYER_WORKWEEKS,
    FLIGHT_CREW_HOURS_FLOOR,
    HOURS_OF_SERVICE,
    ORDINARY_ENTITLEMENT_WEEKS,
    RULE_CREW_HOURS,
    RULE_EMPLOYER,
    RULE_HOURS,
    RULE_RELATIONSHIP,
    RULE_SERVICEMEMBER,
    RULE_TENURE,
    RULE_WORKSITE,
    WORKSITE_HEADCOUNT,
    EligibilityVerdict,
    Employee,
    EmployeeClass,
    Employer,
    EmployerType,
    EmploymentPeriod,
    FlightCrewService,
    LeaveReason,
    MilitaryCaregiver,
    QualifyingRelationship,
    RuleOutcome,
    ServicememberStatus,
    UserraService,
    countable_periods,
    employer_is_covered,
    entitlement_weeks_for,
    evaluate_caregiver,
    evaluate_employer,
    evaluate_flight_crew_hours,
    evaluate_hours,
    evaluate_tenure,
    evaluate_worksite,
    flight_crew_hours_satisfied,
    hours_of_service,
    months_between,
    months_of_service,
    outcome_for,
    relationship_qualifies,
    required_flight_crew_guarantee_hours,
    servicemember_is_covered,
    userra_credited_hours,
    veteran_is_covered,
)

LEAVE_START = date(2026, 3, 1)


def employee(**overrides: object) -> Employee:
    defaults: dict[str, object] = {
        "employee_class": EmployeeClass.STANDARD,
        "employment_periods": [EmploymentPeriod(start=date(2024, 1, 1))],
        "written_rehire_agreement": False,
        "userra_service": None,
        "hours_worked_in_lookback": 1400,
        "worksite_headcount_within_75_miles": 80,
        "flight_crew_service": None,
    }
    return Employee.model_validate(defaults | overrides)


def employer(**overrides: object) -> Employer:
    defaults: dict[str, object] = {
        "employer_type": EmployerType.PRIVATE,
        "workweeks_with_50_employees_current_year": 22,
        "workweeks_with_50_employees_preceding_year": 0,
    }
    return Employer.model_validate(defaults | overrides)


def caregiver(**overrides: object) -> MilitaryCaregiver:
    defaults: dict[str, object] = {
        "relationship": QualifyingRelationship.SPOUSE,
        "servicemember_status": ServicememberStatus.CURRENT_MEMBER_IN_TREATMENT,
        "discharge_date": None,
        "discharged_other_than_dishonorably": None,
    }
    return MilitaryCaregiver.model_validate(defaults | overrides)


# --- Properties. MODULE-LEVEL; a @given method trips differing_executors under
# mutmut's repeated in-process runs.


@given(
    start=st.dates(min_value=date(2000, 1, 1), max_value=date(2030, 1, 1)),
    end=st.dates(min_value=date(2000, 1, 1), max_value=date(2030, 1, 1)),
)
def test_months_between_is_never_negative(start: date, end: date) -> None:
    """825.110 counts service; negative service is not a quantity.

    The generated pairs include end < start, which is what pins the max().
    """
    assert months_between(start, end) >= 0


@given(satisfied=st.booleans())
def test_outcome_for_maps_the_two_truth_values(satisfied: bool) -> None:
    expected = RuleOutcome.SATISFIED if satisfied else RuleOutcome.NOT_SATISFIED
    assert outcome_for(satisfied) is expected


@given(workweeks=st.integers(min_value=0, max_value=53))
def test_private_employer_coverage_turns_exactly_on_twenty_workweeks(workweeks: int) -> None:
    """825.104(a). The boundary asserted across the whole range, not at a point."""
    covered = employer_is_covered(
        employer(
            workweeks_with_50_employees_current_year=workweeks,
            workweeks_with_50_employees_preceding_year=0,
        )
    )

    assert covered is (workweeks >= COVERED_EMPLOYER_WORKWEEKS)


@given(headcount=st.integers(min_value=0, max_value=200))
def test_the_worksite_rule_turns_exactly_on_fifty(headcount: int) -> None:
    evaluation = evaluate_worksite(employee(worksite_headcount_within_75_miles=headcount))

    expected = (
        RuleOutcome.SATISFIED if headcount >= WORKSITE_HEADCOUNT else RuleOutcome.NOT_SATISFIED
    )
    assert evaluation.outcome is expected
    assert evaluation.observed == headcount
    assert evaluation.required == WORKSITE_HEADCOUNT


@given(hours=st.integers(min_value=0, max_value=3000))
def test_the_hours_rule_turns_exactly_on_1250(hours: int) -> None:
    evaluation = evaluate_hours(employee(hours_worked_in_lookback=hours))

    expected = RuleOutcome.SATISFIED if hours >= HOURS_OF_SERVICE else RuleOutcome.NOT_SATISFIED
    assert evaluation.outcome is expected
    assert evaluation.observed == hours


# --- months_between: the arithmetic the round-number fixtures never reached ---


class TestMonthsBetween:
    def test_a_whole_year_is_twelve_months(self) -> None:
        assert months_between(date(2025, 3, 1), date(2026, 3, 1)) == 12

    def test_the_day_of_month_shortfall_removes_a_month(self) -> None:
        """THE MUTANT THAT SURVIVED THE FIRST RUN.

        Counting calendar-month boundaries alone credits a full month to someone
        employed from the 31st to the 1st, which makes an employee eligible a
        month early. Every earlier fixture used day 1, so this never executed.
        """
        assert months_between(date(2025, 3, 31), date(2026, 3, 1)) == 11

    def test_an_exact_day_match_keeps_the_month(self) -> None:
        assert months_between(date(2025, 3, 15), date(2026, 3, 15)) == 12

    def test_a_later_day_of_month_keeps_the_month(self) -> None:
        assert months_between(date(2025, 3, 10), date(2026, 3, 20)) == 12

    def test_a_reversed_range_is_zero_rather_than_negative(self) -> None:
        assert months_between(date(2026, 3, 1), date(2025, 3, 1)) == 0

    def test_the_same_date_is_zero_months(self) -> None:
        assert months_between(date(2026, 3, 1), date(2026, 3, 1)) == 0

    def test_one_day_short_of_a_month_is_zero(self) -> None:
        assert months_between(date(2026, 2, 2), date(2026, 3, 1)) == 0


# --- Break in service ---------------------------------------------------------


class TestCountablePeriods:
    def test_a_short_break_keeps_both_periods(self) -> None:
        periods = [
            EmploymentPeriod(start=date(2021, 1, 1), end=date(2021, 8, 1)),
            EmploymentPeriod(start=date(2025, 9, 1)),
        ]

        assert (
            countable_periods(
                periods,
                as_of=LEAVE_START,
                written_rehire_agreement=False,
                has_userra_service=False,
            )
            == periods
        )

    def test_a_break_of_more_than_seven_years_drops_the_earlier_period(self) -> None:
        early = EmploymentPeriod(start=date(2010, 1, 1), end=date(2015, 1, 1))
        late = EmploymentPeriod(start=date(2025, 11, 1))

        kept = countable_periods(
            [early, late],
            as_of=LEAVE_START,
            written_rehire_agreement=False,
            has_userra_service=False,
        )

        assert kept == [late]

    def test_exactly_seven_years_is_not_more_than_seven_years(self) -> None:
        """825.110(b)(1) permits discounting a break of SEVEN YEARS OR MORE only
        beyond that span; the comparison is strict, so the boundary is asserted."""
        early = EmploymentPeriod(start=date(2010, 1, 1), end=date(2019, 3, 1))
        late = EmploymentPeriod(start=date(2026, 3, 1))

        kept = countable_periods(
            [early, late],
            as_of=LEAVE_START,
            written_rehire_agreement=False,
            has_userra_service=False,
        )

        assert kept == [early, late]

    def test_a_written_rehire_agreement_keeps_everything(self) -> None:
        periods = [
            EmploymentPeriod(start=date(2010, 1, 1), end=date(2015, 1, 1)),
            EmploymentPeriod(start=date(2025, 11, 1)),
        ]

        assert (
            countable_periods(
                periods,
                as_of=LEAVE_START,
                written_rehire_agreement=True,
                has_userra_service=False,
            )
            == periods
        )

    def test_userra_service_keeps_everything(self) -> None:
        periods = [
            EmploymentPeriod(start=date(2010, 1, 1), end=date(2015, 1, 1)),
            EmploymentPeriod(start=date(2025, 11, 1)),
        ]

        assert (
            countable_periods(
                periods,
                as_of=LEAVE_START,
                written_rehire_agreement=False,
                has_userra_service=True,
            )
            == periods
        )

    def test_everything_before_the_last_long_break_is_dropped(self) -> None:
        """THREE PERIODS, NOT TWO.

        An implementation dropping only the single period before the break would
        keep the earliest stint here.
        """
        first = EmploymentPeriod(start=date(2000, 1, 1), end=date(2001, 1, 1))
        second = EmploymentPeriod(start=date(2002, 1, 1), end=date(2003, 1, 1))
        third = EmploymentPeriod(start=date(2025, 11, 1))

        kept = countable_periods(
            [first, second, third],
            as_of=LEAVE_START,
            written_rehire_agreement=False,
            has_userra_service=False,
        )

        assert kept == [third]

    def test_periods_supplied_out_of_order_are_sorted_before_scanning(self) -> None:
        """Input order is not a fact about employment."""
        early = EmploymentPeriod(start=date(2010, 1, 1), end=date(2015, 1, 1))
        late = EmploymentPeriod(start=date(2025, 11, 1))

        kept = countable_periods(
            [late, early],
            as_of=LEAVE_START,
            written_rehire_agreement=False,
            has_userra_service=False,
        )

        assert kept == [late]

    def test_an_open_period_is_measured_to_the_leave_date(self) -> None:
        """825.110(d): eligibility is determined as of the date leave starts."""
        assert (
            months_of_service(
                employee(employment_periods=[EmploymentPeriod(start=date(2025, 3, 1))]),
                as_of=LEAVE_START,
            )
            == 12
        )

    def test_nonconsecutive_months_are_summed_not_spanned(self) -> None:
        """825.110(b): the twelve months need not be consecutive.

        Measuring from the earliest start to the leave date would report sixty
        months here rather than the thirteen actually served.
        """
        months = months_of_service(
            employee(
                employment_periods=[
                    EmploymentPeriod(start=date(2021, 1, 1), end=date(2021, 8, 1)),
                    EmploymentPeriod(start=date(2025, 9, 1)),
                ]
            ),
            as_of=LEAVE_START,
        )

        assert months == 13


# --- USERRA -------------------------------------------------------------------


class TestUserra:
    def test_no_service_credits_no_hours(self) -> None:
        assert userra_credited_hours(None) == 0

    def test_hours_are_computed_from_the_pre_service_schedule(self) -> None:
        """825.110(c)(2): the hours that WOULD have been worked.

        Ten months at forty hours a week: 10 * 52/12 * 40.
        """
        assert (
            userra_credited_hours(UserraService(months_absent=10, pre_service_weekly_hours=40))
            == 1733
        )

    def test_a_zero_length_absence_credits_nothing(self) -> None:
        assert (
            userra_credited_hours(UserraService(months_absent=0, pre_service_weekly_hours=40)) == 0
        )

    def test_credited_hours_are_added_to_hours_actually_worked(self) -> None:
        """ADDED, NOT SUBSTITUTED. Replacing the actual hours would penalise an
        employee who worked before deploying."""
        total = hours_of_service(
            employee(
                hours_worked_in_lookback=600,
                userra_service=UserraService(months_absent=10, pre_service_weekly_hours=40),
            )
        )

        assert total == 2333

    def test_the_absence_is_added_to_months_of_service(self) -> None:
        months = months_of_service(
            employee(
                employment_periods=[EmploymentPeriod(start=date(2025, 11, 1))],
                userra_service=UserraService(months_absent=10, pre_service_weekly_hours=40),
            ),
            as_of=LEAVE_START,
        )

        assert months == 14


# --- Flight crew --------------------------------------------------------------


class TestFlightCrew:
    def test_the_guarantee_requirement_is_sixty_percent_of_the_annualised_guarantee(
        self,
    ) -> None:
        """825.801(b)(1). Seventy hours a month for twelve months is 840; 60% is 504."""
        service = FlightCrewService(duty_or_paid_hours=0, applicable_monthly_guarantee=70)

        assert required_flight_crew_guarantee_hours(service) == 504

    def test_a_ninety_hour_guarantee_requires_648_hours(self) -> None:
        service = FlightCrewService(duty_or_paid_hours=0, applicable_monthly_guarantee=90)

        assert required_flight_crew_guarantee_hours(service) == 648

    def test_a_zero_guarantee_requires_nothing_from_that_clause(self) -> None:
        """The 504-hour floor still applies, which the next tests assert."""
        service = FlightCrewService(duty_or_paid_hours=0, applicable_monthly_guarantee=0)

        assert required_flight_crew_guarantee_hours(service) == 0

    def test_both_conditions_must_hold(self) -> None:
        service = FlightCrewService(duty_or_paid_hours=520, applicable_monthly_guarantee=70)

        assert flight_crew_hours_satisfied(service) is True

    def test_one_hour_below_the_floor_fails(self) -> None:
        service = FlightCrewService(duty_or_paid_hours=503, applicable_monthly_guarantee=60)

        assert flight_crew_hours_satisfied(service) is False

    def test_exactly_the_floor_passes_when_the_guarantee_is_met(self) -> None:
        service = FlightCrewService(duty_or_paid_hours=504, applicable_monthly_guarantee=60)

        assert flight_crew_hours_satisfied(service) is True

    def test_clearing_the_floor_but_not_the_guarantee_fails(self) -> None:
        """THE AND, ASSERTED. An implementation using OR admits this crew member."""
        service = FlightCrewService(duty_or_paid_hours=600, applicable_monthly_guarantee=90)

        assert flight_crew_hours_satisfied(service) is False

    def test_the_evaluation_reports_the_binding_requirement(self) -> None:
        """observed AND required, which no earlier test looked at."""
        service = FlightCrewService(duty_or_paid_hours=600, applicable_monthly_guarantee=90)

        evaluation = evaluate_flight_crew_hours(service)

        assert evaluation.rule_id == RULE_CREW_HOURS
        assert evaluation.citation == "29 CFR 825.801(b)"
        assert evaluation.outcome is RuleOutcome.NOT_SATISFIED
        assert evaluation.observed == 600
        assert evaluation.required == 648

    def test_the_floor_binds_when_it_exceeds_the_guarantee_fraction(self) -> None:
        service = FlightCrewService(duty_or_paid_hours=100, applicable_monthly_guarantee=10)

        evaluation = evaluate_flight_crew_hours(service)

        assert evaluation.required == FLIGHT_CREW_HOURS_FLOOR

    def test_the_ordinary_hours_rule_is_not_applicable_to_crew(self) -> None:
        """NOT_APPLICABLE AND ITS CITATION, both of which mutants blanked."""
        evaluation = evaluate_hours(
            employee(
                employee_class=EmployeeClass.AIRLINE_FLIGHT_CREW,
                hours_worked_in_lookback=520,
            )
        )

        assert evaluation.rule_id == RULE_HOURS
        assert evaluation.citation == "29 CFR 825.801(a)"
        assert evaluation.outcome is RuleOutcome.NOT_APPLICABLE
        assert evaluation.observed == "airline_flight_crew"
        assert evaluation.required == HOURS_OF_SERVICE


# --- Military caregiver -------------------------------------------------------


class TestCaregiverRules:
    def test_each_named_relationship_qualifies(self) -> None:
        for relationship in (
            QualifyingRelationship.SPOUSE,
            QualifyingRelationship.PARENT,
            QualifyingRelationship.SON_OR_DAUGHTER,
            QualifyingRelationship.NEXT_OF_KIN,
        ):
            assert relationship_qualifies(caregiver(relationship=relationship)) is True

    def test_none_does_not_qualify(self) -> None:
        assert relationship_qualifies(caregiver(relationship=QualifyingRelationship.NONE)) is False

    def test_each_current_member_status_is_covered(self) -> None:
        for status in (
            ServicememberStatus.CURRENT_MEMBER_IN_TREATMENT,
            ServicememberStatus.OUTPATIENT_STATUS,
            ServicememberStatus.TEMPORARY_DISABILITY_RETIRED_LIST,
        ):
            assert (
                servicemember_is_covered(
                    caregiver(servicemember_status=status), leave_start=LEAVE_START
                )
                is True
            )

    def test_not_covered_is_not_covered(self) -> None:
        assert (
            servicemember_is_covered(
                caregiver(servicemember_status=ServicememberStatus.NOT_COVERED),
                leave_start=LEAVE_START,
            )
            is False
        )

    def test_a_veteran_discharged_within_five_years_is_covered(self) -> None:
        assert (
            veteran_is_covered(
                caregiver(
                    servicemember_status=ServicememberStatus.COVERED_VETERAN,
                    discharge_date=date(2022, 6, 1),
                    discharged_other_than_dishonorably=True,
                ),
                leave_start=LEAVE_START,
            )
            is True
        )

    def test_exactly_five_years_is_still_within_the_window(self) -> None:
        """825.122(a)(2) says WITHIN five years, so the boundary is inclusive."""
        assert (
            veteran_is_covered(
                caregiver(
                    servicemember_status=ServicememberStatus.COVERED_VETERAN,
                    discharge_date=date(2021, 3, 1),
                    discharged_other_than_dishonorably=True,
                ),
                leave_start=LEAVE_START,
            )
            is True
        )

    def test_one_month_past_five_years_is_outside_the_window(self) -> None:
        assert (
            veteran_is_covered(
                caregiver(
                    servicemember_status=ServicememberStatus.COVERED_VETERAN,
                    discharge_date=date(2021, 2, 1),
                    discharged_other_than_dishonorably=True,
                ),
                leave_start=LEAVE_START,
            )
            is False
        )

    def test_a_dishonorable_discharge_is_not_covered(self) -> None:
        assert (
            veteran_is_covered(
                caregiver(
                    servicemember_status=ServicememberStatus.COVERED_VETERAN,
                    discharge_date=date(2025, 6, 1),
                    discharged_other_than_dishonorably=False,
                ),
                leave_start=LEAVE_START,
            )
            is False
        )

    def test_a_missing_discharge_character_is_not_covered(self) -> None:
        """None IS NOT TRUE. An unverifiable claim is not an established one."""
        assert (
            veteran_is_covered(
                caregiver(
                    servicemember_status=ServicememberStatus.COVERED_VETERAN,
                    discharge_date=date(2025, 6, 1),
                    discharged_other_than_dishonorably=None,
                ),
                leave_start=LEAVE_START,
            )
            is False
        )

    def test_a_missing_discharge_date_is_not_covered(self) -> None:
        assert (
            veteran_is_covered(
                caregiver(
                    servicemember_status=ServicememberStatus.COVERED_VETERAN,
                    discharge_date=None,
                    discharged_other_than_dishonorably=True,
                ),
                leave_start=LEAVE_START,
            )
            is False
        )

    def test_the_caregiver_evaluations_carry_their_citations_and_evidence(self) -> None:
        """BOTH RULES, IN ORDER, WITH EVERY FIELD.

        Mutants blanked each of these strings and survived, because the
        acceptance suite only ever looked at outcomes.
        """
        relationship, servicemember = evaluate_caregiver(
            caregiver(relationship=QualifyingRelationship.NEXT_OF_KIN), leave_start=LEAVE_START
        )

        assert relationship.rule_id == RULE_RELATIONSHIP
        assert relationship.citation == "29 CFR 825.122(e)"
        assert relationship.outcome is RuleOutcome.SATISFIED
        assert relationship.observed == "next_of_kin"
        assert relationship.required == "spouse, parent, son or daughter, or next of kin"

        assert servicemember.rule_id == RULE_SERVICEMEMBER
        assert servicemember.citation == "29 CFR 825.122(a)"
        assert servicemember.outcome is RuleOutcome.SATISFIED
        assert servicemember.observed == "current_member_in_treatment"
        assert servicemember.required == (
            "current member in treatment, outpatient, TDRL, or covered veteran"
        )

    def test_exactly_two_caregiver_rules_are_produced(self) -> None:
        assert len(evaluate_caregiver(caregiver(), leave_start=LEAVE_START)) == 2


# --- Evaluations: evidence and citations --------------------------------------


class TestEvaluationEvidence:
    def test_the_employer_rule_reports_the_type_when_covered(self) -> None:
        evaluation = evaluate_employer(employer(employer_type=EmployerType.PUBLIC_AGENCY))

        assert evaluation.rule_id == RULE_EMPLOYER
        assert evaluation.citation == "29 CFR 825.104(a)"
        assert evaluation.outcome is RuleOutcome.SATISFIED
        assert evaluation.observed == "public_agency"
        assert evaluation.required == COVERED_EMPLOYER_WORKWEEKS

    def test_the_employer_rule_reports_the_workweeks_when_not_covered(self) -> None:
        """THE HIGHER OF THE TWO YEARS, because that is the one that decided it."""
        evaluation = evaluate_employer(
            employer(
                workweeks_with_50_employees_current_year=3,
                workweeks_with_50_employees_preceding_year=7,
            )
        )

        assert evaluation.outcome is RuleOutcome.NOT_SATISFIED
        assert evaluation.observed == 7

    def test_a_school_is_covered_without_a_headcount(self) -> None:
        assert (
            employer_is_covered(
                employer(
                    employer_type=EmployerType.SCHOOL,
                    workweeks_with_50_employees_current_year=0,
                    workweeks_with_50_employees_preceding_year=0,
                )
            )
            is True
        )

    def test_the_preceding_year_alone_establishes_coverage(self) -> None:
        assert (
            employer_is_covered(
                employer(
                    workweeks_with_50_employees_current_year=0,
                    workweeks_with_50_employees_preceding_year=20,
                )
            )
            is True
        )

    def test_the_tenure_rule_reports_months_and_its_citation(self) -> None:
        evaluation = evaluate_tenure(employee(), as_of=LEAVE_START)

        assert evaluation.rule_id == RULE_TENURE
        assert evaluation.citation == "29 CFR 825.110(a)(1)"
        assert evaluation.outcome is RuleOutcome.SATISFIED
        assert evaluation.observed == 26
        assert evaluation.required == 12

    def test_the_hours_rule_reports_credited_hours_not_raw_hours(self) -> None:
        """THE OBSERVED VALUE IS THE ONE THE RULE JUDGED.

        Reporting the raw figure while deciding on the credited one would make
        the evidence contradict the outcome.
        """
        evaluation = evaluate_hours(
            employee(
                hours_worked_in_lookback=600,
                userra_service=UserraService(months_absent=10, pre_service_weekly_hours=40),
            )
        )

        assert evaluation.citation == "29 CFR 825.110(a)(2)"
        assert evaluation.observed == 2333
        assert evaluation.required == HOURS_OF_SERVICE

    def test_the_worksite_rule_reports_its_citation(self) -> None:
        evaluation = evaluate_worksite(employee())

        assert evaluation.rule_id == RULE_WORKSITE
        assert evaluation.citation == "29 CFR 825.110(a)(3)"


# --- Entitlement --------------------------------------------------------------


class TestEntitlement:
    def test_an_ordinary_eligible_leave_is_twelve_weeks(self) -> None:
        weeks = entitlement_weeks_for(
            EligibilityVerdict.ELIGIBLE, LeaveReason.OWN_SERIOUS_HEALTH_CONDITION
        )

        assert weeks == ORDINARY_ENTITLEMENT_WEEKS

    def test_military_caregiver_leave_is_twenty_six_weeks(self) -> None:
        weeks = entitlement_weeks_for(EligibilityVerdict.ELIGIBLE, LeaveReason.MILITARY_CAREGIVER)

        assert weeks == CAREGIVER_ENTITLEMENT_WEEKS

    def test_every_other_reason_receives_the_ordinary_entitlement(self) -> None:
        for reason in (
            LeaveReason.BIRTH,
            LeaveReason.PLACEMENT,
            LeaveReason.FAMILY_SERIOUS_HEALTH_CONDITION,
            LeaveReason.QUALIFYING_EXIGENCY,
        ):
            assert (
                entitlement_weeks_for(EligibilityVerdict.ELIGIBLE, reason)
                == ORDINARY_ENTITLEMENT_WEEKS
            )

    def test_an_ineligible_employee_has_no_entitlement_rather_than_zero(self) -> None:
        """NONE, NOT 0. Zero would let a consumer treat a denial as an exhausted
        balance, which is a different appeal and a different remedy."""
        assert (
            entitlement_weeks_for(
                EligibilityVerdict.INELIGIBLE, LeaveReason.OWN_SERIOUS_HEALTH_CONDITION
            )
            is None
        )

    def test_an_ineligible_caregiver_leave_also_has_no_entitlement(self) -> None:
        assert (
            entitlement_weeks_for(EligibilityVerdict.INELIGIBLE, LeaveReason.MILITARY_CAREGIVER)
            is None
        )


@pytest.mark.parametrize(
    ("employee_class", "expected"),
    [
        (EmployeeClass.STANDARD, RuleOutcome.SATISFIED),
        (EmployeeClass.AIRLINE_FLIGHT_CREW, RuleOutcome.NOT_APPLICABLE),
    ],
)
def test_the_hours_rule_applies_only_to_standard_employees(
    employee_class: EmployeeClass, expected: RuleOutcome
) -> None:
    assert evaluate_hours(employee(employee_class=employee_class)).outcome is expected
