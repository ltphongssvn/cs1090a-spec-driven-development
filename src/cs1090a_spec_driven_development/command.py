# src/cs1090a_spec_driven_development/command.py
# EVERY EXTERNAL PROCESS, LAUNCHED THROUGH ONE INJECTED SEAM.
#
# --- WHY THIS EXISTS ----------------------------------------------------------
#
# Mutation testing found `check=True`, `timeout=...` and the resolved executable
# removable at two separate subprocess call sites, with nothing objecting. The
# obvious response -- patch subprocess.run and assert the kwargs -- is the
# treadmill twice over.
#
# IT TESTS HOW THE CALL IS WRITTEN, not what it guarantees: an assertion on
# kwargs breaks on any refactor and proves nothing about behaviour.
#
# AND PATCHING A BUILTIN MODULE IS ITSELF THE HAZARD. Patching builtin modules
# affects other libraries INCLUDING THE TEST FRAMEWORK, and pytest runs in the
# same process and uses subprocess for its own purposes. A 2026 static analyzer
# exists solely to forbid calling an impure stdlib entry point -- clock, random
# source, network, SUBPROCESS -- outside a composition root, on the grounds that
# collaborators belong injected.
#
# --- THE REQUEST CARRIES THE POLICY -------------------------------------------
#
# timeout_seconds IS A PositiveInt WITH A DEFAULT, so `timeout=None` is not a
# mutation that survives: it is a document that fails validation. An empty argv
# is refused for the same reason. That is the difference between a defect
# detected and a defect made unwritable.
#
# FAILURE IS INTOLERABLE BY DEFAULT, and that inversion matters. The most
# serious survivor this replaces was `check=True` becoming `check=False` in the
# policy gate: a failing engine would exit non-zero, the caller would read no
# result, and the gate would report NO VIOLATIONS -- a broken tool passing the
# gate. A caller that genuinely wants an exit code as an answer must say so.
#
# --- ONE WRAPPER, MANY CALLERS ------------------------------------------------
#
# git_topology and policy_gate both launch a process. Two implementations of one
# contract drift, and the second is always the one nobody remembers to fix.

import subprocess
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, PositiveInt

DEFAULT_TIMEOUT_SECONDS = 60


class Runner(Protocol):
    """How a process is launched, declared precisely enough to check.

    A CALLBACK PROTOCOL RATHER THAN Callable[..., X]. The ellipsis form accepts
    any argument list, so it verifies nothing about the keywords this module
    passes -- a fake could drift from the real runner and no checker would say
    so. A __call__ member states the names and kinds, and a mismatched
    collaborator is then rejected for exactly that reason.

    KEYWORD-ONLY AFTER argv, because every one of these is a guarantee rather
    than a positional detail, and a caller that reorders them should be told.
    """

    def __call__(
        self,
        argv: list[str],
        *,
        stdin: str | None,
        timeout_seconds: int,
    ) -> "subprocess.CompletedProcess[str]": ...


def system_runner(
    argv: list[str],
    *,
    stdin: str | None,
    timeout_seconds: int,
) -> "subprocess.CompletedProcess[str]":
    """The real runner, and the ONE place the standard library's shape appears.

    subprocess.run CANNOT SATISFY Runner DIRECTLY: its first parameter is
    `args`, it is overloaded, and it carries dozens of keywords nobody here
    passes. Adapting it once is the composition root -- everything else in this
    repository speaks the vocabulary above.

    capture_output AND text ARE FIXED HERE rather than per caller: every caller
    reads paths or JSON, and deciding it four times is three chances to differ.

    check IS FALSE ON PURPOSE. The failure guarantee belongs to run_command, not
    to the collaborator -- see there for why delegating it is not a guarantee.
    """
    return subprocess.run(  # noqa: S603
        argv,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
    )


class CommandRequest(BaseModel):
    """What to run, and under what guarantees.

    FROZEN, because a request is a decision. A caller editing it between
    construction and execution would run something nobody declared.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # A LIST, NEVER A STRING: passing a list bypasses the shell entirely, so no
    # quoting, globbing or word-splitting can occur.
    argv: list[str] = Field(min_length=1)

    # TEXT ON STDIN, for callers that hand a document to a tool rather than a
    # path -- which is how gathered facts reach the policy engine.
    stdin: str | None = None

    # AN EXTERNAL PROCESS CAN HANG FOREVER. Without a bound, a wedged tool turns
    # a gate into a stuck CI job that a human must notice and cancel.
    timeout_seconds: PositiveInt = DEFAULT_TIMEOUT_SECONDS

    # FAIL CLOSED. See the module header: silently tolerating a non-zero exit is
    # how a broken engine comes to report a clean verdict.
    tolerate_failure: bool = False


class CommandResult(BaseModel):
    """What the process did.

    A CONTRACT RATHER THAN CompletedProcess, so callers depend on this
    repository's shape rather than on the standard library's -- and so a result
    can be constructed in a test without inventing a CompletedProcess.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    returncode: int
    stdout: str
    stderr: str


def run_command(request: CommandRequest, runner: Runner | None = None) -> CommandResult:
    """Launch a process through the injected runner.

    THE DEFAULT IS THE REAL ONE, so production takes a path tests also exercise.
    An injected seam whose default nothing covers is the gap that let
    `sys.argv[1:]` survive mutation earlier in this repository.

    capture_output AND text ARE FIXED HERE rather than per caller: every caller
    reads paths or JSON, and deciding it four times is three chances to differ.
    """
    execute = system_runner if runner is None else runner

    completed = execute(
        request.argv,
        stdin=request.stdin,
        timeout_seconds=request.timeout_seconds,
    )

    # NO `or ""` HERE, AND THAT IS DELIBERATE. CPython documents stdout and
    # stderr as None only when output was NOT captured; system_runner always
    # captures, and the Runner protocol promises CompletedProcess[str]. Guarding
    # against None would be defending against a state the contract forbids --
    # code no test can reach without fabricating an illegal value, which is how
    # the speculative branch in shell.walk came to survive eleven mutants.
    result = CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )

    # THE SEAM RAISES; IT DOES NOT ASK THE RUNNER TO. Passing check=True would
    # delegate the guarantee to the collaborator -- subprocess.run honours it,
    # an injected runner need not, and the tests proved that gap immediately by
    # supplying a fake that ignored it. Enforcing it here means "fail closed" is
    # a property of this module rather than of whoever was passed in.
    #
    # check=False IS THEREFORE PASSED DOWN DELIBERATELY: one rule, one
    # mechanism. Two would eventually disagree, and the day they do is the day a
    # broken tool reports a clean verdict.
    if result.returncode != 0 and not request.tolerate_failure:
        raise subprocess.CalledProcessError(
            returncode=result.returncode,
            cmd=request.argv,
            output=result.stdout,
            stderr=result.stderr,
        )

    return result
