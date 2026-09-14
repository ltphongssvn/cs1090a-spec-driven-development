# tests/conftest.py
# SHARED TEST BUILDERS, AS FIXTURES.
#
# WHY THIS EXISTS. tests/test_fmla_boundaries.py first tried
# `from tests.test_fmla_rules import employee`, which failed: tests/ has no
# __init__.py and is therefore not a package.
#
# MAKING IT A PACKAGE WOULD HAVE BEEN THE WRONG FIX. Importing one test module
# from another couples them -- the importing module's collection now depends on
# the imported one's import-time behaviour, its fixtures, and its name -- and it
# is how a rename in one file breaks a test in another that never mentioned it.
#
# conftest.py IS PYTEST'S OWN ANSWER: definitions here are available to every
# test module beneath it without any module importing any other.
#
# THE BUILDERS ARE FACTORY FIXTURES rather than plain objects, because each test
# varies ONE fact against a baseline. A shared frozen instance would force every
# test to reconstruct the whole object to change a single field, and the
# reconstruction is where a fixture quietly stops resembling the baseline.

from collections.abc import Callable
from datetime import date

import pytest

from cs1090a_spec_driven_development.contracts.fmla import (
    Employee,
    EmployeeClass,
    Employer,
    EmployerType,
    EmploymentPeriod,
    MilitaryCaregiver,
    QualifyingRelationship,
    ServicememberStatus,
)

# THE DATE EVERY DETERMINATION IS MEASURED AGAINST. 825.110(d) fixes
# eligibility as of the date leave is to start, so a single constant keeps every
# fixture's arithmetic checkable by hand.
LEAVE_START = date(2026, 3, 1)


@pytest.fixture
def leave_start() -> date:
    return LEAVE_START


@pytest.fixture
def employee_builder() -> Callable[..., Employee]:
    """An employee who satisfies every condition, before overrides.

    THE BASELINE IS DELIBERATELY ELIGIBLE so each test changes ONE fact and
    attributes the result to that fact. A baseline that already failed would let
    a test pass for the wrong reason.
    """

    def build(**overrides: object) -> Employee:
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

    return build


@pytest.fixture
def employer_builder() -> Callable[..., Employer]:
    def build(**overrides: object) -> Employer:
        defaults: dict[str, object] = {
            "employer_type": EmployerType.PRIVATE,
            "workweeks_with_50_employees_current_year": 22,
            "workweeks_with_50_employees_preceding_year": 0,
        }
        return Employer.model_validate(defaults | overrides)

    return build


@pytest.fixture
def caregiver_builder() -> Callable[..., MilitaryCaregiver]:
    def build(**overrides: object) -> MilitaryCaregiver:
        defaults: dict[str, object] = {
            "relationship": QualifyingRelationship.SPOUSE,
            "servicemember_status": ServicememberStatus.CURRENT_MEMBER_IN_TREATMENT,
            "discharge_date": None,
            "discharged_other_than_dishonorably": None,
        }
        return MilitaryCaregiver.model_validate(defaults | overrides)

    return build
