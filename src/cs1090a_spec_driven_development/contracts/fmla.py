# src/cs1090a_spec_driven_development/contracts/fmla.py
# THE FMLA DOMAIN, AS CONTRACTS. 29 CFR part 825, expressed as types and rules.
#
# THE SPECIFICATION IS THE REGULATION. Every rule below carries the provision it
# applies, and the citation travels with the determination. A determination this
# service cannot attribute to a provision is one it has no business issuing --
# the party who asks "why was this denied" is a regulator or the employee.
#
# POLICY AS CODE PRODUCING EVIDENCE AS DATA. Each rule reports what was OBSERVED
# and what the regulation REQUIRED, and the verdict is DERIVED from the rules.
# Nothing in this module decides eligibility directly; the decision falls out of
# the evaluations, which is what makes the audit trail complete by construction
# rather than by discipline.
#
# EVERY RULE IS A PLAIN UNDECORATED MODULE-LEVEL FUNCTION. mutmut 3 skips
# decorated functions, so a rule living inside a @field_validator or an @app.post
# handler would be invisible to mutation testing -- and a surviving mutant in an
# eligibility rule is a statute this service can get wrong with no test
# objecting. The routes delegate; the rules are measured.
#
# NOT_APPLICABLE IS NOT A PASS. A rule that did not apply and a rule that was
# satisfied are different facts, and collapsing them is how an audit trail comes
# to describe a check that never ran.

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

# --- Thresholds, each with its provision ---------------------------------------
# NAMED CONSTANTS RATHER THAN LITERALS AT THE COMPARISON. A bare `>= 1250` in a
# branch is a number nobody can trace to a statute, and it is the first thing to
# be "adjusted" during a debugging session.
COVERED_EMPLOYER_WORKWEEKS = 20  # 825.104(a)
TENURE_MONTHS = 12  # 825.110(a)(1)
HOURS_OF_SERVICE = 1250  # 825.110(a)(2)
WORKSITE_HEADCOUNT = 50  # 825.110(a)(3)
BREAK_IN_SERVICE_MONTHS = 84  # 825.110(b)(1): seven years
FLIGHT_CREW_HOURS_FLOOR = 504  # 825.801(b)(2)
FLIGHT_CREW_GUARANTEE_NUMERATOR = 60  # 825.801(b)(1): 60 percent
FLIGHT_CREW_GUARANTEE_DENOMINATOR = 100
MONTHS_IN_YEAR = 12
WEEKS_IN_YEAR = 52
ORDINARY_ENTITLEMENT_WEEKS = 12  # 825.200(a)
CAREGIVER_ENTITLEMENT_WEEKS = 26  # 825.127(e)
VETERAN_LOOKBACK_MONTHS = 60  # 825.122(a)(2): five years

RULE_EMPLOYER = "fmla.employer.covered"
RULE_TENURE = "fmla.tenure.12_months"
RULE_HOURS = "fmla.hours.1250_in_lookback"
RULE_WORKSITE = "fmla.worksite.50_within_75_miles"
RULE_CREW_HOURS = "fmla.flight_crew.hours_of_service"
RULE_RELATIONSHIP = "fmla.military_caregiver.qualifying_relationship"
RULE_SERVICEMEMBER = "fmla.military_caregiver.covered_servicemember"


class EmployerType(StrEnum):
    """825.104(a). Coverage is not a single test.

    PUBLIC_AGENCY and SCHOOL are covered WITHOUT REGARD to headcount. Treating
    every employer as private would deny leave at every small school district in
    the country.
    """

    PRIVATE = "private"
    PUBLIC_AGENCY = "public_agency"
    SCHOOL = "school"


class EmployeeClass(StrEnum):
    """825.801. Flight crew are measured by a different hours rule entirely."""

    STANDARD = "standard"
    AIRLINE_FLIGHT_CREW = "airline_flight_crew"


class LeaveReason(StrEnum):
    """825.112(a). The reason selects the entitlement, not merely the paperwork."""

    BIRTH = "birth"
    PLACEMENT = "placement"
    FAMILY_SERIOUS_HEALTH_CONDITION = "family_serious_health_condition"
    OWN_SERIOUS_HEALTH_CONDITION = "own_serious_health_condition"
    QUALIFYING_EXIGENCY = "qualifying_exigency"
    MILITARY_CAREGIVER = "military_caregiver"


class QualifyingRelationship(StrEnum):
    """825.122(e). NEXT_OF_KIN is a defined priority order, not any relative.

    NONE EXISTS SO THE ABSENCE IS REPRESENTABLE. Omitting it would force a
    caller with no qualifying relationship to pick one that does qualify.
    """

    SPOUSE = "spouse"
    PARENT = "parent"
    SON_OR_DAUGHTER = "son_or_daughter"
    NEXT_OF_KIN = "next_of_kin"
    NONE = "none"


class ServicememberStatus(StrEnum):
    """825.122(a). Three current-member conditions, plus the covered veteran."""

    CURRENT_MEMBER_IN_TREATMENT = "current_member_in_treatment"
    OUTPATIENT_STATUS = "outpatient_status"
    TEMPORARY_DISABILITY_RETIRED_LIST = "temporary_disability_retired_list"
    COVERED_VETERAN = "covered_veteran"
    NOT_COVERED = "not_covered"


class RuleOutcome(StrEnum):
    """What one regulatory condition concluded."""

    SATISFIED = "satisfied"
    NOT_SATISFIED = "not_satisfied"
    NOT_APPLICABLE = "not_applicable"


class EligibilityVerdict(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"


class EmploymentPeriod(BaseModel):
    """One span of employment. `end` is None while the employee is still working."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: date
    end: date | None = None


class UserraService(BaseModel):
    """825.110(b)(2)(i) and (c)(2): protected military service.

    BOTH EFFECTS COME FROM ONE FACT. The absence counts toward the twelve
    months, and the hours that would have been worked are added to the hours
    actually worked. Modelling them separately would let a caller supply one
    without the other.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    months_absent: int = Field(ge=0)
    pre_service_weekly_hours: int = Field(ge=0)


class FlightCrewService(BaseModel):
    """825.801(b). Duty or paid hours, and the applicable monthly guarantee."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    duty_or_paid_hours: int = Field(ge=0)
    applicable_monthly_guarantee: int = Field(ge=0)


class MilitaryCaregiver(BaseModel):
    """825.127. Who is caring, and for whom."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    relationship: QualifyingRelationship
    servicemember_status: ServicememberStatus
    discharge_date: date | None = None
    discharged_other_than_dishonorably: bool | None = None


class Employer(BaseModel):
    """825.104(a), 825.105(f)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    employer_type: EmployerType
    workweeks_with_50_employees_current_year: int = Field(ge=0, le=53)
    workweeks_with_50_employees_preceding_year: int = Field(ge=0, le=53)


class Employee(BaseModel):
    """825.110. The facts the three conditions are measured against."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    employee_class: EmployeeClass
    employment_periods: list[EmploymentPeriod] = Field(min_length=1)
    written_rehire_agreement: bool = False
    userra_service: UserraService | None = None
    hours_worked_in_lookback: int = Field(ge=0)
    worksite_headcount_within_75_miles: int = Field(ge=0)
    flight_crew_service: FlightCrewService | None = None


class Leave(BaseModel):
    """825.110(d): eligibility is determined as of the date leave is to start."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: LeaveReason
    start_date: date
    military_caregiver: MilitaryCaregiver | None = None


class DeterminationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    employer: Employer
    employee: Employee
    leave: Leave


class RuleEvaluation(BaseModel):
    """One regulatory condition, with its citation and its evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str = Field(min_length=1)
    citation: str = Field(min_length=1)
    outcome: RuleOutcome
    observed: int | str | None = None
    required: int | str | None = None


class Determination(BaseModel):
    """The answer, and the whole chain that produced it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: EligibilityVerdict
    entitlement_weeks: int | None = Field(default=None, ge=0)
    rules: list[RuleEvaluation] = Field(min_length=1)


def months_between(start: date, end: date) -> int:
    """Whole months elapsed.

    THE DAY-OF-MONTH ADJUSTMENT IS NOT PEDANTRY. Counting calendar-month
    boundaries alone would credit a full month to someone employed from the 31st
    to the 1st, which is how an employee becomes eligible a month early.
    """
    months = (end.year - start.year) * MONTHS_IN_YEAR + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def countable_periods(
    periods: list[EmploymentPeriod],
    *,
    as_of: date,
    written_rehire_agreement: bool,
    has_userra_service: bool,
) -> list[EmploymentPeriod]:
    """Drop service severed by a break of more than seven years.

    825.110(b)(1) permits an employer not to count it. TWO EXCEPTIONS RESTORE
    IT: 825.110(b)(2)(i) where the break was USERRA service, and (b)(2)(ii)
    where a written agreement reflects an intention to rehire.

    THE SCAN DISCARDS EVERYTHING BEFORE THE LAST QUALIFYING BREAK, not merely
    the one period preceding it. An employee with three stints either side of a
    long gap must not keep the earliest two.
    """
    if written_rehire_agreement or has_userra_service:
        return periods

    ordered = sorted(periods, key=lambda period: period.start)
    kept = list(ordered)
    for index in range(len(ordered) - 1):
        finished = ordered[index].end or as_of
        gap = months_between(finished, ordered[index + 1].start)
        if gap > BREAK_IN_SERVICE_MONTHS:
            kept = ordered[index + 1 :]
    return kept


def months_of_service(employee: Employee, *, as_of: date) -> int:
    """Total countable months, including any USERRA absence.

    825.110(b): the months NEED NOT BE CONSECUTIVE, so the periods are summed
    rather than measured from the earliest start.
    """
    periods = countable_periods(
        employee.employment_periods,
        as_of=as_of,
        written_rehire_agreement=employee.written_rehire_agreement,
        has_userra_service=employee.userra_service is not None,
    )
    worked = sum(months_between(period.start, period.end or as_of) for period in periods)
    absent = employee.userra_service.months_absent if employee.userra_service else 0
    return worked + absent


def userra_credited_hours(service: UserraService | None) -> int:
    """825.110(c)(2): the hours that WOULD have been worked.

    Computed from the pre-service schedule, which is the regulation's own
    measure -- not from an average of hours actually worked, which would be
    depressed by the very absence being credited.
    """
    if service is None:
        return 0
    weeks = service.months_absent * WEEKS_IN_YEAR / MONTHS_IN_YEAR
    return int(weeks * service.pre_service_weekly_hours)


def hours_of_service(employee: Employee) -> int:
    return employee.hours_worked_in_lookback + userra_credited_hours(employee.userra_service)


def required_flight_crew_guarantee_hours(service: FlightCrewService) -> int:
    """825.801(b)(1): sixty percent of the applicable monthly guarantee.

    The guarantee is MONTHLY and the period is twelve months, so it is scaled
    before the percentage is applied. INTEGER ARITHMETIC, ORDERED TO MULTIPLY
    FIRST: dividing by 100 before multiplying truncates the percentage to zero.
    """
    annual = service.applicable_monthly_guarantee * MONTHS_IN_YEAR
    return annual * FLIGHT_CREW_GUARANTEE_NUMERATOR // FLIGHT_CREW_GUARANTEE_DENOMINATOR


def employer_is_covered(employer: Employer) -> bool:
    """825.104(a) and 825.105(f).

    THE OR ACROSS YEARS IS LOAD-BEARING. Coverage attained in the preceding year
    persists; testing only the current year denies leave at every employer with
    seasonal headcount.
    """
    if employer.employer_type in (EmployerType.PUBLIC_AGENCY, EmployerType.SCHOOL):
        return True
    reached = max(
        employer.workweeks_with_50_employees_current_year,
        employer.workweeks_with_50_employees_preceding_year,
    )
    return reached >= COVERED_EMPLOYER_WORKWEEKS


def flight_crew_hours_satisfied(service: FlightCrewService) -> bool:
    """825.801(b): BOTH conditions, joined by AND.

    An implementation using OR admits a crew member who met neither the floor
    nor the guarantee fraction, provided they met one.
    """
    if service.duty_or_paid_hours < FLIGHT_CREW_HOURS_FLOOR:
        return False
    return service.duty_or_paid_hours >= required_flight_crew_guarantee_hours(service)


def relationship_qualifies(caregiver: MilitaryCaregiver) -> bool:
    """825.122(e): next of kin is a defined order; a cousin is not automatically it."""
    return caregiver.relationship is not QualifyingRelationship.NONE


def veteran_is_covered(caregiver: MilitaryCaregiver, *, leave_start: date) -> bool:
    """825.122(a)(2): discharged other than dishonorably, within five years.

    BOTH CONDITIONS, AND A MISSING DATE IS A FAILURE RATHER THAN A PASS. A
    veteran claim with no discharge date cannot be verified, and an unverifiable
    claim is not an established one.
    """
    if not caregiver.discharged_other_than_dishonorably:
        return False
    if caregiver.discharge_date is None:
        return False
    return months_between(caregiver.discharge_date, leave_start) <= VETERAN_LOOKBACK_MONTHS


def servicemember_is_covered(caregiver: MilitaryCaregiver, *, leave_start: date) -> bool:
    """825.122(a): current member in one of three conditions, or a covered veteran."""
    current = (
        ServicememberStatus.CURRENT_MEMBER_IN_TREATMENT,
        ServicememberStatus.OUTPATIENT_STATUS,
        ServicememberStatus.TEMPORARY_DISABILITY_RETIRED_LIST,
    )
    if caregiver.servicemember_status in current:
        return True
    if caregiver.servicemember_status is ServicememberStatus.COVERED_VETERAN:
        return veteran_is_covered(caregiver, leave_start=leave_start)
    return False


def outcome_for(satisfied: bool) -> RuleOutcome:
    return RuleOutcome.SATISFIED if satisfied else RuleOutcome.NOT_SATISFIED


def evaluate_employer(employer: Employer) -> RuleEvaluation:
    covered = employer_is_covered(employer)
    reached = max(
        employer.workweeks_with_50_employees_current_year,
        employer.workweeks_with_50_employees_preceding_year,
    )
    return RuleEvaluation(
        rule_id=RULE_EMPLOYER,
        citation="29 CFR 825.104(a)",
        outcome=outcome_for(covered),
        observed=employer.employer_type.value if covered else reached,
        required=COVERED_EMPLOYER_WORKWEEKS,
    )


def evaluate_tenure(employee: Employee, *, as_of: date) -> RuleEvaluation:
    months = months_of_service(employee, as_of=as_of)
    return RuleEvaluation(
        rule_id=RULE_TENURE,
        citation="29 CFR 825.110(a)(1)",
        outcome=outcome_for(months >= TENURE_MONTHS),
        observed=months,
        required=TENURE_MONTHS,
    )


def evaluate_hours(employee: Employee) -> RuleEvaluation:
    """The ordinary 1,250-hour rule, or its explicit inapplicability to crew.

    NOT_APPLICABLE RATHER THAN OMITTED. A reader of the determination must be
    able to see that the rule was considered and set aside, which is different
    from a rule that was never mentioned.
    """
    if employee.employee_class is EmployeeClass.AIRLINE_FLIGHT_CREW:
        return RuleEvaluation(
            rule_id=RULE_HOURS,
            citation="29 CFR 825.801(a)",
            outcome=RuleOutcome.NOT_APPLICABLE,
            observed="airline_flight_crew",
            required=HOURS_OF_SERVICE,
        )
    hours = hours_of_service(employee)
    return RuleEvaluation(
        rule_id=RULE_HOURS,
        citation="29 CFR 825.110(a)(2)",
        outcome=outcome_for(hours >= HOURS_OF_SERVICE),
        observed=hours,
        required=HOURS_OF_SERVICE,
    )


def evaluate_flight_crew_hours(service: FlightCrewService) -> RuleEvaluation:
    return RuleEvaluation(
        rule_id=RULE_CREW_HOURS,
        citation="29 CFR 825.801(b)",
        outcome=outcome_for(flight_crew_hours_satisfied(service)),
        observed=service.duty_or_paid_hours,
        required=max(FLIGHT_CREW_HOURS_FLOOR, required_flight_crew_guarantee_hours(service)),
    )


def evaluate_worksite(employee: Employee) -> RuleEvaluation:
    return RuleEvaluation(
        rule_id=RULE_WORKSITE,
        citation="29 CFR 825.110(a)(3)",
        outcome=outcome_for(employee.worksite_headcount_within_75_miles >= WORKSITE_HEADCOUNT),
        observed=employee.worksite_headcount_within_75_miles,
        required=WORKSITE_HEADCOUNT,
    )


def evaluate_caregiver(caregiver: MilitaryCaregiver, *, leave_start: date) -> list[RuleEvaluation]:
    return [
        RuleEvaluation(
            rule_id=RULE_RELATIONSHIP,
            citation="29 CFR 825.122(e)",
            outcome=outcome_for(relationship_qualifies(caregiver)),
            observed=caregiver.relationship.value,
            required="spouse, parent, son or daughter, or next of kin",
        ),
        RuleEvaluation(
            rule_id=RULE_SERVICEMEMBER,
            citation="29 CFR 825.122(a)",
            outcome=outcome_for(servicemember_is_covered(caregiver, leave_start=leave_start)),
            observed=caregiver.servicemember_status.value,
            required="current member in treatment, outpatient, TDRL, or covered veteran",
        ),
    ]


def evaluate_rules(request: DeterminationRequest) -> list[RuleEvaluation]:
    """Every applicable rule, evaluated to completion.

    NO SHORT-CIRCUITING. An implementation returning on the first failure
    produces a denial the employee can cure only one round at a time -- and each
    round trip is a leave request, not a form field.
    """
    rules = [
        evaluate_employer(request.employer),
        evaluate_tenure(request.employee, as_of=request.leave.start_date),
        evaluate_hours(request.employee),
    ]
    if request.employee.flight_crew_service is not None:
        rules.append(evaluate_flight_crew_hours(request.employee.flight_crew_service))
    rules.append(evaluate_worksite(request.employee))

    if request.leave.military_caregiver is not None:
        rules.extend(
            evaluate_caregiver(
                request.leave.military_caregiver, leave_start=request.leave.start_date
            )
        )
    return rules


def derive_verdict(rules: list[RuleEvaluation]) -> EligibilityVerdict:
    """Any unmet condition denies. NOT_APPLICABLE does not deny."""
    unmet = any(rule.outcome is RuleOutcome.NOT_SATISFIED for rule in rules)
    return EligibilityVerdict.INELIGIBLE if unmet else EligibilityVerdict.ELIGIBLE


def entitlement_weeks_for(verdict: EligibilityVerdict, reason: LeaveReason) -> int | None:
    """825.200(a) and 825.127(e).

    NONE RATHER THAN ZERO FOR A DENIAL. An ineligible employee has no statutory
    entitlement at all; reporting 0 would let a consumer treat a denial as an
    exhausted balance, which is a different appeal and a different remedy.
    """
    if verdict is EligibilityVerdict.INELIGIBLE:
        return None
    if reason is LeaveReason.MILITARY_CAREGIVER:
        return CAREGIVER_ENTITLEMENT_WEEKS
    return ORDINARY_ENTITLEMENT_WEEKS


def determine(request: DeterminationRequest) -> Determination:
    """The domain service: facts in, determination out.

    UNDECORATED AND TRANSPORT-FREE, so it is reachable by mutation testing and
    callable from a test without an HTTP client. The route is one line.
    """
    rules = evaluate_rules(request)
    verdict = derive_verdict(rules)
    return Determination(
        verdict=verdict,
        entitlement_weeks=entitlement_weeks_for(verdict, request.leave.reason),
        rules=rules,
    )
