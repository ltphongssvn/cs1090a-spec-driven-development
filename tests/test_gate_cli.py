# tests/test_gate_cli.py
# THE GATE ENTRY POINT, TESTED AFTER THE FACT -- AND THAT IS A DEFECT.
#
# THIS FILE WAS WRITTEN SECOND. __main__.py was authored before any failing test
# demanded it, which inverts the order this project holds everywhere else. The
# honest record is that the module was written on assumption and this suite
# checked those assumptions retrospectively, which is weaker evidence: a test
# written after the code tends to describe what the code does rather than what
# the requirement was. It is recorded here rather than quietly forgotten.
#
# THE TESTS ARE THEREFORE WRITTEN AGAINST THE REQUIREMENT. Each states what a
# gate runner must do for the gate to be trustworthy at all:
#
#   THE EXIT CODE FOLLOWS THE VERDICT. Not the reverse. A runner that decides
#   its own exit status can disagree with the document it just wrote, and the
#   document is what an auditor reads.
#
#   THREE OUTCOMES REACH THE SHELL. pass/fail/unknown must not collapse into
#   pass/fail, or "the gate measured nothing" becomes indistinguishable from
#   "the gate measured something and it was wrong".
#
#   THE VERDICT IS WRITTEN, NOT ONLY PRINTED. A verdict existing solely in a
#   scrollback is the ephemeral console output this project replaced.
#
#   A MISSING REPORT NEVER PASSES. The runner must fail loudly on a machine
#   where mutmut never ran.

import json
from pathlib import Path

import pytest

from conftest import containing
from cs1090a_spec_driven_development.__main__ import (
    main,
    record,
    run_mutation_gate,
    verdict_path_for,
)
from cs1090a_spec_driven_development.contracts.verdict import (
    Check,
    CheckVerdict,
    GateVerdict,
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


def write_stats(root: Path, **overrides: int) -> Path:
    artifact = root / "mutants/mutmut-cicd-stats.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(CLEAN | overrides))
    return artifact


def read_verdict(root: Path, gate: str) -> Verdict:
    return Verdict.model_validate_json((root / verdict_path_for(gate)).read_text())


def example_verdict() -> Verdict:
    return Verdict(gate="example", subject="s", checks=[Check(id="a", verdict=CheckVerdict.PASS)])


class TestExitCodesFollowTheVerdict:
    def test_a_clean_run_exits_zero(self, tmp_path: Path) -> None:
        write_stats(tmp_path)

        assert run_mutation_gate(tmp_path) == 0

    def test_a_survivor_exits_one(self, tmp_path: Path) -> None:
        write_stats(tmp_path, survived=1, killed=473)

        assert run_mutation_gate(tmp_path) == 1

    def test_a_vacuous_run_exits_two_rather_than_zero(self, tmp_path: Path) -> None:
        """THE FAILURE THIS REPOSITORY ALREADY EXPERIENCED.

        Zero survivors out of zero mutants exits 2, so CI can distinguish a gate
        that passed from one that never measured anything. Collapsing this into
        0 is how a green build certifies untested code.
        """
        write_stats(tmp_path, killed=0, survived=0, total=0)

        assert run_mutation_gate(tmp_path) == 2

    def test_an_interrupted_run_exits_two(self, tmp_path: Path) -> None:
        write_stats(tmp_path, check_was_interrupted_by_user=1)

        assert run_mutation_gate(tmp_path) == 2

    def test_the_exit_code_matches_the_written_verdict(self, tmp_path: Path) -> None:
        """THE INVARIANT THAT BINDS THE TWO.

        The code and the document must never disagree, because each is read by a
        different audience -- CI reads the code, an auditor reads the document.
        """
        write_stats(tmp_path, survived=2, killed=472)

        code = run_mutation_gate(tmp_path)

        assert read_verdict(tmp_path, "mutation_zero_survivors").exit_code == code


class TestTheVerdictIsRecorded:
    def test_a_verdict_file_is_written(self, tmp_path: Path) -> None:
        write_stats(tmp_path)

        run_mutation_gate(tmp_path)

        assert (tmp_path / ".artifacts/verdicts/mutation_zero_survivors.json").is_file()

    def test_the_written_verdict_is_valid_json_matching_the_contract(self, tmp_path: Path) -> None:
        """A RECORD NOTHING CAN PARSE IS NOT EVIDENCE."""
        write_stats(tmp_path, survived=3, killed=471)

        run_mutation_gate(tmp_path)
        verdict = read_verdict(tmp_path, "mutation_zero_survivors")

        assert verdict.verdict is GateVerdict.FAIL
        assert verdict.reasons == ["zero_survivors"]

    def test_the_record_carries_the_observed_counts(self, tmp_path: Path) -> None:
        """EVIDENCE AS DATA: the record answers "how many" without a re-run."""
        write_stats(tmp_path, survived=3, killed=471)

        run_mutation_gate(tmp_path)
        verdict = read_verdict(tmp_path, "mutation_zero_survivors")
        survivors = next(check for check in verdict.checks if check.id == "zero_survivors")

        assert survivors.observed == 3

    def test_a_later_run_replaces_the_earlier_record(self, tmp_path: Path) -> None:
        """THE QUESTION IS WHAT THE GATE SAYS NOW.

        Accumulating timestamped files would grow without bound and leave a
        reader to work out which one is current.
        """
        write_stats(tmp_path, survived=1, killed=473)
        run_mutation_gate(tmp_path)

        write_stats(tmp_path)
        run_mutation_gate(tmp_path)

        assert read_verdict(tmp_path, "mutation_zero_survivors").verdict is GateVerdict.PASS

    def test_the_file_is_named_for_its_gate(self) -> None:
        assert verdict_path_for("mutation_zero_survivors") == Path(
            ".artifacts/verdicts/mutation_zero_survivors.json"
        )

    def test_recording_creates_the_directory_when_absent(self, tmp_path: Path) -> None:
        """A FRESH CLONE HAS NO .artifacts DIRECTORY, and the gate must not fail
        for that reason on its first run."""
        destination = record(example_verdict(), root=tmp_path)

        assert (tmp_path / destination).is_file()

    def test_the_record_ends_with_a_newline(self, tmp_path: Path) -> None:
        """POSIX TEXT FILES END WITH ONE, and tools that concatenate records
        otherwise join two documents on a single line.
        """
        destination = record(example_verdict(), root=tmp_path)

        assert (tmp_path / destination).read_bytes().endswith(b"\n")


class TestMissingOrBrokenInput:
    def test_a_missing_report_raises_rather_than_passing(self, tmp_path: Path) -> None:
        """THE MOST DANGEROUS FAILURE MODE. A runner treating absence as success
        passes wherever mutmut never ran."""
        with pytest.raises(FileNotFoundError, match=containing("mutmut-cicd-stats.json")):
            run_mutation_gate(tmp_path)

    def test_the_refusal_says_how_to_produce_the_report(self, tmp_path: Path) -> None:
        """A REFUSAL THAT DOES NOT SAY WHAT TO DO NEXT costs the reader a search."""
        with pytest.raises(FileNotFoundError, match=containing("mise run mutants")):
            run_mutation_gate(tmp_path)

    def test_a_malformed_report_raises(self, tmp_path: Path) -> None:
        artifact = tmp_path / "mutants/mutmut-cicd-stats.json"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("{not json")

        with pytest.raises(ValueError, match=containing("is not valid JSON")):
            run_mutation_gate(tmp_path)


class TestDispatch:
    def test_an_unknown_gate_exits_two(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A CALLER ERROR IS NOT A FAILING CHECK, and CI must not confuse them."""
        assert main(["nonexistent"]) == 2

        assert "unknown gate: nonexistent" in capsys.readouterr().err

    def test_no_arguments_exits_two_and_shows_usage(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main([]) == 2

        assert "usage:" in capsys.readouterr().err
