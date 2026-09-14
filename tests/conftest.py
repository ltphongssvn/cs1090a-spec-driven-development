# tests/conftest.py
# SHARED TEST BUILDERS, HELPERS, AND PER-PROCESS TEMPORARY ISOLATION.
#
# WHY THIS EXISTS AT ALL. tests/test_fmla_boundaries.py first tried
# `from tests.test_fmla_rules import employee`, which failed: tests/ has no
# __init__.py and is not a package. Making it one would have COUPLED the two
# modules -- the importer's collection would depend on the imported module's
# import-time behaviour, its fixtures and its name. conftest.py is pytest's own
# answer: definitions here reach every test module beneath it without any module
# importing any other.
#
# --- PER-PROCESS TEMPORARY ISOLATION ------------------------------------------
#
# A MUTATION RUN ABORTED MID-FLIGHT WITH:
#
#   FileNotFoundError: .../pytest-of-thanhphongle/pytest-current
#     in cleanup_dead_symlinks -> left_dir.unlink()
#
# NOT A TEST FAILURE AND NOT OUR CODE. pytest derives its base temp directory
# from tempfile.gettempdir() plus a USER-scoped subdirectory, keeps a
# `pytest-current` SYMLINK inside it, and garbage-collects stale numbered
# directories at session end. That structure is shared by every pytest session
# on the machine.
#
# mutmut RUNS FOUR CHILDREN at --max-children 4, each calling pytest.main() in
# process. Four sessions create, relink and clean up the same symlink
# concurrently; one unlinks it between another's existence check and its own
# unlink, and the loser dies.
#
# WHY IT MATTERS THOUGH THE RUN FINISHED. That crash landed after the verdict
# was written. A race has no such manners: the same collision midway leaves a
# PARTIAL report, and a gate reading a partial report publishes a number nobody
# produced -- the exact failure the mutation gate exists to prevent, arriving
# through the back door.
#
# ISOLATION RATHER THAN RETRY. Giving each PROCESS its own base temp directory
# removes the shared resource instead of serialising access to it. Retrying the
# unlink would paper over a race that also governs the numbered directories.
#
# NOT PYTEST_DEBUG_TEMPROOT. It would work, and its name says what it is for.
# Building reliability on a variable documented as a debug hook is the treadmill
# -- it can change without notice and nothing would tell us. --basetemp is the
# supported interface for precisely this.

import os
import re
import tempfile
from collections.abc import Callable
from datetime import date
from pathlib import Path

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
# as of the date leave is to start, so one constant keeps every fixture's
# arithmetic checkable by hand.
LEAVE_START = date(2026, 3, 1)


def session_basetemp(root: Path, pid: int | None = None) -> Path:
    """A base temp directory belonging to one process and no other.

    THE PID DEFAULTS rather than being required, because a caller who must
    remember to pass its own process id is a caller who will one day forget.

    THE NAME AVOIDS pytest-of- AND pytest-current deliberately: reusing either
    would place us back inside the shared structure this is escaping.
    """
    return root / f"pytest-session-{os.getpid() if pid is None else pid}"


def pytest_configure(config: pytest.Config) -> None:
    """Point this session's temporary files at a directory only it uses.

    A HOOK RATHER THAN A FIXTURE, because basetemp is resolved once per session
    before any fixture runs.

    IT DEFERS TO AN EXPLICIT --basetemp. Someone debugging with a chosen
    directory means it, and silently overriding them would be worse than the
    race.
    """
    if config.option.basetemp is None:
        config.option.basetemp = str(session_basetemp(Path(tempfile.gettempdir())))


def exactly(message: str) -> str:
    r"""A regex matching the whole string and nothing around it.

    TWO DEFECTS THIS CLOSES, both found by tooling rather than review:

    UNANCHORED MATCHES ARE SUBSTRING SEARCHES. pytest.raises(match=...) uses
    re.search, so "payload must not be empty" matched mutmut's sentinel-wrapped
    "XXpayload must not be emptyXX" and the mutant survived a suite that
    appeared to assert the message.

    UNESCAPED DOTS ARE WILDCARDS. "mutmut-cicd-stats.json" also matches
    "mutmut-cicd-statsXjson", which ruff's RUF043 flags precisely because an
    assertion reading as a literal and behaving as a pattern is weaker than it
    looks.

    \A AND \Z RATHER THAN ^ AND $, which also match at line boundaries -- a
    message containing a newline would still satisfy an anchored-with-$ match.
    """
    return rf"\A{re.escape(message)}\Z"


def containing(fragment: str) -> str:
    """A regex matching a literal fragment anywhere in the message.

    FOR MESSAGES WHOSE FULL TEXT IS NOT OURS TO FIX -- pydantic wraps a
    ValueError with its own prefix, and an exception carrying a formatted path
    varies by machine. The fragment is still ESCAPED, so the only looseness is
    the one being asked for.
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
