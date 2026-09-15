# src/cs1090a_spec_driven_development/__main__.py
# THE COMMAND-LINE ENTRY POINT FOR GATES AND FOR AUTHORING.
#
# WHY A __main__ RATHER THAN A SCRIPT IN tools/. These commands import the same
# contracts the service uses, so they ship WITH the package and are exercised by
# the same test suite. A loose script beside the repository is code that nothing
# typechecks and nothing mutates -- the condition this project exists to remove.
#
# THE EXIT CODE COMES FROM THE VERDICT, NEVER THE OTHER WAY ROUND. The verdict
# is derived from checks by the contract; this module only translates it for the
# shell. That ordering is what stops a command announcing success because the
# previous process happened to exit zero.
#
#   0  pass
#   1  fail       something was measured and it was wrong
#   2  unknown    nothing was measured, the run did not finish, or the caller
#                 asked for something that does not exist
#
# --- WHY `author` EXISTS ------------------------------------------------------
#
# authoring.py replaced `cat > path << 'EOF'` in principle for several commits
# while being unreachable from a terminal. The gap showed itself the moment it
# mattered: writing .github/workflows/ci.yml failed with "no such file or
# directory", because a redirect creates the FILE and never the DIRECTORY.
#
# THE PAYLOAD ARRIVES ON STDIN, AND THE SHELL IS NOT THE WRITER. A heredoc
# feeding an INTERPRETER is fine; `cat > file` is the thing 2026 tooling blocks.
# Python performs the write, atomically, with parents created -- then reads the
# file BACK and judges it, so a corrupted transport fails the command rather
# than passing because `cat` returned zero.
#
# --- WHY `policy` IS HERE, AND WHY ITS ABSENCE WENT UNNOTICED -----------------
#
# policy_gate.py was written, tested and green while `mise run
# check:policy-decisions` reported "unknown gate: policy" -- the module existed
# and nothing could reach it. The task was the only caller, and the task had
# never been run against a working implementation.
#
# THE LESSON IS THE ONE THIS REPOSITORY KEEPS RELEARNING: a component is not
# done when its tests pass, but when the path production takes has been walked.
# The same gap produced the sys.argv slice that no in-process test could kill.

import os
import sys
from pathlib import Path

from cs1090a_spec_driven_development.authoring import (
    AuthoringRequest,
    author_verbatim,
    observe_written_file,
)
from cs1090a_spec_driven_development.contracts.verdict import Verdict
from cs1090a_spec_driven_development.mutation import (
    ARTIFACT,
    evaluate_mutation_stats,
    load_mutation_stats,
)

VERDICT_DIRECTORY = Path(".artifacts/verdicts")
ROOT_VARIABLE = "CS1090A_GATE_ROOT"
USAGE = (
    "usage: python -m cs1090a_spec_driven_development mutants\n"
    "       python -m cs1090a_spec_driven_development policy\n"
    "       python -m cs1090a_spec_driven_development author <path>  # payload on stdin"
)


def gate_root() -> Path:
    """Where reports are read from and verdicts written to.

    THE WORKING DIRECTORY BY DEFAULT, which is how a developer and CI both
    invoke it from the repository root. The override exists because the
    directory a process must RUN in is not always the directory its artifacts
    belong in -- a mutated package must run where mutmut's config is, while its
    report belongs somewhere disposable.
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

    THROUGH author_verbatim, so a gate's own record is produced atomically by
    the same writer every other file uses, with the same guarantees about
    partial writes.
    """
    destination = verdict_path_for(verdict.gate)
    payload = f"{verdict.model_dump_json(indent=2)}\n".encode()
    author_verbatim(AuthoringRequest(path=destination, payload=payload), root=root)
    return destination


def report(verdict: Verdict, destination: Path) -> int:
    """Print the verdict on stdout, the note on stderr, and return the exit code.

    THE STREAM SPLIT IS A CONTRACT. A consumer pipes stdout into jq; the human
    note must not land in that pipe and corrupt it.
    """
    print(verdict.model_dump_json(indent=2))
    print(f"\nverdict written to {destination}", file=sys.stderr)
    return verdict.exit_code


def run_mutation_gate(root: Path) -> int:
    """Judge the last mutation run, record the verdict, and report an exit code."""
    verdict = evaluate_mutation_stats(load_mutation_stats(root / ARTIFACT))
    return report(verdict, record(verdict, root=root))


def read_payload() -> bytes:
    """The bytes to write, taken raw from stdin.

    .buffer BYPASSES THE TEXT LAYER entirely, so no encoding is applied and no
    newline is translated between the terminal and the file.
    """
    return sys.stdin.buffer.read()


def run_author(path: str, root: Path) -> int:
    """Write a file from stdin, then judge what landed.

    THE REQUEST IS VALIDATED BEFORE ANYTHING IS TOUCHED. An empty payload or a
    traversing path raises here, leaving any existing file intact -- the
    guarantee a redirect cannot make, since it truncates the target before the
    payload arrives.
    """
    request = AuthoringRequest(path=Path(path), payload=read_payload())
    written = author_verbatim(request, root=root)
    verdict = observe_written_file(written, root=root)
    return report(verdict, record(verdict, root=root))


def usage(arguments: list[str]) -> int:
    """Report a caller error.

    EXIT 2, NOT 1. Asking for a command that does not exist is a caller error,
    not a failing check, and the two must not look alike in CI.
    """
    print(f"unknown gate: {' '.join(arguments) or '(none)'}", file=sys.stderr)
    print(USAGE, file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    """Dispatch to a command by name.

    THE POLICY IMPORT IS LOCAL, DELIBERATELY. policy_gate imports this module
    for `record` and `report`; importing it at module scope would close the
    cycle and fail at interpreter start rather than at the one command that
    needs it.
    """
    arguments = sys.argv[1:] if argv is None else argv

    if arguments == ["mutants"]:
        return run_mutation_gate(gate_root())

    if arguments == ["policy"]:
        from cs1090a_spec_driven_development.policy_gate import run_policy_gate

        return run_policy_gate(gate_root())

    if len(arguments) == 2 and arguments[0] == "author":
        return run_author(arguments[1], gate_root())

    return usage(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
