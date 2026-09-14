# tests/conftest.py
# SHARED TEST BUILDERS AND HELPERS.
#
# WHY THIS EXISTS. tests/test_fmla_boundaries.py first tried
# `from tests.test_fmla_rules import employee`, which failed: tests/ has no
# __init__.py and is therefore not a package.
#
# MAKING IT A PACKAGE WOULD HAVE BEEN THE WRONG FIX. Importing one test module
# from another couples them -- the importing module's collection now depends on
# the imported one's import-time behaviour, its fixtures and its name -- and it
# is how a rename in one file breaks a test in another that never mentioned it.
# conftest.py is pytest's own answer: definitions here reach every test module
# beneath it without any module importing any other.
#
# THE BUILDERS ARE FACTORY FIXTURES rather than plain objects, because each test
# varies ONE fact against a baseline. A shared frozen instance would force every
# test to reconstruct the whole object to change a single field, and the
# reconstruction is where a fixture quietly stops resembling the baseline.

import re
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

# THE DATE EVERY DETERMINATION IS MEASURED AGAINST. 825.110(d) fixes eligibility
# as of the date leave is to start, so a single constant keeps every fixture's
# arithmetic checkable by hand.
LEAVE_START = date(2026, 3, 1)


def exactly(message: str) -> str:
    r"""A regex matching the whole string and nothing around it.

    TWO SEPARATE DEFECTS THIS CLOSES, both found by tooling rather than review:

    UNANCHORED MATCHES ARE SUBSTRING SEARCHES. pytest.raises(match=...) uses
    re.search, so "payload must not be empty" matched mutmut's sentinel-wrapped
    "XXpayload must not be emptyXX" and the mutant survived a suite that
    appeared to assert the message.

    UNESCAPED DOTS ARE WILDCARDS. "mutmut-cicd-stats.json" also matches
    "mutmut-cicd-statsXjson", which ruff's RUF043 flags precisely because an
    assertion that reads as a literal and behaves as a pattern is weaker than it
    looks.

    \A AND \Z RATHER THAN ^ AND $, which also match at line boundaries -- a
    message containing a newline would still satisfy an anchored-with-$ match.
    """
    return rf"\A{re.escape(message)}\Z"


def containing(fragment: str) -> str:
    """A regex matching a literal fragment anywhere in the message.

    FOR MESSAGES WHOSE FULL TEXT IS NOT OURS TO FIX -- pydantic wraps a
    ValueError with its own prefix and suffix, and an exception carrying a
    formatted path varies by machine. The fragment is still ESCAPED, so the only
    looseness is the one being asked for.
    """
    return re.escape(fragment)


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
