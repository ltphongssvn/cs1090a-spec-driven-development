# tests/test_command_seam.py
# EVERY EXTERNAL PROCESS, LAUNCHED THROUGH ONE INJECTED SEAM.
#
# --- WHY THIS EXISTS ----------------------------------------------------------
#
# Mutation testing found `check=True`, `timeout=...` and the resolved executable
# all removable from two separate subprocess call sites, with nothing objecting.
# The obvious response -- patch subprocess.run and assert the kwargs -- is the
# treadmill twice over.
#
# IT TESTS HOW THE CALL IS WRITTEN, not what it guarantees. An assertion on
# kwargs breaks on any refactor and proves nothing about behaviour.
#
# AND PATCHING A BUILTIN MODULE IS ITSELF THE HAZARD. The 2026 guidance is
# blunt: patching builtin modules affects other libraries INCLUDING THE TEST
# FRAMEWORK -- and pytest runs in the same process, using subprocess for its own
# purposes. A gomatic analyzer now exists solely to forbid calling an impure
# stdlib entry point (clock, random, network, SUBPROCESS) outside a composition
# root, on the grounds that collaborators should be injected.
#
# --- THE SEAM CARRIES THE POLICY ----------------------------------------------
#
# CommandRequest is a frozen model with a POSITIVE timeout and a required argv.
# `timeout=None` is then not a mutation that survives -- it is a document that
# does not validate. That is the difference between a defect detected and a
# defect made unwritable, which is the standard this branch has been applying.
#
# ONE WRAPPER, MANY CALLERS. git_topology and policy_gate both launch a process;
# two implementations of one contract drift, and the second is always the one
# nobody remembers to fix.

import subprocess

import pytest
from pydantic import ValidationError

from cs1090a_spec_driven_development.command import (
    DEFAULT_TIMEOUT_SECONDS,
    CommandRequest,
    CommandResult,
    run_command,
)
from cs1090a_spec_driven_development.executables import resolve


class Echoing:
    """A fake runner, injected rather than patched.

    NOTHING GLOBAL IS TOUCHED, so pytest's own use of subprocess is unaffected
    and this test cannot be the reason another one fails. That is the argument
    for a seam: patching a builtin module reaches into every library in the
    process, the test framework included.

    IT CONFORMS TO THE Runner PROTOCOL STRUCTURALLY, and that conformance is
    CHECKED. A callback protocol declares the parameter names and kinds, so a
    double that drifts from the real runner is a type error rather than a
    surprise at run time -- which is why the seam's type is a protocol and not
    Callable[..., X].

    A CLASS RATHER THAN A CLOSURE WITH ATTRIBUTES. Recording what it was handed
    is part of what this object IS, so it is declared rather than bolted on.
    """

    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr
        self.seen_argv: list[str] = []
        self.seen_stdin: str | None = None
        self.seen_timeout: int | None = None

    def __call__(
        self,
        argv: list[str],
        *,
        stdin: str | None,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        self.seen_argv = list(argv)
        self.seen_stdin = stdin
        self.seen_timeout = timeout_seconds
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)


def echoing(stdout: str = "", returncode: int = 0, stderr: str = "") -> Echoing:
    return Echoing(stdout=stdout, returncode=returncode, stderr=stderr)


class TestTheRequestContract:
    def test_a_timeout_is_always_present(self) -> None:
        """THE MUTANT MADE UNWRITABLE. `timeout=None` is not a surviving
        mutation here; it is a document that fails validation.
        """
        assert CommandRequest(argv=["git"]).timeout_seconds == DEFAULT_TIMEOUT_SECONDS

    def test_a_missing_timeout_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            CommandRequest(argv=["git"], timeout_seconds=None)  # type: ignore[arg-type]

    def test_a_zero_timeout_is_refused(self) -> None:
        """A ZERO TIMEOUT IS NOT A BOUND, it is a guaranteed failure dressed as
        configuration."""
        with pytest.raises(ValidationError):
            CommandRequest(argv=["git"], timeout_seconds=0)

    def test_a_negative_timeout_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            CommandRequest(argv=["git"], timeout_seconds=-1)

    def test_an_empty_argv_is_refused(self) -> None:
        """A COMMAND WITH NO PROGRAM cannot be run, and accepting it defers the
        failure into the standard library."""
        with pytest.raises(ValidationError):
            CommandRequest(argv=[])

    def test_the_request_is_frozen(self) -> None:
        request = CommandRequest(argv=["git"])

        with pytest.raises(ValidationError):
            request.argv = ["rm"]  # type: ignore[misc]

    def test_failure_is_intolerable_by_default(self) -> None:
        """FAIL CLOSED. A caller that wants to read a non-zero exit must say so;
        the default must not silently swallow a broken tool.
        """
        assert CommandRequest(argv=["git"]).tolerate_failure is False


class TestRunning:
    def test_the_argument_vector_reaches_the_runner(self) -> None:
        runner = echoing()

        run_command(CommandRequest(argv=["git", "status"]), runner=runner)

        assert runner.seen_argv == ["git", "status"]

    def test_the_timeout_reaches_the_runner(self) -> None:
        """ASSERTED ONCE, HERE, rather than at every call site."""
        runner = echoing()

        run_command(CommandRequest(argv=["git"], timeout_seconds=7), runner=runner)

        assert runner.seen_timeout == 7

    def test_output_is_captured_as_text(self) -> None:
        """TEXT, NOT BYTES. Every caller reads paths and JSON, and decoding at
        each site would be the same decision made four times."""
        result = run_command(CommandRequest(argv=["git"]), runner=echoing(stdout="ok\n"))

        assert result.stdout == "ok\n"

    def test_stdin_is_delivered_when_supplied(self) -> None:
        runner = echoing()

        run_command(CommandRequest(argv=["opa"], stdin='{"a": 1}'), runner=runner)

        assert runner.seen_stdin == '{"a": 1}'

    def test_the_result_is_a_contract(self) -> None:
        result = run_command(CommandRequest(argv=["git"]), runner=echoing(stdout="x"))

        assert isinstance(result, CommandResult)
        assert result.returncode == 0


class TestFailure:
    def test_a_failing_command_raises_by_default(self) -> None:
        """THE MOST SERIOUS SURVIVOR THIS REPLACES.

        With failure tolerated everywhere, a broken engine exits non-zero, the
        caller reads no result, and the gate reports NO VIOLATIONS -- a broken
        tool passing the gate. Failing closed is the whole point.
        """
        with pytest.raises(subprocess.CalledProcessError):
            run_command(CommandRequest(argv=["opa"]), runner=echoing(returncode=1))

    def test_a_failing_command_is_returned_when_tolerated(self) -> None:
        """SOME CALLERS NEED THE EXIT CODE AS AN ANSWER. "Not a git repository"
        is a fact about where the caller stands, not a crash.
        """
        result = run_command(
            CommandRequest(argv=["git"], tolerate_failure=True),
            runner=echoing(returncode=128, stderr="not a repository"),
        )

        assert result.returncode == 128
        assert "not a repository" in result.stderr

    def test_the_raised_error_names_the_command(self) -> None:
        with pytest.raises(subprocess.CalledProcessError) as raised:
            run_command(CommandRequest(argv=["opa", "eval"]), runner=echoing(returncode=2))

        assert raised.value.cmd == ["opa", "eval"]


class TestTheDefaultRunner:
    def test_the_default_runner_launches_a_real_process(self) -> None:
        """THE SEAM MUST STILL WORK WITHOUT INJECTION, or production takes a
        path no test ever exercises -- the gap that let sys.argv[1:] survive
        earlier in this repository.
        """
        result = run_command(CommandRequest(argv=[resolve("git"), "--version"]))

        assert result.returncode == 0
        assert result.stdout.startswith("git version")


class TestWhatAFailureCarries:
    """A CalledProcessError is the only account of why a tool failed.

    MUTATION TESTING FOUND ITS PAYLOAD BLANKABLE: returncode, output and stderr
    could each become None with every existing assertion still passing. An
    exception carrying no diagnostics fires exactly when the reader has nothing
    else to go on.
    """

    def test_the_error_carries_the_exit_code(self) -> None:
        with pytest.raises(subprocess.CalledProcessError) as raised:
            run_command(CommandRequest(argv=["opa"]), runner=echoing(returncode=2))

        assert raised.value.returncode == 2

    def test_the_error_carries_what_the_tool_printed(self) -> None:
        """STDOUT OFTEN HOLDS THE REASON even on failure -- a parse error, a
        usage message, a partial result."""
        runner = echoing(returncode=1, stdout="partial output")

        with pytest.raises(subprocess.CalledProcessError) as raised:
            run_command(CommandRequest(argv=["opa"]), runner=runner)

        assert raised.value.output == "partial output"

    def test_the_error_carries_the_diagnostics(self) -> None:
        runner = echoing(returncode=1, stderr="rego_parse_error")

        with pytest.raises(subprocess.CalledProcessError) as raised:
            run_command(CommandRequest(argv=["opa"]), runner=runner)

        assert raised.value.stderr == "rego_parse_error"

    def test_every_field_survives_together(self) -> None:
        """EACH MUTATED INDEPENDENTLY, so all three are asserted in one failure
        rather than trusting three cases to cover the set between them."""
        runner = echoing(returncode=3, stdout="out", stderr="err")

        with pytest.raises(subprocess.CalledProcessError) as raised:
            run_command(CommandRequest(argv=["opa", "eval"]), runner=runner)

        assert (raised.value.returncode, raised.value.output, raised.value.stderr) == (
            3,
            "out",
            "err",
        )

    def test_a_tolerated_failure_carries_the_same_facts(self) -> None:
        """THE NON-RAISING PATH REPORTS THE SAME THINGS, so a caller reading the
        result is no worse informed than one catching the error."""
        result = run_command(
            CommandRequest(argv=["git"], tolerate_failure=True),
            runner=echoing(returncode=128, stdout="out", stderr="not a repository"),
        )

        assert (result.returncode, result.stdout, result.stderr) == (
            128,
            "out",
            "not a repository",
        )
