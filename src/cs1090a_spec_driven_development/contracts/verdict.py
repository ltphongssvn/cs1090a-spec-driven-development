# src/cs1090a_spec_driven_development/contracts/verdict.py
# VERDICT AS DATA. The typed document every gate emits.
#
# WHAT THIS REPLACES. Gates used to end in `&& echo GATES_PASS`: a string in a
# scrollback that cannot be queried, diffed, attested or replayed. It DESCRIBED
# a check rather than recording one, and it announced success merely because the
# previous command exited zero -- so a mistyped predicate produced a confident
# pass. This repository has already watched a mutation gate report green across
# zero mutants for precisely that reason.
#
# THE INVERSION THIS MODULE ENFORCES:
#
#   checks  ->  verdict  ->  exit code
#
# Checks carry observations. The verdict is DERIVED from them. The exit code is
# derived from the verdict. A caller cannot assert a passing verdict over a
# failing check, because the derived value overwrites whatever was supplied.
#
# WHY THE LOGIC IS IN PLAIN MODULE-LEVEL FUNCTIONS. mutmut 3 mutates only code
# inside functions, and SKIPS any function carrying a decorator other than
# staticmethod or classmethod. A @model_validator body is therefore invisible to
# mutation testing: the rules deciding every gate in this repository would be
# the one place no mutant could reach. The validators below delegate a single
# line each to the undecorated functions above them, which ARE mutated.
#
# WHY THOSE HELPERS TAKE A PEP 695 TYPE PARAMETER. A validator must return
# `Self`, which in a subclass is NARROWER than the base class -- so a helper
# annotated `-> Check` widens the type and mypy refuses it. `def f[T: Check]`
# makes the helper return exactly what it was handed, which is also the honest
# description of what these functions do. The parameter is scoped to the
# function rather than declared as a module-level TypeVar, so there is no loose
# name outliving the one signature that uses it.
#
# --- ON THE TWO `noqa: S105` SUPPRESSIONS BELOW -------------------------------
#
# Ruff's bandit port flags an assignment whose NAME matches a credential
# wordlist, and `PASS` matches. There is no secret here; the member is domain
# vocabulary. Upstream treats enum-member false positives as a known property of
# the rule and has narrowed the regex before -- a merged fix stopped "passed"
# being read as "password" -- without removing name-based matching itself.
#
# THREE ALTERNATIVES WERE REJECTED, EACH FOR A DIFFERENT REASON:
#
#   RENAMING THE MEMBER corrupts the ubiquitous language to satisfy a heuristic
#   about variable names. The gate says "pass"; so does the type.
#
#   A PER-FILE IGNORE is broader than the problem. It would blind this file to a
#   genuine S105 introduced later, and this is the module every gate depends on.
#
#   ANNOTATING THE MEMBERS would silence the rule, because S105 does not fire on
#   an annotated assignment -- but that gap is an upstream BUG that is accepted
#   and awaiting implementation. Relying on a defect scheduled for repair is the
#   treadmill: the lint would break on a future ruff bump, and no test of ours
#   could anticipate it.
#
# RUF100 IS IN THE SELECTED RULESET, so an unnecessary noqa becomes a lint error
# in its own right. The suppression cannot outlive its justification unnoticed.

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CheckVerdict(StrEnum):
    """What one check concluded.

    INFORMATIONAL IS NOT A HEDGE. A line count or a byte size is context a
    reader needs and no threshold was set for; forcing it to claim pass or fail
    would make a gate turn on a number nobody chose a bound for.
    """

    PASS = "pass"  # noqa: S105
    FAIL = "fail"
    INFORMATIONAL = "informational"


class GateVerdict(StrEnum):
    """What the gate as a whole concluded.

    UNKNOWN IS A THIRD OUTCOME, NOT A SHADE OF FAILURE. "The gate measured
    nothing" and "the gate measured something and it was wrong" have different
    causes and different fixes, and only one of them is repaired by changing the
    code under test. Collapsing them is how a vacuous green survives review.
    """

    PASS = "pass"  # noqa: S105
    FAIL = "fail"
    UNKNOWN = "unknown"


class Check(BaseModel):
    """One observation, with what was seen and what was required.

    OBSERVED AND EXPECTED ARE THE POINT. A check reporting only pass or fail
    sends the reader back to the machine that ran it; carrying both values makes
    the record self-contained, which is what an auditor means by evidence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, description="Stable identifier, cited in reasons.")
    verdict: CheckVerdict
    observed: int | str | None = Field(default=None, description="What was actually seen.")
    expected: int | str | None = Field(default=None, description="What was required, if any.")

    @model_validator(mode="after")
    def _reject_blank_id(self) -> Self:
        return reject_blank_id(self)


def reject_blank_id[CheckT: Check](check: CheckT) -> CheckT:
    """Refuse an id that is whitespace.

    AN UNNAMED CHECK IS AN UNCITABLE ONE. min_length=1 admits "   ", and a
    verdict whose reasons list contains a blank string tells a reader that
    something failed and nothing about what.
    """
    if not check.id.strip():
        raise ValueError("check id must not be blank")
    return check


def deciding_checks(checks: list[Check]) -> list[Check]:
    """The checks that are allowed to decide the gate.

    Informational checks are excluded in ONE place, so a later reader cannot
    find two different answers to which checks count.
    """
    return [check for check in checks if check.verdict is not CheckVerdict.INFORMATIONAL]


def derive_gate_verdict(checks: list[Check]) -> GateVerdict:
    """Compute the gate's conclusion from its checks.

    THE ANTI-VACUITY CLAUSE IS THE FIRST BRANCH. A gate whose checks are all
    informational measured nothing, and measuring nothing is not passing.
    """
    deciding = deciding_checks(checks)
    if not deciding:
        return GateVerdict.UNKNOWN
    if all(check.verdict is CheckVerdict.PASS for check in deciding):
        return GateVerdict.PASS
    return GateVerdict.FAIL


def derive_reasons(checks: list[Check]) -> list[str]:
    """Name every failing check, so the reader need not filter the document."""
    return [check.id for check in checks if check.verdict is CheckVerdict.FAIL]


def reject_duplicate_ids(checks: list[Check]) -> list[Check]:
    """Two checks sharing one name make the reasons list ambiguous.

    Which "hours" failed? A document that cannot answer that is not evidence.
    """
    seen: set[str] = set()
    for check in checks:
        if check.id in seen:
            raise ValueError(f"duplicate check id: {check.id}")
        seen.add(check.id)
    return checks


def exit_code_for(verdict: GateVerdict) -> int:
    """Map a verdict to a process exit code.

    THE MAPPING IS TOTAL AND EXPLICIT rather than a default with two special
    cases, because the default branch is where an unhandled future member would
    silently become success.
    """
    if verdict is GateVerdict.PASS:
        return 0
    if verdict is GateVerdict.FAIL:
        return 1
    return 2


def utc_now() -> datetime:
    """A timezone-aware timestamp.

    A NAIVE TIMESTAMP IS NOT A FACT ABOUT A MOMENT. Evidence compared across a
    laptop and a CI runner in different zones is unorderable without an offset.
    """
    return datetime.now(UTC)


class Verdict(BaseModel):
    """One gate's judgement, as a durable document.

    NOT FROZEN, DELIBERATELY, UNLIKE Check. The after-validator must overwrite
    the supplied verdict and reasons with the derived ones, and a frozen model
    cannot. Immutability here would protect a value that must not be trusted in
    the first place.
    """

    model_config = ConfigDict(extra="forbid")

    spec_version: str = Field(
        default="1.0.0",
        description="Which shape of this document a consumer is reading.",
    )
    gate: str = Field(min_length=1, description="Which gate produced this judgement.")
    subject: str = Field(min_length=1, description="What was judged.")
    run_timestamp: datetime = Field(default_factory=utc_now)
    checks: list[Check] = Field(min_length=1)
    verdict: GateVerdict = Field(
        default=GateVerdict.UNKNOWN,
        description="DERIVED from checks. Any supplied value is discarded.",
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="DERIVED: the id of every failing check.",
    )

    @model_validator(mode="after")
    def _derive(self) -> Self:
        return derive_verdict_fields(self)

    @property
    def exit_code(self) -> int:
        return exit_code_for(self.verdict)


def derive_verdict_fields[VerdictT: Verdict](verdict: VerdictT) -> VerdictT:
    """Overwrite the supplied verdict and reasons with the computed ones.

    ASSIGNMENT, NOT COMPARISON. Raising when a caller supplies a wrong verdict
    would make the correct value knowable only to someone who already had it.
    Overwriting makes the derived answer the only answer, which is what stops
    `echo GATES_PASS` reappearing inside a type.
    """
    reject_duplicate_ids(verdict.checks)
    verdict.verdict = derive_gate_verdict(verdict.checks)
    verdict.reasons = derive_reasons(verdict.checks)
    return verdict
