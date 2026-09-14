# tests/test_fmla_userra_break.py
# THE LAST SURVIVOR: USERRA SERVICE ACROSS A SEVEN-YEAR BREAK.
#
# THE MUTANT was `has_userra_service=None` in place of
# `employee.userra_service is not None`. None is falsy, so the mutant differs
# from the original only when an employee BOTH has USERRA service AND has a
# break in service long enough to be discounted.
#
# NO FIXTURE COMBINED THEM. The USERRA tests use a single recent employment
# period, so there is no break to rescue. The break-in-service tests use no
# USERRA service, so the flag is False either way. Each rule was covered; their
# INTERSECTION was not, and the intersection is where the flag does its work.
#
# THE CASE IS NOT HYPOTHETICAL. 825.110(b)(2)(i) exists precisely for the
# reservist whose employment was interrupted by a long deployment: without it,
# an employer could discount every month served before the call-up and deny
# leave on tenure grounds to the person the protection was written for. It is
# also the case least likely to be exercised by a test author, because it
# requires holding two separate provisions in mind at once.
#
# THE GENERAL LESSON: a mutant that survives a suite covering each rule
# individually is usually pointing at an interaction between rules. Coverage of
# the parts is not coverage of the combination.

from collections.abc import Callable
from datetime import date

from cs1090a_spec_driven_development.contracts.fmla import (
    Employee,
    EmploymentPeriod,
    RuleOutcome,
    UserraService,
    countable_periods,
    evaluate_tenure,
    months_of_service,
)


class TestUserraRescuesServiceAcrossALongBreak:
    def test_userra_service_keeps_employment_from_before_a_long_break(
        self, leave_start: date
    ) -> None:
        """825.110(b)(2)(i), STATED DIRECTLY ON countable_periods.

        Without the flag, the 2010-2015 period is discarded as preceding a break
        of more than seven years. With it, the whole record counts.
        """
        early = EmploymentPeriod(start=date(2010, 1, 1), end=date(2015, 1, 1))
        recent = EmploymentPeriod(start=date(2025, 11, 1))

        with_userra = countable_periods(
            [early, recent],
            as_of=leave_start,
            written_rehire_agreement=False,
            has_userra_service=True,
        )
        without_userra = countable_periods(
            [early, recent],
            as_of=leave_start,
            written_rehire_agreement=False,
            has_userra_service=False,
        )

        assert with_userra == [early, recent]
        assert without_userra == [recent]

    def test_a_reservist_with_pre_deployment_service_is_eligible(
        self, employee_builder: Callable[..., Employee], leave_start: date
    ) -> None:
        """THE MUTANT, KILLED THROUGH THE REAL ENTRY POINT.

        Five years served before a long deployment, four months since returning.
        Discount the earlier service and the employee has four months and is
        denied; count it, as the regulation requires, and they have sixty-four.
        """
        subject = employee_builder(
            employment_periods=[
                EmploymentPeriod(start=date(2010, 1, 1), end=date(2015, 1, 1)),
                EmploymentPeriod(start=date(2025, 11, 1)),
            ],
            userra_service=UserraService(months_absent=6, pre_service_weekly_hours=40),
        )

        assert months_of_service(subject, as_of=leave_start) == 70
        assert evaluate_tenure(subject, as_of=leave_start).outcome is RuleOutcome.SATISFIED

    def test_the_same_reservist_without_userra_service_is_denied(
        self, employee_builder: Callable[..., Employee], leave_start: date
    ) -> None:
        """THE CONTROL. Identical employment history, no protected service.

        Without this pair the previous test could pass for the wrong reason --
        it would not distinguish "USERRA rescued the early period" from "the
        early period was never discarded".
        """
        subject = employee_builder(
            employment_periods=[
                EmploymentPeriod(start=date(2010, 1, 1), end=date(2015, 1, 1)),
                EmploymentPeriod(start=date(2025, 11, 1)),
            ],
            userra_service=None,
        )

        assert months_of_service(subject, as_of=leave_start) == 4
        assert evaluate_tenure(subject, as_of=leave_start).outcome is RuleOutcome.NOT_SATISFIED

    def test_zero_months_of_userra_absence_still_counts_as_protected_service(
        self, employee_builder: Callable[..., Employee], leave_start: date
    ) -> None:
        """THE FLAG IS PRESENCE, NOT DURATION.

        A record with months_absent=0 is still USERRA service -- a call-up that
        ended the same month, or a correction. Testing presence with a truthiness
        check on the duration would discard the early period here, and this is
        the case that distinguishes `is not None` from a truthy test.
        """
        subject = employee_builder(
            employment_periods=[
                EmploymentPeriod(start=date(2010, 1, 1), end=date(2015, 1, 1)),
                EmploymentPeriod(start=date(2025, 11, 1)),
            ],
            userra_service=UserraService(months_absent=0, pre_service_weekly_hours=40),
        )

        assert evaluate_tenure(subject, as_of=leave_start).outcome is RuleOutcome.SATISFIED

    def test_a_written_rehire_agreement_and_userra_service_together_are_harmless(
        self, employee_builder: Callable[..., Employee], leave_start: date
    ) -> None:
        """BOTH EXCEPTIONS AT ONCE. 825.110(b)(2)(i) and (ii) are alternatives,
        not a sequence; holding both must not double-count or discard anything.
        """
        subject = employee_builder(
            employment_periods=[
                EmploymentPeriod(start=date(2010, 1, 1), end=date(2015, 1, 1)),
                EmploymentPeriod(start=date(2025, 11, 1)),
            ],
            written_rehire_agreement=True,
            userra_service=UserraService(months_absent=6, pre_service_weekly_hours=40),
        )

        assert months_of_service(subject, as_of=leave_start) == 70
