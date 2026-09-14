# tests/acceptance/test_fmla_eligibility.py
# SLICE 2, THE OUTERMOST TEST OF THE PRODUCT ITSELF.
#
# THE SPECIFICATION IS THE REGULATION, CITED PER RULE. Every assertion below
# traces to a provision of 29 CFR part 825, and the rule_id in the response
# carries that citation back to the caller. A determination this service cannot
# attribute to a provision is one it has no business issuing.
#
#   825.104(a)    covered employer: 50+ employees each working day in each of
#                 20+ calendar workweeks, current OR preceding calendar year.
#                 Public agencies and elementary/secondary schools are covered
#                 WITHOUT REGARD to headcount.
#   825.110(a)    the three eligibility conditions.
#   825.110(b)    the 12 months NEED NOT BE CONSECUTIVE; service before a break
#                 of 7+ years need not be counted -- EXCEPT where the break was
#                 USERRA service or a written rehire agreement exists.
#   825.110(c)(2) USERRA returnees are credited the hours they WOULD have
#                 worked, added to hours actually worked.
#   825.110(d)    eligibility is determined AS OF THE DATE LEAVE IS TO START.
#   825.801(b)    airline flight crew instead need 60% of the applicable
#                 monthly guarantee AND 504 hours.
#   825.122(a)    covered servicemember; 825.122(e) next of kin.
#   825.127(e)    26 workweeks in a single 12-month period.
#
# WHY THE RESPONSE CARRIES A RULE CHAIN RATHER THAN A BOOLEAN. A regulator, or
# a denied employee, asks "why". "The system said no" is not an answer this
# product is permitted to give. Each rule reports what was OBSERVED and what the
# regulation REQUIRED -- policy as code producing evidence as data.
#
# STRONG ASSERTIONS THROUGHOUT (section 2.1.2 of the source). Asserting that a
# determination came back would pass against a service that approves everyone.
# Each test pins the EXACT verdict, the EXACT entitlement, and the EXACT rules.

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from cs1090a_spec_driven_development.app import app
from cs1090a_spec_driven_development.contracts.fmla import (
    Determination,
    EligibilityVerdict,
    EmployeeClass,
    EmployerType,
    LeaveReason,
    QualifyingRelationship,
    RuleOutcome,
    ServicememberStatus,
)

DETERMINATIONS = "/fmla/determinations"

EMPLOYER = "fmla.employer.covered"
TENURE = "fmla.tenure.12_months"
HOURS = "fmla.hours.1250_in_lookback"
WORKSITE = "fmla.worksite.50_within_75_miles"
CREW_HOURS = "fmla.flight_crew.hours_of_service"
RELATIONSHIP = "fmla.military_caregiver.qualifying_relationship"
SERVICEMEMBER = "fmla.military_caregiver.covered_servicemember"


async def determine(payload: dict[str, Any]) -> Determination:
    """Post the facts and validate the response against the published contract.

    VALIDATED, NOT SUBSCRIPTED. Reading response.json()["verdict"] would pass
    against any dict carrying that key, including one from another route.
    Parsing through the model makes a renamed or retyped field fail HERE rather
    than silently change what consumers receive.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://leave") as client:
        response = await client.post(DETERMINATIONS, json=payload)

    assert response.status_code == 200, response.text
    return Determination.model_validate(response.json())


def outcome_of(determination: Determination, rule_id: str) -> RuleOutcome:
    """Find one rule's outcome, failing loudly when the rule was never evaluated.

    A MISSING RULE IS NOT A PASSING RULE. Returning NOT_APPLICABLE for an absent
    rule_id would let an implementation that quietly stopped evaluating a
    condition keep every test green.
    """
    matches = [rule for rule in determination.rules if rule.rule_id == rule_id]
    assert len(matches) == 1, f"expected exactly one {rule_id}, got {len(matches)}"
    return matches[0].outcome


def rule_ids(determination: Determination) -> set[str]:
    return {rule.rule_id for rule in determination.rules}


def unmet(determination: Determination) -> set[str]:
    return {
        rule.rule_id for rule in determination.rules if rule.outcome is RuleOutcome.NOT_SATISFIED
    }


def facts(**overrides: Any) -> dict[str, Any]:
    """An employee who satisfies every condition, before overrides.

    THE BASELINE IS DELIBERATELY ELIGIBLE so each test changes ONE fact and
    attributes the resulting denial to that fact. A baseline that already failed
    would let a test pass for the wrong reason.
    """
    baseline: dict[str, Any] = {
        "employer": {
            "employer_type": EmployerType.PRIVATE.value,
            "workweeks_with_50_employees_current_year": 22,
            "workweeks_with_50_employees_preceding_year": 0,
        },
        "employee": {
            "employee_class": EmployeeClass.STANDARD.value,
            "employment_periods": [{"start": "2024-01-01", "end": None}],
            "written_rehire_agreement": False,
            "userra_service": None,
            "hours_worked_in_lookback": 1400,
            "worksite_headcount_within_75_miles": 80,
            "flight_crew_service": None,
        },
        "leave": {
            "reason": LeaveReason.OWN_SERIOUS_HEALTH_CONDITION.value,
            "start_date": "2026-03-01",
            "military_caregiver": None,
        },
    }
    return baseline | overrides


def with_employer(**changes: Any) -> dict[str, Any]:
    return facts(employer=facts()["employer"] | changes)


def with_employee(**changes: Any) -> dict[str, Any]:
    return facts(employee=facts()["employee"] | changes)


def caregiver_leave(**caregiver: Any) -> dict[str, Any]:
    return facts(
        leave={
            "reason": LeaveReason.MILITARY_CAREGIVER.value,
            "start_date": "2026-03-01",
            "military_caregiver": caregiver,
        }
    )


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_an_employee_meeting_every_condition_is_entitled_to_twelve_weeks() -> None:
    determination = await determine(facts())

    assert determination.verdict is EligibilityVerdict.ELIGIBLE
    assert determination.entitlement_weeks == 12

    # EVERY RULE IS REPORTED, NOT ONLY THE FAILING ONES. A determination listing
    # only failures could not distinguish "all conditions passed" from "only one
    # was ever evaluated".
    assert rule_ids(determination) == {EMPLOYER, TENURE, HOURS, WORKSITE}
    assert unmet(determination) == set()


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_a_private_employer_below_the_threshold_in_both_years_is_not_covered() -> None:
    determination = await determine(
        with_employer(
            workweeks_with_50_employees_current_year=19,
            workweeks_with_50_employees_preceding_year=19,
        )
    )

    assert determination.verdict is EligibilityVerdict.INELIGIBLE
    # NO ENTITLEMENT, NOT A ZERO-WEEK ENTITLEMENT. An ineligible employee has no
    # statutory entitlement at all; representing that as 0 would let a consumer
    # treat a denial as an exhausted balance.
    assert determination.entitlement_weeks is None
    assert EMPLOYER in unmet(determination)


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_the_preceding_calendar_year_alone_establishes_coverage() -> None:
    """825.105(f): coverage attained in the preceding year persists.

    THE OR IS LOAD-BEARING. An implementation testing only the current year
    denies leave at every employer with seasonal headcount -- precisely the
    population 825.105(f) was written to protect.
    """
    determination = await determine(
        with_employer(
            workweeks_with_50_employees_current_year=0,
            workweeks_with_50_employees_preceding_year=20,
        )
    )

    assert outcome_of(determination, EMPLOYER) is RuleOutcome.SATISFIED
    assert determination.verdict is EligibilityVerdict.ELIGIBLE


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_twenty_workweeks_passes_and_nineteen_fails() -> None:
    """The threshold boundary, asserted in both directions."""
    at_threshold = await determine(
        with_employer(
            workweeks_with_50_employees_current_year=20,
            workweeks_with_50_employees_preceding_year=0,
        )
    )
    assert outcome_of(at_threshold, EMPLOYER) is RuleOutcome.SATISFIED

    below = await determine(
        with_employer(
            workweeks_with_50_employees_current_year=19,
            workweeks_with_50_employees_preceding_year=0,
        )
    )
    assert outcome_of(below, EMPLOYER) is RuleOutcome.NOT_SATISFIED


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_a_public_agency_is_covered_regardless_of_headcount() -> None:
    """825.104(a): public agencies are covered employers with no headcount test."""
    determination = await determine(
        with_employer(
            employer_type=EmployerType.PUBLIC_AGENCY.value,
            workweeks_with_50_employees_current_year=0,
            workweeks_with_50_employees_preceding_year=0,
        )
    )

    assert outcome_of(determination, EMPLOYER) is RuleOutcome.SATISFIED


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_a_school_is_covered_regardless_of_headcount() -> None:
    """825.104(a): public AND private elementary/secondary schools are covered."""
    determination = await determine(
        with_employer(
            employer_type=EmployerType.SCHOOL.value,
            workweeks_with_50_employees_current_year=0,
            workweeks_with_50_employees_preceding_year=0,
        )
    )

    assert outcome_of(determination, EMPLOYER) is RuleOutcome.SATISFIED


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_nonconsecutive_service_within_seven_years_counts_toward_twelve_months() -> None:
    """825.110(b): the 12 months need not be consecutive.

    Seven months in 2021 plus six months to the 2026 leave date exceeds twelve,
    and the break is under seven years, so both periods count.
    """
    determination = await determine(
        with_employee(
            employment_periods=[
                {"start": "2021-01-01", "end": "2021-08-01"},
                {"start": "2025-09-01", "end": None},
            ],
        )
    )

    assert outcome_of(determination, TENURE) is RuleOutcome.SATISFIED
    assert determination.verdict is EligibilityVerdict.ELIGIBLE


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_service_before_a_break_of_more_than_seven_years_is_not_counted() -> None:
    """825.110(b)(1): pre-break service need not be counted past seven years."""
    determination = await determine(
        with_employee(
            employment_periods=[
                {"start": "2010-01-01", "end": "2015-01-01"},
                {"start": "2025-11-01", "end": None},
            ],
        )
    )

    assert outcome_of(determination, TENURE) is RuleOutcome.NOT_SATISFIED
    assert determination.verdict is EligibilityVerdict.INELIGIBLE


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_a_written_rehire_agreement_restores_service_before_a_long_break() -> None:
    """825.110(b)(2)(ii): a written rehire agreement forces the earlier period to count."""
    determination = await determine(
        with_employee(
            employment_periods=[
                {"start": "2010-01-01", "end": "2015-01-01"},
                {"start": "2025-11-01", "end": None},
            ],
            written_rehire_agreement=True,
        )
    )

    assert outcome_of(determination, TENURE) is RuleOutcome.SATISFIED


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_userra_absence_counts_toward_tenure_and_credits_hours() -> None:
    """825.110(b)(2)(i) and (c)(2): both effects, in one employee.

    Four months of actual service is not twelve; adding the ten-month USERRA
    absence makes it fourteen. Likewise 600 actual hours falls short of 1,250,
    but the hours that WOULD have been worked on the pre-service schedule are
    added to the hours actually worked.
    """
    determination = await determine(
        with_employee(
            employment_periods=[{"start": "2025-11-01", "end": None}],
            hours_worked_in_lookback=600,
            userra_service={"months_absent": 10, "pre_service_weekly_hours": 40},
        )
    )

    assert outcome_of(determination, TENURE) is RuleOutcome.SATISFIED
    assert outcome_of(determination, HOURS) is RuleOutcome.SATISFIED
    assert determination.verdict is EligibilityVerdict.ELIGIBLE


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_exactly_the_hours_threshold_is_eligible_and_one_hour_short_is_not() -> None:
    """The boundary asserted in BOTH directions.

    An off-by-one in a statutory threshold denies leave to precisely the
    population the threshold was written to include.
    """
    at_threshold = await determine(with_employee(hours_worked_in_lookback=1250))
    assert outcome_of(at_threshold, HOURS) is RuleOutcome.SATISFIED

    below = await determine(with_employee(hours_worked_in_lookback=1249))
    assert outcome_of(below, HOURS) is RuleOutcome.NOT_SATISFIED
    assert unmet(below) == {HOURS}


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_the_worksite_headcount_boundary_holds_in_both_directions() -> None:
    at_threshold = await determine(with_employee(worksite_headcount_within_75_miles=50))
    assert outcome_of(at_threshold, WORKSITE) is RuleOutcome.SATISFIED

    below = await determine(with_employee(worksite_headcount_within_75_miles=49))
    assert outcome_of(below, WORKSITE) is RuleOutcome.NOT_SATISFIED


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_flight_crew_are_judged_on_the_crew_rule_and_not_the_1250_rule() -> None:
    """825.801(b): 60% of the applicable monthly guarantee AND 504 hours.

    520 duty hours would FAIL the ordinary 1,250-hour test. The crew rule
    REPLACES that test rather than supplementing it, so the 1,250 rule must
    report NOT_APPLICABLE -- reporting it as failed would deny an eligible crew
    member on a rule that does not apply to them.
    """
    determination = await determine(
        with_employee(
            employee_class=EmployeeClass.AIRLINE_FLIGHT_CREW.value,
            hours_worked_in_lookback=520,
            flight_crew_service={"duty_or_paid_hours": 520, "applicable_monthly_guarantee": 70},
        )
    )

    assert outcome_of(determination, HOURS) is RuleOutcome.NOT_APPLICABLE
    assert outcome_of(determination, CREW_HOURS) is RuleOutcome.SATISFIED
    assert determination.verdict is EligibilityVerdict.ELIGIBLE


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_flight_crew_failing_either_crew_condition_are_ineligible() -> None:
    """BOTH conditions are required, so each is failed independently.

    503 hours misses the 504-hour floor while clearing 60% of a 60-hour monthly
    guarantee; the second case clears 504 hours while falling under 60% of a
    90-hour guarantee. An implementation joining the two with OR passes both.
    """
    short_hours = await determine(
        with_employee(
            employee_class=EmployeeClass.AIRLINE_FLIGHT_CREW.value,
            flight_crew_service={"duty_or_paid_hours": 503, "applicable_monthly_guarantee": 60},
        )
    )
    assert outcome_of(short_hours, CREW_HOURS) is RuleOutcome.NOT_SATISFIED

    short_guarantee = await determine(
        with_employee(
            employee_class=EmployeeClass.AIRLINE_FLIGHT_CREW.value,
            flight_crew_service={"duty_or_paid_hours": 600, "applicable_monthly_guarantee": 90},
        )
    )
    assert outcome_of(short_guarantee, CREW_HOURS) is RuleOutcome.NOT_SATISFIED


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_the_crew_rule_is_not_applicable_to_a_standard_employee() -> None:
    """Symmetry with the previous test: the two hours rules are mutually exclusive."""
    determination = await determine(facts())

    assert CREW_HOURS not in rule_ids(determination)
    assert outcome_of(determination, HOURS) is RuleOutcome.SATISFIED


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_military_caregiver_leave_is_twenty_six_weeks() -> None:
    """825.127(e): 26 workweeks, not 12.

    A service returning 12 here understates a protected leave by fourteen weeks.
    """
    determination = await determine(
        caregiver_leave(
            relationship=QualifyingRelationship.NEXT_OF_KIN.value,
            servicemember_status=ServicememberStatus.CURRENT_MEMBER_IN_TREATMENT.value,
            discharge_date=None,
            discharged_other_than_dishonorably=None,
        )
    )

    assert determination.verdict is EligibilityVerdict.ELIGIBLE
    assert determination.entitlement_weeks == 26
    assert outcome_of(determination, RELATIONSHIP) is RuleOutcome.SATISFIED
    assert outcome_of(determination, SERVICEMEMBER) is RuleOutcome.SATISFIED


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_outpatient_status_and_the_disability_retired_list_are_covered() -> None:
    """825.127(b)(1): three distinct current-member conditions, not one."""
    for status in (
        ServicememberStatus.OUTPATIENT_STATUS,
        ServicememberStatus.TEMPORARY_DISABILITY_RETIRED_LIST,
    ):
        determination = await determine(
            caregiver_leave(
                relationship=QualifyingRelationship.PARENT.value,
                servicemember_status=status.value,
                discharge_date=None,
                discharged_other_than_dishonorably=None,
            )
        )
        assert outcome_of(determination, SERVICEMEMBER) is RuleOutcome.SATISFIED


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_a_veteran_discharged_within_five_years_is_a_covered_servicemember() -> None:
    """825.122(a)(2): discharged other than dishonorably within the prior five years."""
    determination = await determine(
        caregiver_leave(
            relationship=QualifyingRelationship.SPOUSE.value,
            servicemember_status=ServicememberStatus.COVERED_VETERAN.value,
            discharge_date="2022-06-01",
            discharged_other_than_dishonorably=True,
        )
    )

    assert outcome_of(determination, SERVICEMEMBER) is RuleOutcome.SATISFIED
    assert determination.entitlement_weeks == 26


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_a_veteran_discharged_more_than_five_years_ago_is_not_covered() -> None:
    determination = await determine(
        caregiver_leave(
            relationship=QualifyingRelationship.SPOUSE.value,
            servicemember_status=ServicememberStatus.COVERED_VETERAN.value,
            discharge_date="2020-06-01",
            discharged_other_than_dishonorably=True,
        )
    )

    assert determination.verdict is EligibilityVerdict.INELIGIBLE
    assert SERVICEMEMBER in unmet(determination)


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_a_dishonorable_discharge_is_not_a_covered_veteran() -> None:
    determination = await determine(
        caregiver_leave(
            relationship=QualifyingRelationship.SPOUSE.value,
            servicemember_status=ServicememberStatus.COVERED_VETERAN.value,
            discharge_date="2025-06-01",
            discharged_other_than_dishonorably=False,
        )
    )

    assert SERVICEMEMBER in unmet(determination)


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_a_relative_without_next_of_kin_standing_fails_the_relationship_rule() -> None:
    """825.122(e): next of kin is a specific priority order, not any relative."""
    determination = await determine(
        caregiver_leave(
            relationship=QualifyingRelationship.NONE.value,
            servicemember_status=ServicememberStatus.OUTPATIENT_STATUS.value,
            discharge_date=None,
            discharged_other_than_dishonorably=None,
        )
    )

    assert determination.verdict is EligibilityVerdict.INELIGIBLE
    assert RELATIONSHIP in unmet(determination)


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_military_caregiver_rules_are_absent_from_an_ordinary_determination() -> None:
    """The caregiver rules must not silently pass when they were never relevant.

    AN UNEVALUATED RULE IS NOT A SATISFIED RULE. Reporting one as satisfied is
    how an audit trail comes to describe a check that never ran.
    """
    determination = await determine(facts())

    assert RELATIONSHIP not in rule_ids(determination)
    assert SERVICEMEMBER not in rule_ids(determination)


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_every_failing_rule_is_reported_not_only_the_first() -> None:
    """A denial names EVERY unmet condition.

    SHORT-CIRCUITING IS THE BUG THIS PREVENTS. An implementation returning on
    the first failure produces a denial the employee can only cure one round at
    a time -- and each round trip is a leave request, not a form field.
    """
    determination = await determine(
        facts(
            employer=facts()["employer"]
            | {
                "workweeks_with_50_employees_current_year": 3,
                "workweeks_with_50_employees_preceding_year": 3,
            },
            employee=facts()["employee"]
            | {
                "employment_periods": [{"start": "2025-12-01", "end": None}],
                "hours_worked_in_lookback": 200,
                "worksite_headcount_within_75_miles": 10,
            },
        )
    )

    assert determination.verdict is EligibilityVerdict.INELIGIBLE
    assert unmet(determination) == {EMPLOYER, TENURE, HOURS, WORKSITE}


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_every_rule_carries_its_regulatory_citation() -> None:
    """A rule without a citation cannot be defended to a regulator.

    THIS IS THE PRODUCT'S CENTRAL CLAIM, ASSERTED RATHER THAN DESCRIBED. The
    service sells auditable determinations; a rule that cannot name the
    provision it applied is an opinion with an identifier.
    """
    determination = await determine(facts())

    for rule in determination.rules:
        assert rule.citation.startswith("29 CFR 825."), rule.citation
