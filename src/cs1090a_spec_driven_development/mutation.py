# src/cs1090a_spec_driven_development/mutation.py
# THE MUTATION GATE. Zero survivors, enforced rather than remembered.
#
# WHY THIS MODULE EXISTS. Zero survivors was reached by hand: run mutmut, read
# the number, be satisfied. A standard nobody enforces lasts until the first
# inconvenient afternoon, and the number is reported by a tool whose output
# nothing validates.
#
# --- THE VACUITY TRAP, IN mutmut's OWN ARTIFACT -------------------------------
#
#   {"killed": 0, "survived": 0, "total": 0, "no_tests": 0, ...}
#
# That document satisfies "survived == 0" perfectly and describes a run that
# measured NOTHING. This repository has already lived it: before the domain
# moved out of decorated functions, mutmut generated zero mutants and every
# naive reading of the result said green. The anti-vacuity clause below is the
# whole reason this gate is worth having.
#
# --- WHY FIVE OUTCOMES ARE NOT PASSES -----------------------------------------
#
#   survived   a test should have failed and did not. The headline failure.
#   no_tests   the mutant was generated and NOTHING RAN AGAINST IT. Not a
#              survivor -- nothing tried to kill it -- and not acceptable
#              either, because coverage can rot while the survivor count sits
#              at zero.
#   suspicious the suite behaved oddly. The mutant's fate is unknown.
#   timeout    the mutant ran too long, usually an infinite loop. A timeout is
#              NOT a kill: the suite never reported on it, and the loop is a
#              defect worth describing rather than absorbing.
#   segfault   the interpreter died. Nothing was measured.
#
# skipped IS CONTEXT, NOT A CONDITION. Nobody configured a bound for it here, so
# it is reported and decides nothing -- the same rule every other gate in this
# repository follows.
#
# check_was_interrupted_by_user YIELDS UNKNOWN, NOT FAIL. Someone pressed
# Ctrl-C. The run is incomplete, which is neither a pass nor evidence of a
# defect, and UNKNOWN is precisely the outcome that distinction exists for.
#
# --- WHY THE ARTIFACT IS PARSED THROUGH A MODEL -------------------------------
#
# It is untyped JSON written by another tool. Reading it with .get() would
# silently tolerate the day a field is renamed or dropped -- returning None,
# comparing falsy, and passing the gate. extra="forbid" turns an upstream
# addition into a visible contract change instead of a silent one.
#
# THE LOGIC IS IN PLAIN UNDECORATED FUNCTIONS, because mutmut skips decorated
# ones and the gate enforcing mutation coverage is the last place in this
# repository that can afford to be unmeasured by it.

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from cs1090a_spec_driven_development.contracts.verdict import (
    Check,
    CheckVerdict,
    Verdict,
)

GATE = "mutation_zero_survivors"
ARTIFACT = Path("mutants/mutmut-cicd-stats.json")


class MutationStats(BaseModel):
    """mutmut's CI/CD export, as a contract.

    THE FIELD NAMES ARE mutmut's, taken from a real run rather than guessed.
    Every count is ge=0 because a negative count means the document is corrupt,
    which is a different problem from a failing gate and must not be reported as
    one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    killed: int = Field(ge=0)
    survived: int = Field(ge=0)
    total: int = Field(ge=0)
    no_tests: int = Field(ge=0)
    skipped: int = Field(ge=0)
    suspicious: int = Field(ge=0)
    timeout: int = Field(ge=0)
    check_was_interrupted_by_user: int = Field(ge=0)
    segfault: int = Field(ge=0)


def load_mutation_stats(artifact: Path = ARTIFACT) -> MutationStats:
    """Read and validate the artifact, refusing to proceed without it.

    A MISSING REPORT IS THE MOST DANGEROUS FAILURE MODE THERE IS. A gate that
    treats absence as success passes on every machine where mutmut never ran --
    which is every machine where somebody forgot. It raises instead, and the
    message names the path so the reader knows what was looked for and where.
    """
    if not artifact.is_file():
        raise FileNotFoundError(f"no mutation report at {artifact}: run `mise run mutants` first")
    try:
        document = json.loads(artifact.read_text())
    except json.JSONDecodeError as error:
        raise ValueError(f"{artifact} is not valid JSON: {error}") from error
    return MutationStats.model_validate(document)


def indeterminate_count(stats: MutationStats) -> int:
    """Mutants whose fate the run could not establish.

    SUMMED IN ONE PLACE, so a reader cannot find two different answers to what
    counts as indeterminate.
    """
    return stats.suspicious + stats.timeout + stats.segfault


def measured_count(stats: MutationStats) -> int:
    """Mutants that something actually ran against."""
    return stats.total - stats.no_tests


def survivors_check(stats: MutationStats) -> Check:
    return Check(
        id="zero_survivors",
        verdict=CheckVerdict.PASS if stats.survived == 0 else CheckVerdict.FAIL,
        observed=stats.survived,
        expected=0,
    )


def measured_check(stats: MutationStats) -> Check:
    """Every generated mutant must have been executed against the suite."""
    return Check(
        id="every_mutant_measured",
        verdict=CheckVerdict.PASS if stats.no_tests == 0 else CheckVerdict.FAIL,
        observed=stats.no_tests,
        expected=0,
    )


def indeterminate_check(stats: MutationStats) -> Check:
    return Check(
        id="no_indeterminate_outcomes",
        verdict=CheckVerdict.PASS if indeterminate_count(stats) == 0 else CheckVerdict.FAIL,
        observed=indeterminate_count(stats),
        expected=0,
    )


def context_checks(stats: MutationStats) -> list[Check]:
    """Numbers a reader needs and no threshold was set for."""
    return [
        Check(id="mutants_killed", verdict=CheckVerdict.INFORMATIONAL, observed=stats.killed),
        Check(id="mutants_total", verdict=CheckVerdict.INFORMATIONAL, observed=stats.total),
        Check(id="skipped", verdict=CheckVerdict.INFORMATIONAL, observed=stats.skipped),
    ]


def is_inconclusive(stats: MutationStats) -> bool:
    """Whether the run judged nothing, or did not finish.

    TWO DISTINCT WAYS TO MEASURE NOTHING, deliberately collapsed into one
    predicate because they demand the same response: report UNKNOWN, and do not
    let the gate claim anything about code it did not examine.
    """
    if stats.check_was_interrupted_by_user > 0:
        return True
    return measured_count(stats) <= 0


def evaluate_mutation_stats(stats: MutationStats) -> Verdict:
    """Judge a mutation run.

    AN INCONCLUSIVE RUN EMITS ONLY INFORMATIONAL CHECKS, so the contract's own
    derivation returns UNKNOWN. The third outcome is not special-cased here; it
    falls out of the rule that a gate with nothing to decide has decided
    nothing.
    """
    if is_inconclusive(stats):
        return Verdict(gate=GATE, subject=ARTIFACT.as_posix(), checks=context_checks(stats))

    checks = [
        survivors_check(stats),
        measured_check(stats),
        indeterminate_check(stats),
        *context_checks(stats),
    ]
    return Verdict(gate=GATE, subject=ARTIFACT.as_posix(), checks=checks)
