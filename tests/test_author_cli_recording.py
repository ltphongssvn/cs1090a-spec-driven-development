# tests/test_author_cli_recording.py
# THE AUTHOR COMMAND'S OWN RECORD, WHICH NOTHING WAS READING.
#
# THE SURVIVOR was `report(verdict, record(verdict, root=root))` becoming
# `report(verdict, None)`. The record is still written -- record() runs either
# way -- but the destination reported to the user becomes the string "None".
#
# WHY NOTHING CAUGHT IT. Every author test asserted the FILE that was written
# and the VERDICT that was printed. Neither reads the stderr note, and the
# destination appears nowhere else, so the argument could be replaced by any
# value at all without a single assertion changing.
#
# THE CONSEQUENCE IS NOT COSMETIC. "verdict written to None" is what a user sees
# after every write, and the path is the only way to find the evidence
# afterwards. A record nobody can locate is a record nobody has.
#
# THE SAME HOLE EXISTED FOR THE MUTATION GATE and was closed there by
# test_gate_cli_output.py asserting the note. This file does it for authoring,
# which is the other caller of the same report() function -- one shared helper,
# two call sites, and only one of them was covered.

import json
from pathlib import Path

import pytest

from cs1090a_spec_driven_development.__main__ import main, verdict_path_for


def payload_headed(path: str) -> bytes:
    return f"# {path}\nprint('hello')\n".encode()


@pytest.fixture
def stdin_bytes(monkeypatch: pytest.MonkeyPatch) -> object:
    """Replace stdin with a byte buffer the CLI can read."""

    def supply(payload: bytes) -> None:
        import io

        monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(payload)))

    return supply


class TestTheNoteNamesTheRecord:
    def test_the_destination_is_reported_on_stderr(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        stdin_bytes: object,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """THE SURVIVING MUTANT, KILLED.

        report(verdict, None) prints "verdict written to None", which passes
        every assertion this suite previously made.
        """
        monkeypatch.chdir(tmp_path)
        stdin_bytes(payload_headed("pkg/mod.py"))  # type: ignore[operator]

        main(["author", "pkg/mod.py"])

        assert ".artifacts/verdicts/authored_file_integrity.json" in capsys.readouterr().err

    def test_the_reported_path_is_the_file_that_exists(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        stdin_bytes: object,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """THE NOTE AND THE FILESYSTEM MUST AGREE.

        Asserting the text alone would still pass if record() wrote elsewhere;
        this reads the path out of the note and requires a file to be there.
        """
        monkeypatch.chdir(tmp_path)
        stdin_bytes(payload_headed("pkg/mod.py"))  # type: ignore[operator]

        main(["author", "pkg/mod.py"])
        note = capsys.readouterr().err.strip()
        reported = Path(note.rsplit(" ", 1)[-1])

        assert (tmp_path / reported).is_file()

    def test_the_note_does_not_say_none(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        stdin_bytes: object,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """STATED DIRECTLY, because the mutation is exactly this."""
        monkeypatch.chdir(tmp_path)
        stdin_bytes(payload_headed("f.py"))  # type: ignore[operator]

        main(["author", "f.py"])

        assert "None" not in capsys.readouterr().err

    def test_the_recorded_verdict_matches_the_printed_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        stdin_bytes: object,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """ONE VERDICT, TWO DESTINATIONS. A command printing one document and
        recording another gives the shell and the auditor different answers.
        """
        monkeypatch.chdir(tmp_path)
        stdin_bytes(payload_headed("pkg/mod.py"))  # type: ignore[operator]

        main(["author", "pkg/mod.py"])
        printed = json.loads(capsys.readouterr().out)
        written = json.loads((tmp_path / verdict_path_for("authored_file_integrity")).read_text())

        assert printed == written

    def test_a_failing_write_is_still_recorded(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        stdin_bytes: object,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """EVIDENCE MATTERS MOST WHEN THE GATE FAILED.

        A header naming another path fails the command; the record must exist
        anyway, or the one case anyone would investigate leaves no trace.
        """
        monkeypatch.chdir(tmp_path)
        stdin_bytes(payload_headed("pkg/other.py"))  # type: ignore[operator]

        assert main(["author", "pkg/mod.py"]) == 1

        recorded = json.loads((tmp_path / verdict_path_for("authored_file_integrity")).read_text())
        assert recorded["verdict"] == "fail"
        assert recorded["reasons"] == ["path_header_comment"]

    def test_the_record_is_named_for_the_authoring_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdin_bytes: object
    ) -> None:
        """NOT THE SUBJECT. One file per GATE, so authoring a second file
        replaces the record rather than accumulating one per path written.
        """
        monkeypatch.chdir(tmp_path)
        stdin_bytes(payload_headed("a.py"))  # type: ignore[operator]
        main(["author", "a.py"])

        stdin_bytes(payload_headed("b.py"))  # type: ignore[operator]
        main(["author", "b.py"])

        recorded = json.loads((tmp_path / verdict_path_for("authored_file_integrity")).read_text())
        assert recorded["subject"] == "b.py"
