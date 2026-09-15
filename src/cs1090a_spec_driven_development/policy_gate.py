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

from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from cs1090a_spec_driven_development.command import CommandRequest, run_command
from cs1090a_spec_driven_development.contracts.decision import (
    DecisionEnvelope,
    denials_of,
)
from cs1090a_spec_driven_development.contracts.verdict import (
    Check,
    CheckVerdict,
    Verdict,
)
from cs1090a_spec_driven_development.executables import resolve
from cs1090a_spec_driven_development.policy import PolicyInput, gather_policy_input

GATE = "repository_policy"
POLICY_PACKAGE = "cs1090a_spec_driven_development.policies"
DECISION_QUERY = "data.repository.deny"
EVALUATION_TIMEOUT_SECONDS = 60
REGO_SUFFIX = ".rego"


def default_policies() -> Traversable:
    """Where this repository's policies live, found through the import system.

    NOT A PATH RESOLVED AGAINST A WORKING DIRECTORY, which is what three earlier
    attempts amounted to. Path(__file__) arithmetic resolves to the main clone
    when run from a worktree; pytest's rootpath follows the configfile, so
    mutmut's scratch copy answers with itself; and git rev-parse is right only
    while a working tree exists, which stops being true the moment this package
    is installed as a wheel.

    importlib.resources ASKS THE IMPORT SYSTEM, so the answer holds wherever the
    package can be imported -- including from a zip, where no file path would
    work at all. PyPA recommends exactly this for run-time data, because data
    installed outside a package has no reliable retrieval facility.
    """
    return resources.files(POLICY_PACKAGE)


def rego_files(policies: Traversable) -> list[Traversable]:
    """Every policy file beneath a container, in a deterministic order.

    A Traversable HAS NO rglob. It offers iterdir and nothing more, which is the
    price of working inside a zip -- and one level down is all this layout
    needs, since each package of policies is its own directory.

    SORTED, AND NOT FOR TIDINESS. Filesystem enumeration order is not a
    processing order: APFS on macOS reports insertion order and ext4 on Linux
    reports inode order, so an unsorted answer differs between a laptop and the
    runner. This repository has already been bitten by exactly that divergence
    once, when ruff classified imports differently on the two machines, and the
    established remedy is to sort at the source rather than to stop depending on
    the order downstream.
    """
    found: list[Traversable] = []
    for entry in policies.iterdir():
        if entry.is_dir():
            found.extend(child for child in entry.iterdir() if child.name.endswith(REGO_SUFFIX))
        elif entry.name.endswith(REGO_SUFFIX):
            found.append(entry)
    return sorted(found, key=lambda entry: entry.name)


def require_policies(policies: Traversable) -> Traversable:
    """Refuse to evaluate against a container with no policies in it.

    THE VACUITY REFUSAL. An engine loaded with nothing denies nothing, and a
    gate reporting "no violations" over zero rules is the failure this project
    keeps meeting in new tools.
    """
    if not policies.is_dir() or not rego_files(policies):
        raise FileNotFoundError(
            f"no policies found under {policies}: the gate would pass without evaluating anything"
        )
    return policies


def evaluate_policies(document: PolicyInput) -> list[str]:
    """Ask OPA what this document violates, and return the violations sorted.

    as_file MATERIALISES THE POLICIES FOR THE CALL. `opa eval --data` takes a
    filesystem path, and a Traversable need not be one; as_file provides a real
    path for the duration and removes it afterwards, which is how package data
    is handed to an external process.

    SORTED, BECAUSE A REGO SET HAS NO ORDER. Emitting it unsorted makes the
    recorded verdict differ between runs over identical input, destroying the
    diffability the record exists for.
    """
    located = require_policies(default_policies())

    with resources.as_file(located) as directory:
        result = run_command(
            CommandRequest(
                argv=[
                    resolve("opa"),
                    "eval",
                    "--data",
                    str(directory),
                    "--stdin-input",
                    "--format",
                    "json",
                    DECISION_QUERY,
                ],
                stdin=document.model_dump_json(),
                timeout_seconds=EVALUATION_TIMEOUT_SECONDS,
                # FAIL CLOSED, DELIBERATELY. `opa eval` exits zero whether or
                # not the policies deny anything, so a non-zero exit means the
                # ENGINE failed. Tolerating it would let a broken engine report
                # no violations -- a gate passing because it could not run.
            )
        )

    return sorted(read_decision(result.stdout))


def read_decision(output: str) -> list[str]:
    """Pull the deny set out of OPA's result envelope.

    PARSED THROUGH A CONTRACT rather than navigated by hand. The previous body
    used one guarded `.get("result", [])` followed by three unguarded subscripts
    -- two mutants lived in the guard, and the subscripts had no guard at all,
    so one function disagreed with itself about how far to trust the document.

    AN UNDEFINED RESULT IS AN EMPTY DECISION, NOT AN ERROR. opa omits the
    `result` key entirely for an undefined query -- measured, not assumed -- and
    for a partial set rule that means nothing was denied. The contract expresses
    that as a default rather than as a lookup.

    model_validate_json, NOT model_validate(json.loads(...)): pydantic validates
    the JSON internally instead of building a dict first and checking it after.
    """
    return denials_of(DecisionEnvelope.model_validate_json(output))


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


def run_policy_gate(root: Path) -> int:
    """Gather, evaluate, record, and report an exit code.

    NO policies PARAMETER, AND ITS REMOVAL IS THE FIX RATHER THAN A TIDY-UP.
    Mutation testing replaced the forwarded argument with None and nothing
    objected -- because None resolved, through the import system, to exactly
    what every caller was passing. A parameter always given the same value is
    speculative generality, and eliminating it is the documented remedy.

    IT ALSO CLOSES A REAL HOLE: while the parameter existed, a caller could
    point this gate at policies nobody intended it to enforce.
    """
    from cs1090a_spec_driven_development.__main__ import record, report

    document = gather_policy_input(root)
    verdict = build_verdict(document, evaluate_policies(document))

    return report(verdict, record(verdict, root=root))
