# tests/test_author_cli.py
# THE AUTHORING COMMAND, SO THE SHELL STOPS BEING THE WRITER IN PRACTICE.
#
# WHY NOW. Writing .github/workflows/ci.yml failed with
#
#   zsh: no such file or directory: .github/workflows/ci.yml
#
# because a redirect creates the FILE and never the DIRECTORY. That is one of
# the four defects author_verbatim was written to remove, and the module has
# existed for several commits with no way to invoke it from a terminal. A tool
# that fixes a problem and cannot be reached when the problem occurs is not a
# fix.
#
# --- WHY THE PAYLOAD ARRIVES ON STDIN -----------------------------------------
#
# The bytes have to cross the terminal somehow. The 2026 position is not that
# heredocs are forbidden -- it is that the SHELL MUST NOT BE THE WRITER:
# heredocs feeding an INTERPRETER are explicitly acceptable, and it is
# `cat > file` that is blocked. Reading stdin puts Python in charge of the
# write while the shell does nothing but carry bytes.
#
# stdin.buffer, NEVER stdin. Reading text applies an encoding and newline
# translation, which would defeat the verbatim guarantee at the last step. The
# CLI reads raw bytes and hands them to the same author_verbatim every other
# caller uses.
#
# --- WHY IT EMITS A VERDICT ---------------------------------------------------
#
# Authoring is not a gate; observing is. The command therefore writes the file,
# then READS IT BACK and judges it, printing the Verdict as data on stdout. The
# exit code comes from that verdict, so a corrupted transport fails the command
# rather than being reported as success by a shell that only knows `cat`
# returned zero.

import json
from pathlib import Path

import pytest

from cs1090a_spec_driven_development.__main__ import main
from cs1090a_spec_driven_development.contracts.verdict import GateVerdict

SOURCE = b"# pkg/mod.py\nprint('hello')\n"


def payload_headed(path: str) -> bytes:
    return f"# {path}\nprint('hello')\n".encode()


@pytest.fixture
def stdin_bytes(monkeypatch: pytest.MonkeyPatch) -> object:
    """Replace stdin with a byte buffer the CLI can read.

    A CALLABLE FIXTURE, because each test supplies different bytes and the
    replacement must happen before main() runs.
    """

    def supply(payload: bytes) -> None:
        import io

        stream = io.TextIOWrapper(io.BytesIO(payload))
        monkeypatch.setattr("sys.stdin", stream)

    return supply


class TestAuthoringACommand:
    def test_a_file_is_written_from_stdin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdin_bytes: object
    ) -> None:
        monkeypatch.chdir(tmp_path)
        stdin_bytes(SOURCE)  # type: ignore[operator]

        assert main(["author", "pkg/mod.py"]) == 0
        assert (tmp_path / "pkg/mod.py").read_bytes() == SOURCE

    def test_missing_parent_directories_are_created(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdin_bytes: object
    ) -> None:
        """THE DEFECT THAT PROMPTED THIS COMMAND.

        `cat > .github/workflows/ci.yml` fails outright when the directories do
        not exist. This is the same write, and it succeeds.
        """
        monkeypatch.chdir(tmp_path)
        stdin_bytes(payload_headed(".github/workflows/ci.yml"))  # type: ignore[operator]

        assert main(["author", ".github/workflows/ci.yml"]) == 0
        assert (tmp_path / ".github/workflows/ci.yml").is_file()

    def test_the_bytes_land_verbatim(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdin_bytes: object
    ) -> None:
        """CRLF AND A TRAILING NUL SURVIVE, which text mode would rewrite."""
        payload = b"# f.txt\r\na\x00b\r\n"
        monkeypatch.chdir(tmp_path)
        stdin_bytes(payload)  # type: ignore[operator]

        main(["author", "f.txt"])

        assert (tmp_path / "f.txt").read_bytes() == payload

    def test_a_verdict_is_printed_on_stdout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        stdin_bytes: object,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """AUTHORING WRITES; OBSERVING JUDGES. The command does both, and the
        judgement is data rather than a console message."""
        monkeypatch.chdir(tmp_path)
        stdin_bytes(payload_headed("pkg/mod.py"))  # type: ignore[operator]

        main(["author", "pkg/mod.py"])
        printed = json.loads(capsys.readouterr().out)

        assert printed["gate"] == "authored_file_integrity"
        assert printed["subject"] == "pkg/mod.py"
        assert printed["verdict"] == GateVerdict.PASS.value

    def test_a_header_naming_another_path_fails_the_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdin_bytes: object
    ) -> None:
        """THE EXIT CODE FOLLOWS THE VERDICT, so a bad write fails the shell
        rather than being reported as success because `cat` returned zero."""
        monkeypatch.chdir(tmp_path)
        stdin_bytes(payload_headed("pkg/other.py"))  # type: ignore[operator]

        assert main(["author", "pkg/mod.py"]) == 1

    def test_a_stray_delimiter_fails_the_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdin_bytes: object
    ) -> None:
        """TRANSPORT LEAKAGE IS STILL DETECTED, because the payload still
        crosses a terminal."""
        monkeypatch.chdir(tmp_path)
        stdin_bytes(b"# f.py\nprint('x')\nPY\n")  # type: ignore[operator]

        assert main(["author", "f.py"]) == 1

    def test_an_empty_payload_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdin_bytes: object
    ) -> None:
        """A ZERO-BYTE WRITE IS THE MISFIRED HEREDOC, and the target must not be
        truncated on the way to discovering that."""
        target = tmp_path / "f.py"
        target.write_bytes(b"# original\n")
        monkeypatch.chdir(tmp_path)
        stdin_bytes(b"")  # type: ignore[operator]

        with pytest.raises(ValueError, match="must not be empty"):
            main(["author", "f.py"])

        assert target.read_bytes() == b"# original\n"

    def test_a_path_outside_the_repository_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdin_bytes: object
    ) -> None:
        monkeypatch.chdir(tmp_path)
        stdin_bytes(SOURCE)  # type: ignore[operator]

        with pytest.raises(ValueError, match="must not traverse"):
            main(["author", "../escaped.py"])


class TestAuthorDispatch:
    def test_the_command_requires_a_path(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A WRITE WITH NO DESTINATION is a caller error, which exits 2."""
        assert main(["author"]) == 2
        assert "usage:" in capsys.readouterr().err

    def test_more_than_one_path_is_refused(self, capsys: pytest.CaptureFixture[str]) -> None:
        """ONE FILE PER INVOCATION. Two paths and one stdin cannot both be
        honoured, and guessing which was meant is worse than refusing."""
        assert main(["author", "a.py", "b.py"]) == 2

    def test_the_usage_line_mentions_both_gates(self, capsys: pytest.CaptureFixture[str]) -> None:
        main([])

        assert "author" in capsys.readouterr().err
