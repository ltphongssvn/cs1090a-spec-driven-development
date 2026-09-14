# tests/test_gate_root_and_argv.py
# THE FIVE SURVIVORS THAT SUBPROCESS TESTS CANNOT KILL.
#
# --- WHY A SUBPROCESS TEST CANNOT KILL A MUTANT -------------------------------
#
# mutmut instruments the package with a TRAMPOLINE that records, IN PROCESS,
# which test touched which function. A child process launched by subprocess.run
# imports the mutated code and may well crash on it -- but the parent's
# trampoline never sees that, so mutmut does not attribute the test to the
# mutant and never runs the two together.
#
# THE CONSEQUENCE IS EXACT: every line reachable only through `python -m ...`
# is unmeasurable, no matter how carefully the subprocess asserts. These five
# survived for that reason and no other:
#
#   override = os.environ.get(ROOT_VARIABLE)  ->  override = None
#   Path(override) if override else Path.cwd()  ->  Path(None) if ...
#   arguments = sys.argv[1:]  ->  sys.argv[2:]
#   '(none)'  ->  'XX(none)XX'  and  '(NONE)'
#
# THE SUBPROCESS TESTS ARE KEPT. They proved the real `python -m` path works --
# and they caught two genuine defects in doing so. But proving the wiring and
# measuring the logic are different jobs, and only the second can be done in
# process.
#
# THE FIX IS THEREFORE NOT TO DELETE THEM BUT TO DUPLICATE THE ASSERTIONS where
# mutmut can observe them: monkeypatch the environment and sys.argv, and call
# main() directly. Nothing here launches a process.

import os
from pathlib import Path

import pytest

from cs1090a_spec_driven_development.__main__ import (
    ROOT_VARIABLE,
    VERDICT_DIRECTORY,
    gate_root,
    main,
    verdict_path_for,
)

USAGE = "usage: python -m cs1090a_spec_driven_development mutants"


class TestGateRoot:
    def test_the_environment_variable_overrides_the_working_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """override = None SURVIVED because no in-process test set the variable.

        The directory a gate RUNS in and the directory its report lives in are
        different concerns: a mutated package must run where mutmut's config is,
        while its report belongs somewhere disposable.
        """
        monkeypatch.setenv(ROOT_VARIABLE, str(tmp_path))

        assert gate_root() == tmp_path

    def test_the_working_directory_is_used_when_the_variable_is_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """THE DEFAULT, so nothing changes for the ordinary invocation."""
        monkeypatch.delenv(ROOT_VARIABLE, raising=False)
        monkeypatch.chdir(tmp_path)

        assert gate_root() == Path.cwd()

    def test_an_empty_variable_falls_back_rather_than_naming_the_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Path(None) SURVIVED, AND Path("") IS THE REAL TRAP.

        An unset variable in CI commonly arrives as the empty string. Path("")
        is the CURRENT directory expressed as ".", which happens to be harmless
        here -- but the truthiness test is what makes that deliberate rather
        than lucky, and `Path(None)` would raise.
        """
        monkeypatch.setenv(ROOT_VARIABLE, "")
        monkeypatch.chdir(tmp_path)

        assert gate_root() == Path.cwd()

    def test_the_variable_is_read_by_its_documented_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A CONSTANT NOBODY ASSERTS CAN BE RENAMED WITHOUT ANY TEST OBJECTING,
        and CI would then silently write verdicts to the wrong place."""
        assert ROOT_VARIABLE == "CS1090A_GATE_ROOT"

        monkeypatch.setenv("CS1090A_GATE_ROOT", str(tmp_path))

        assert gate_root() == tmp_path

    def test_a_relative_override_is_honoured_as_given(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """NOT RESOLVED HERE. The caller's relative path is theirs to interpret;
        silently absolutising it would surprise a CI job that meant it.
        """
        monkeypatch.setenv(ROOT_VARIABLE, "build/reports")

        assert gate_root() == Path("build/reports")

    def test_the_environment_is_not_mutated_by_reading_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A GETTER THAT WRITES IS A GETTER NOBODY CAN CALL TWICE SAFELY."""
        monkeypatch.setenv(ROOT_VARIABLE, str(tmp_path))
        before = dict(os.environ)

        gate_root()

        assert dict(os.environ) == before


class TestArgvSlice:
    def test_the_gate_name_is_taken_from_the_first_argument(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """sys.argv[2:] SURVIVED because every in-process test supplied argv.

        argv[0] is the program name, so the gate is argv[1]. The mutant drops it
        and every real invocation reports "unknown gate".
        """
        monkeypatch.setenv(ROOT_VARIABLE, str(tmp_path))
        monkeypatch.setattr("sys.argv", ["python -m cs1090a_spec_driven_development", "mutants"])

        # No report exists in tmp_path, so a CORRECT slice reaches the gate and
        # raises; the mutant instead prints "unknown gate" and returns 2.
        with pytest.raises(FileNotFoundError):
            main()

    def test_an_empty_argument_vector_reports_no_gate(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """THE SLICE AGAIN, from the other side: with only the program name,
        argv[1:] is empty and argv[2:] is also empty -- so this case alone
        cannot distinguish them, which is why the test above exists too."""
        monkeypatch.setattr("sys.argv", ["python -m cs1090a_spec_driven_development"])

        assert main() == 2
        assert capsys.readouterr().err.splitlines()[0] == "unknown gate: (none)"

    def test_an_explicit_argv_still_takes_precedence(self) -> None:
        """THE TEST SEAM ITSELF. Passing argv must bypass sys.argv entirely, or
        every test in this suite would depend on the ambient command line.
        """
        assert main(["nonexistent"]) == 2


class TestMessagesInProcess:
    def test_no_arguments_names_the_absence_exactly(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """'XX(none)XX' AND '(NONE)' BOTH SURVIVED.

        The sentinel-wrapped mutant CONTAINS the original, so `in` passes
        against it; the uppercase mutant differs only in case, which a
        case-insensitive reading would miss. Equality on the whole line closes
        both.
        """
        main([])

        assert capsys.readouterr().err.splitlines()[0] == "unknown gate: (none)"

    def test_a_named_gate_is_reported_verbatim(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(["nonexistent"])

        assert capsys.readouterr().err.splitlines()[0] == "unknown gate: nonexistent"

    def test_several_arguments_are_joined_with_one_space(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(["two", "words"])

        assert capsys.readouterr().err.splitlines()[0] == "unknown gate: two words"

    def test_the_usage_line_is_exactly_this(self, capsys: pytest.CaptureFixture[str]) -> None:
        main([])

        assert capsys.readouterr().err.splitlines()[1] == USAGE

    def test_nothing_is_printed_to_stdout_on_a_caller_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """THE PIPE CONTRACT HOLDS ON THE ERROR PATH TOO. A consumer piping
        stdout into jq must get empty input, not a usage message.
        """
        main([])

        assert capsys.readouterr().out == ""


class TestVerdictPaths:
    def test_the_verdict_directory_is_under_artifacts(self) -> None:
        """GITIGNORED BY DESIGN: a verdict is a fact about one execution on one
        machine, not source."""
        assert Path(".artifacts/verdicts") == VERDICT_DIRECTORY

    def test_the_file_is_named_for_its_gate(self) -> None:
        assert verdict_path_for("mutation_zero_survivors") == Path(
            ".artifacts/verdicts/mutation_zero_survivors.json"
        )

    def test_two_gates_write_to_two_files(self) -> None:
        """ONE FILE PER GATE, so a second gate added later cannot overwrite the
        first's record."""
        assert verdict_path_for("a") != verdict_path_for("b")
