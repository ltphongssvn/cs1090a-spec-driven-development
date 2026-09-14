# src/cs1090a_spec_driven_development/__main__.py
# THE COMMAND-LINE ENTRY POINT FOR GATES.
#
# WHY A __main__ RATHER THAN A SCRIPT IN tools/. The gates import the same
# contracts the service uses, so they ship WITH the package and are exercised by
# the same test suite. A loose script beside the repository is code that nothing
# typechecks and nothing mutates -- the condition this project exists to remove.
#
# THE EXIT CODE COMES FROM THE VERDICT, NEVER THE OTHER WAY ROUND. The verdict
# is derived from checks by the contract; this module only translates it for the
# shell. That ordering is what stops a gate announcing success because the last
# command happened to exit zero.
#
#   0  pass
#   1  fail       something was measured and it was wrong
#   2  unknown    nothing was measured, or the run did not finish, or the
#                 caller asked for a gate that does not exist
#
# THE VERDICT IS BOTH PRINTED AND WRITTEN. Printed on STDOUT so it can be piped
# into jq; the human note goes to STDERR so it cannot corrupt that pipe. Written
# to .artifacts/verdicts/ so it is queryable, diffable and attestable
# afterwards, because a verdict living only in a scrollback is the ephemeral
# console output this project replaced.
#
# --- WHY THE ROOT IS OVERRIDABLE ----------------------------------------------
#
# CS1090A_GATE_ROOT was added because a test needed it, and it was worth keeping
# for a reason the test only revealed indirectly: THE DIRECTORY A GATE RUNS IN
# AND THE DIRECTORY ITS REPORT LIVES IN ARE DIFFERENT CONCERNS.
#
# The subprocess test had to run with the repository as its working directory --
# the mutated package imports mutmut's trampoline, which loads mutmut's config
# from the CURRENT DIRECTORY and aborts the entire mutation run if it is
# elsewhere -- while pointing the report somewhere disposable. Conflating the
# two made the test either vacuous or fatal.
#
# THE SAME SPLIT APPEARS IN CI: a job that collects artifacts into a staging
# directory, or a monorepo runner invoked from the top while the report sits in
# a package subdirectory. Path.cwd() remains the default, so nothing changes for
# the ordinary case.

import os
import sys
from pathlib import Path

from cs1090a_spec_driven_development.authoring import AuthoringRequest, author_verbatim
from cs1090a_spec_driven_development.contracts.verdict import Verdict
from cs1090a_spec_driven_development.mutation import (
    ARTIFACT,
    evaluate_mutation_stats,
    load_mutation_stats,
)

VERDICT_DIRECTORY = Path(".artifacts/verdicts")
ROOT_VARIABLE = "CS1090A_GATE_ROOT"


def gate_root() -> Path:
    """Where reports are read from and verdicts written to.

    THE WORKING DIRECTORY BY DEFAULT, which is how a developer and CI both
    invoke it from the repository root. The override exists because the
    directory a process must RUN in is not always the directory its artifacts
    belong in.
    """
    override = os.environ.get(ROOT_VARIABLE)
    return Path(override) if override else Path.cwd()


def verdict_path_for(gate: str) -> Path:
    """One file per gate, named for it, so a later run replaces its predecessor.

    A TIMESTAMPED FILENAME WOULD ACCUMULATE, and the question anyone asks is
    "what does this gate say NOW". History belongs in CI artifacts, not in a
    directory that grows without bound on a laptop.
    """
    return VERDICT_DIRECTORY / f"{gate}.json"


def record(verdict: Verdict, *, root: Path) -> Path:
    """Write the verdict as data, and return where it went.

    THROUGH author_verbatim, so the gate's own record is produced atomically by
    the same writer every other file in this repository uses -- and is subject
    to the same guarantees about partial writes.
    """
    destination = verdict_path_for(verdict.gate)
    payload = f"{verdict.model_dump_json(indent=2)}\n".encode()
    author_verbatim(AuthoringRequest(path=destination, payload=payload), root=root)
    return destination


def run_mutation_gate(root: Path) -> int:
    """Judge the last mutation run, record the verdict, and report an exit code."""
    verdict = evaluate_mutation_stats(load_mutation_stats(root / ARTIFACT))
    destination = record(verdict, root=root)

    print(verdict.model_dump_json(indent=2))
    print(f"\nverdict written to {destination}", file=sys.stderr)
    return verdict.exit_code


def main(argv: list[str] | None = None) -> int:
    """Dispatch to a gate by name.

    AN UNKNOWN GATE EXITS 2, NOT 1. Asking for a gate that does not exist is a
    caller error, not a failing check, and the two must not look alike in CI.
    """
    arguments = sys.argv[1:] if argv is None else argv
    if arguments == ["mutants"]:
        return run_mutation_gate(gate_root())

    print(f"unknown gate: {' '.join(arguments) or '(none)'}", file=sys.stderr)
    print("usage: python -m cs1090a_spec_driven_development mutants", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
