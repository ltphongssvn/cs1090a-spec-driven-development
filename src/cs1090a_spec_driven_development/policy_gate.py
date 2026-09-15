# src/cs1090a_spec_driven_development/policy_gate.py
# EVALUATING THIS REPOSITORY AGAINST ITS OWN POLICIES.
#
# THE SPLIT THIS COMPLETES:
#
#   check:policy            are the policies well-formed, idiomatic and tested?
#   check:policy-decisions  does THIS REPOSITORY satisfy them?
#
# A policy suite can be immaculate and enforce nothing. This module is what
# makes the second question answerable: the gathered document goes to a real
# engine, the engine's answer becomes a Verdict, and the exit code follows the
# verdict rather than the other way round.
#
# --- THE 2026 SUBPROCESS CONTRACT, AND WHY EACH ARGUMENT IS THERE -------------
#
#   A LIST, NEVER A STRING. Passing a list bypasses the shell entirely, so no
#   quoting, globbing or word-splitting can occur. A string would reintroduce
#   the shell this project spent several commits removing.
#
#   timeout IS NOT OPTIONAL. An external process can hang forever; without a
#   bound, a wedged engine turns a gate into a stuck CI job that a human must
#   notice and cancel.
#
#   check=True TURNS A NON-ZERO EXIT INTO AN EXCEPTION, which is correct here:
#   `opa eval` exits zero whether or not the policies deny anything, so a
#   non-zero exit means the ENGINE failed rather than the repository.
#
#   AN ABSOLUTE PATH, RESOLVED BY shutil.which. Bandit's B607 flags a partial
#   path because PATH is ambient and can be manipulated -- and resolving it here
#   also turns "opa is not installed" into a sentence rather than an OSError
#   from somewhere inside the standard library.
#
# --- A DENIAL IS NOT AN ERROR -------------------------------------------------
#
# A policy violation is the gate WORKING: it yields a failing Verdict and exit
# 1. An engine that could not run at all -- missing binary, unparseable policy,
# malformed input -- is a different fact and raises, because one is fixed by
# changing the repository and the other by fixing the toolchain, and reporting
# them alike sends the reader to the wrong place.
#
# --- AN EMPTY POLICY DIRECTORY IS REFUSED -------------------------------------
#
# An engine with no policies loaded denies nothing, which is indistinguishable
# from a conforming repository. This project has already watched a gate report
# green over an empty measurement twice -- zero mutants, and zero tests -- and
# the third occurrence is refused at the door.

import json
import subprocess
from pathlib import Path

from cs1090a_spec_driven_development.contracts.verdict import (
    Check,
    CheckVerdict,
    Verdict,
)
from cs1090a_spec_driven_development.executables import resolve
from cs1090a_spec_driven_development.policy import PolicyInput, gather_policy_input

GATE = "repository_policy"
POLICY_DIRECTORY = Path("policies")
DECISION_QUERY = "data.repository.deny"
EVALUATION_TIMEOUT_SECONDS = 60


def require_policies(policies: Path) -> Path:
    """Refuse to evaluate against a directory with no policies in it.

    THE VACUITY REFUSAL. An engine loaded with nothing denies nothing, and a
    gate reporting "no violations" over zero rules is the failure this project
    keeps finding in new tools.
    """
    if not policies.is_dir() or not list(policies.rglob("*.rego")):
        raise FileNotFoundError(
            f"no policies found under {policies}: the gate would pass without evaluating anything"
        )
    return policies


def evaluate_policies(document: PolicyInput, *, policies: Path) -> list[str]:
    """Ask OPA what this document violates, and return the violations sorted.

    SORTED, BECAUSE A REGO SET HAS NO ORDER. Emitting it unsorted makes the
    recorded verdict differ between runs over identical input, which destroys
    the diffability the record exists for.
    """
    require_policies(policies)

    completed = subprocess.run(  # noqa: S603
        [
            resolve("opa"),
            "eval",
            "--data",
            str(policies),
            "--stdin-input",
            "--format",
            "json",
            DECISION_QUERY,
        ],
        input=document.model_dump_json(),
        capture_output=True,
        text=True,
        check=True,
        timeout=EVALUATION_TIMEOUT_SECONDS,
    )

    return sorted(read_decision(completed.stdout))


def read_decision(output: str) -> list[str]:
    """Pull the deny set out of OPA's result envelope.

    AN UNDEFINED RESULT IS AN EMPTY DECISION, NOT AN ERROR. OPA omits the
    `result` key entirely when a query is undefined, and for a partial set rule
    that simply means nothing was denied.
    """
    document = json.loads(output)
    results = document.get("result", [])
    if not results:
        return []
    return list(results[0]["expressions"][0]["value"])


def violation_check(message: str, index: int) -> Check:
    """One check per violation, so the record is queryable rather than a paragraph.

    THE INDEX IS IN THE ID because check ids must be unique within a verdict and
    two violations of the same rule are two separate facts.
    """
    return Check(
        id=f"policy_violation_{index}",
        verdict=CheckVerdict.FAIL,
        observed=message,
        expected="no violation",
    )


def context_checks(document: PolicyInput) -> list[Check]:
    """What was actually examined, so a pass cannot be vacuous.

    ZERO VIOLATIONS OVER ZERO TASKS IS NOT THE SAME FACT as zero violations over
    twenty-four, and a reader must be able to tell them apart without re-running
    the gate.
    """
    return [
        Check(
            id="tasks_evaluated",
            verdict=CheckVerdict.INFORMATIONAL,
            observed=len(document.tasks),
        ),
        Check(
            id="workflow_actions_evaluated",
            verdict=CheckVerdict.INFORMATIONAL,
            observed=len(document.workflow_actions),
        ),
        Check(
            id="required_contexts_evaluated",
            verdict=CheckVerdict.INFORMATIONAL,
            observed=len(document.required_contexts),
        ),
    ]


def conformance_check() -> Check:
    """The passing case still needs a DECIDING check.

    Without one the verdict would be derived from informational checks alone and
    resolve to UNKNOWN, which is right for a gate that measured nothing and
    wrong for one that evaluated the repository and found it clean.
    """
    return Check(
        id="no_policy_violations",
        verdict=CheckVerdict.PASS,
        observed=0,
        expected=0,
    )


def build_verdict(document: PolicyInput, violations: list[str]) -> Verdict:
    """Turn a decision into the document every other gate also emits."""
    decided: list[Check] = [
        violation_check(message, index) for index, message in enumerate(violations)
    ]
    if not decided:
        decided = [conformance_check()]

    return Verdict(
        gate=GATE,
        subject="repository configuration",
        checks=decided + context_checks(document),
    )


def run_policy_gate(root: Path, *, policies: Path = POLICY_DIRECTORY) -> int:
    """Gather, evaluate, record, and report an exit code."""
    from cs1090a_spec_driven_development.__main__ import record, report

    document = gather_policy_input(root)
    verdict = build_verdict(document, evaluate_policies(document, policies=policies))

    return report(verdict, record(verdict, root=root))
