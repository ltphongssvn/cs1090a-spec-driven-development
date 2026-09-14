# tests/test_gate_cli_output.py
# WHAT THE GATE RUNNER PRINTS, AND HOW IT IS INVOKED FOR REAL.
#
# SURVIVORS IN THE ENFORCER MATTER MORE THAN SURVIVORS ANYWHERE ELSE: a gate
# nothing measures is the most dangerous module in a repository that trusts it.
#
# --- A GENUINE DEFECT, FOUND BY THE GATE IN ITSELF ----------------------------
#
#   arguments = sys.argv[1:]  mutated to  sys.argv[2:]
#   run_mutation_gate(Path.cwd())  mutated to  run_mutation_gate(None)
#
# Both survived because every in-process test passes argv and root explicitly.
# The real invocation -- `python -m ... mutants`, which is what
# `mise run mutants:check` runs -- was never executed against a mutant.
#
# --- TWO SUCCESSIVE MISTAKES IN THESE SUBPROCESS TESTS, BOTH INSTRUCTIVE ------
#
# FIRST: PYTHONPATH WAS LEFT TO INHERIT mutmut's RELATIVE "src". The child ran
# with cwd=tmp_path, where "src" does not exist, so it fell through to the
# INSTALLED package and executed UNMUTATED code. Every assertion passed no
# matter what the mutant said -- a test that proves nothing while looking
# thorough.
#
# SECOND, FIXING THAT BROKE THE RUN A DIFFERENT WAY. An absolute path to
# mutants/src makes the child import the mutated package, and the mutated
# __init__ imports mutmut's trampoline, which LOADS MUTMUT'S CONFIG FROM THE
# WORKING DIRECTORY. With cwd=tmp_path there is no pyproject.toml, so mutmut
# raised "Could not figure out where the code to mutate is" at import time and
# the whole mutation run aborted.
#
# THE TWO REQUIREMENTS WERE CONFLATED. The child needs the REPOSITORY as its
# working directory so configuration resolves, and it needs a TEMPORARY
# directory for the report so tests do not overwrite the real one. Those are
# different concerns and are now different arguments: cwd is always the repo,
# and the report location travels through an environment variable the gate
# reads.
#
# --- THE REST ARE MESSAGES ASSERTED TOO LOOSELY -------------------------------
#
#   "usage: ..." -> "XXusage: ...XX"   survived an `in` assertion, because the
#   sentinel-wrapped mutant CONTAINS the original. Equality on the line closes
#   it -- the same looseness that hid the earlier XX mutants, in a new disguise.

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import cs1090a_spec_driven_development
from cs1090a_spec_driven_development.__main__ import main, record, run_mutation_gate
from cs1090a_spec_driven_development.contracts.verdict import (
    Check,
    CheckVerdict,
    Verdict,
)

CLEAN = {
    "killed": 474,
    "survived": 0,
    "total": 474,
    "no_tests": 0,
    "skipped": 0,
    "suspicious": 0,
    "timeout": 0,
    "check_was_interrupted_by_user": 0,
    "segfault": 0,
}

MODULE = "cs1090a_spec_driven_development"
USAGE = "usage: python -m cs1090a_spec_driven_development mutants"


def importable_root() -> Path:
    """The directory the package under test was imported from.

    ABSOLUTE, AND DERIVED RATHER THAN ASSUMED. Under mutmut this resolves to
    mutants/src, so the subprocess executes the MUTATED package; outside it, the
    real source tree. Hard-coding "src" made these tests vacuous.
    """
    package = Path(cs1090a_spec_driven_development.__file__).resolve().parent
    return package.parent


def working_directory() -> Path:
    """Where the child process must run.

    THE REPOSITORY, ALWAYS -- which under mutmut is the mutants/ copy, since it
    contains its own pyproject.toml. The mutated package imports mutmut's
    trampoline at module load, and that reads mutmut's configuration from the
    CURRENT DIRECTORY. Running elsewhere aborts the whole mutation run at import
    time with "Could not figure out where the code to mutate is".
    """
    return importable_root().parent


def run_module(*arguments: str, report_root: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the gate the way CI does, with the report in a scratch directory.

    THE REPORT LOCATION TRAVELS SEPARATELY FROM THE WORKING DIRECTORY, because
    conflating them is what broke the previous version of this file.
    """
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(importable_root())
    environment["CS1090A_GATE_ROOT"] = str(report_root)

    return subprocess.run(
        [sys.executable, "-m", MODULE, *arguments],
        cwd=working_directory(),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def write_stats(root: Path, **overrides: int) -> None:
    artifact = root / "mutants/mutmut-cicd-stats.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(CLEAN | overrides))


def example_verdict() -> Verdict:
    return Verdict(gate="example", subject="s", checks=[Check(id="a", verdict=CheckVerdict.PASS)])


class TestRealInvocation:
    """The path production takes, which no in-process test exercises."""

    def test_the_module_runs_as_a_command_and_exits_zero_on_a_clean_run(
        self, tmp_path: Path
    ) -> None:
        """THE sys.argv SLICE, KILLED BY A REAL ARGUMENT VECTOR.

        argv[2:] drops the gate name, so the command reports "unknown gate" and
        exits 2 instead of judging the report.
        """
        write_stats(tmp_path)

        completed = run_module("mutants", report_root=tmp_path)

        assert completed.returncode == 0, completed.stderr

    def test_the_command_exits_one_when_a_mutant_survived(self, tmp_path: Path) -> None:
        write_stats(tmp_path, survived=1, killed=473)

        completed = run_module("mutants", report_root=tmp_path)

        assert completed.returncode == 1, completed.stderr

    def test_the_command_writes_its_verdict_beside_the_report(self, tmp_path: Path) -> None:
        write_stats(tmp_path, survived=9, killed=465)

        completed = run_module("mutants", report_root=tmp_path)

        assert json.loads(completed.stdout)["reasons"] == ["zero_survivors"]
        assert (tmp_path / ".artifacts/verdicts/mutation_zero_survivors.json").is_file()

    def test_an_unknown_gate_name_exits_two(self, tmp_path: Path) -> None:
        completed = run_module("nonexistent", report_root=tmp_path)

        assert completed.returncode == 2
        assert completed.stderr.splitlines()[0] == "unknown gate: nonexistent"

    def test_no_gate_name_exits_two_and_says_so_exactly(self, tmp_path: Path) -> None:
        """EQUALITY, NOT CONTAINMENT. "(none)" is a substring of the mutant's
        "XX(none)XX", so an `in` assertion passes against it.
        """
        completed = run_module(report_root=tmp_path)

        assert completed.returncode == 2
        assert completed.stderr.splitlines()[0] == "unknown gate: (none)"

    def test_the_usage_line_is_exactly_this(self, tmp_path: Path) -> None:
        completed = run_module(report_root=tmp_path)

        assert completed.stderr.splitlines()[1] == USAGE


class TestInProcessDispatch:
    def test_the_gate_name_is_matched_exactly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ "XXmutantsXX" SURVIVED because no test ran the REAL name in process.

        chdir rather than an explicit root, because this exercises the default
        that the explicit-root tests bypass.
        """
        write_stats(tmp_path)
        monkeypatch.chdir(tmp_path)

        assert main(["mutants"]) == 0

    def test_an_uppercase_gate_name_is_refused(self) -> None:
        """Command names are case-sensitive; a runner accepting either spelling
        accepts a typo as a command."""
        assert main(["MUTANTS"]) == 2

    def test_a_padded_gate_name_is_refused(self) -> None:
        assert main([" mutants "]) == 2

    def test_the_unknown_gate_message_joins_arguments_with_a_single_space(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """'XX XX'.join SURVIVED. The separator is asserted, not assumed."""
        main(["two", "words"])

        assert capsys.readouterr().err.splitlines()[0] == "unknown gate: two words"

    def test_the_usage_line_is_printed_verbatim(self, capsys: pytest.CaptureFixture[str]) -> None:
        main([])

        assert capsys.readouterr().err.splitlines()[1] == USAGE


class TestStreamSeparation:
    def test_the_verdict_goes_to_stdout_and_the_note_to_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """THE PIPE CONTRACT. A consumer pipes stdout into jq; the human note
        must not land in that pipe and corrupt it.
        """
        write_stats(tmp_path)

        run_mutation_gate(tmp_path)
        captured = capsys.readouterr()

        assert json.loads(captured.out)["verdict"] == "pass"
        assert "verdict written to" in captured.err
        assert "verdict written to" not in captured.out

    def test_stdout_is_parseable_json_and_nothing_else(self, tmp_path: Path) -> None:
        """THROUGH A SUBPROCESS, so it holds for the real stream and not merely
        for pytest's capture."""
        write_stats(tmp_path)

        completed = run_module("mutants", report_root=tmp_path)

        assert json.loads(completed.stdout)["gate"] == "mutation_zero_survivors"

    def test_the_note_names_where_the_verdict_was_written(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """print(None, file=sys.stderr) SURVIVED because nothing read the text."""
        write_stats(tmp_path)

        run_mutation_gate(tmp_path)

        assert ".artifacts/verdicts/mutation_zero_survivors.json" in capsys.readouterr().err


class TestRecordFormatting:
    def test_the_record_is_indented_for_human_review(self, tmp_path: Path) -> None:
        """indent=None SURVIVED, and it is not cosmetic.

        The record is published as a CI artifact and read by people. One long
        line is unreadable in review and produces a single-line diff for every
        change, destroying the reviewability the record exists for.
        """
        destination = record(example_verdict(), root=tmp_path)
        content = (tmp_path / destination).read_text()

        assert content.startswith("{\n")
        assert '\n  "gate":' in content

    def test_the_indentation_is_two_spaces(self, tmp_path: Path) -> None:
        """indent=3 SURVIVED TOO, so the width is pinned and not merely its
        presence."""
        destination = record(example_verdict(), root=tmp_path)
        lines = (tmp_path / destination).read_text().splitlines()

        gate_line = next(line for line in lines if '"gate"' in line)

        assert gate_line.startswith('  "gate"')
        assert not gate_line.startswith("   ")

    def test_the_printed_verdict_is_indented_too(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_stats(tmp_path)

        run_mutation_gate(tmp_path)
        out = capsys.readouterr().out

        assert out.startswith("{\n")
        assert '\n  "gate":' in out

    def test_the_printed_verdict_and_the_written_verdict_agree(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """ONE VERDICT, TWO DESTINATIONS. A runner printing one document and
        recording another gives CI and the auditor different answers.
        """
        write_stats(tmp_path, survived=4, killed=470)

        run_mutation_gate(tmp_path)
        printed = json.loads(capsys.readouterr().out)
        written = json.loads(
            (tmp_path / ".artifacts/verdicts/mutation_zero_survivors.json").read_text()
        )

        assert printed == written
