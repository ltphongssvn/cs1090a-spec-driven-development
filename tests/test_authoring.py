# tests/test_authoring.py
# THE PYTHON-NATIVE REPLACEMENT FOR `cat > path << 'EOF'`, DRIVEN BY ITS TEST.
#
# THIS FILE LIVES IN tests/ RATHER THAN tests/unit/ FOR ONE TURN, and the reason
# is the bug it exists to fix: the shell redirect that wrote it cannot create a
# parent directory, so `cat > tests/unit/x.py` failed outright. It moves once
# the tool specified below can create parents.
#
# --- WHY THE SHELL STOPS BEING THE WRITER -------------------------------------
#
# A heredoc makes the SHELL responsible for delivering source bytes, and the
# shell is an unreliable narrator about them. Editor and agent tooling collapses
# newlines when normalising a command, turning a multi-line heredoc into a
# single line and corrupting the file with no error. The redirect also creates
# or truncates the target BEFORE the payload arrives, so an interrupted write
# leaves a half-written or empty file where source used to be.
#
#   AUTHORING  writes verbatim bytes, atomically. It is NOT a gate. It reports
#              what it did, and raises when it cannot do it.
#   OBSERVING  reads the file BACK FROM DISK and judges it. It trusts nothing
#              the writer said.
#
# --- WHY THE HEADER EXPECTATION IS NO LONGER A PARAMETER ----------------------
#
# THE FIRST RUN OF THIS SUITE FAILED, AND THE FIXTURE WAS AT FAULT rather than
# the code: a payload headed `# example.py` was written to `pkg/mod.py`, and the
# gate correctly refused it, naming path_header_comment.
#
# THE ROOT CAUSE WAS A DUPLICATED FACT. The path was stated twice -- once inside
# the payload's first line, once in an expected_header argument -- and two
# declarations of one fact drift. Deleting the parameter and deriving the header
# from the path makes the mismatched pair unrepresentable.
#
# --- WHY THE PROPERTY TESTS ARE MODULE-LEVEL FUNCTIONS ------------------------
#
# THEY WERE METHODS ON A TEST CLASS, AND THE FIRST MUTATION RUN FAILED BECAUSE
# OF IT: Hypothesis raised HealthCheck.differing_executors, which it documents
# as a CORRECTNESS issue rather than a style warning, recommending the
# underlying cause be fixed rather than suppressed.
#
# THE CAUSE IS STRUCTURAL. A @given method binds to a class instance, and
# mutmut runs the suite repeatedly IN ONE PROCESS -- a stats pass, then a clean
# pass, then once per mutant -- so the same test function is invoked by
# different executors in the same thread. Hypothesis stopped raising this across
# THREADS in a later release but still raises it within one, which is our case
# exactly. Examples replayed from the database can then be attributed to the
# wrong executor, making a failure non-reproducible.
#
# SUPPRESSING IT WITH @settings WOULD HAVE HIDDEN A REAL DEFECT and left the
# replay database unreliable for the tests that matter most -- the generated
# ones. Module-level property tests have no executor to differ. The
# example-based tests keep their classes: they have no replay database and no
# executor sensitivity, and the grouping is worth keeping.
#
# --- WHY EACH GENERATED EXAMPLE BUILDS ITS OWN ROOT ---------------------------
#
# pytest's tmp_path is FUNCTION-SCOPED, and Hypothesis runs many examples inside
# ONE function call. A @given test taking tmp_path therefore writes every
# example into the same directory, so files from earlier examples survive into
# later ones -- and an assertion about directory contents passes or fails
# depending on generation order. Each example gets a fresh mkdtemp instead.

import hashlib
import tempfile
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from cs1090a_spec_driven_development.authoring import (
    AuthoringRequest,
    WrittenFile,
    author_verbatim,
    expected_header_for,
    observe_written_file,
)
from cs1090a_spec_driven_development.contracts.verdict import CheckVerdict, GateVerdict

SOURCE = b"# example.py\nprint('hello')\n"

# A PATH SPACE, NOT A PATH. Segments are restricted to characters legal on every
# filesystem this project supports; the point is to vary what should not matter,
# not to fuzz the operating system.
segments = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Nd")), min_size=1, max_size=8
)
relative_paths = st.lists(segments, min_size=1, max_size=4).map("/".join)


def payload_headed(path: str) -> bytes:
    """Source whose first line names the path it is about to occupy."""
    return f"# {path}\nprint('hello')\n".encode()


def _raise_os_error(*_args: object, **_kwargs: object) -> None:
    raise OSError("rename refused")


# --- Properties. MODULE-LEVEL BY NECESSITY; see the header. -------------------


@given(path=relative_paths)
def test_the_expected_header_is_the_path_behind_a_comment_marker(path: str) -> None:
    assert expected_header_for(Path(path)) == f"# {path}"


@given(path=relative_paths)
def test_the_header_derivation_uses_posix_separators_on_every_platform(path: str) -> None:
    """A HEADER IS SOURCE, AND SOURCE IS READ ON EVERY PLATFORM.

    Path rendering is OS-dependent; a file authored on Windows must not carry a
    backslash header that fails this gate everywhere else.
    """
    assert "\\" not in expected_header_for(Path(path))


@given(path=relative_paths)
def test_any_file_headed_with_its_own_path_passes(path: str) -> None:
    """THE PROPERTY THAT REPLACED A BRITTLE EXAMPLE.

    No particular path is privileged, so no future test can quietly come to
    depend on one.
    """
    root = Path(tempfile.mkdtemp())
    target = f"{path}.py"
    payload = payload_headed(target)

    written = author_verbatim(AuthoringRequest(path=Path(target), payload=payload), root=root)
    verdict = observe_written_file(
        written, root=root, expected_sha256=hashlib.sha256(payload).hexdigest()
    )

    assert verdict.verdict is GateVerdict.PASS
    assert verdict.reasons == []


@given(payload=st.binary(min_size=1, max_size=256))
def test_whatever_bytes_are_offered_are_the_bytes_that_land(payload: bytes) -> None:
    """VERBATIM ACROSS THE WHOLE BYTE SPACE, not just the examples below.

    Includes payloads containing CRLF, lone CR, NUL and invalid UTF-8 -- every
    sequence that a text-mode write or an encoding round trip would alter.
    """
    root = Path(tempfile.mkdtemp())

    written = author_verbatim(AuthoringRequest(path=Path("f.bin"), payload=payload), root=root)

    assert (root / "f.bin").read_bytes() == payload
    assert written.sha256 == hashlib.sha256(payload).hexdigest()
    assert written.bytes_written == len(payload)


# --- Examples. Grouped in classes; no executor sensitivity. -------------------


class TestAuthoringRequest:
    def test_a_request_carries_a_path_and_verbatim_payload(self) -> None:
        request = AuthoringRequest(path=Path("a/b.py"), payload=SOURCE)

        assert request.path == Path("a/b.py")
        assert request.payload == SOURCE

    def test_a_string_payload_is_refused_at_the_untyped_boundary(self) -> None:
        """BYTES, NOT STR, AND THE DISTINCTION IS LOAD-BEARING.

        MODEL_VALIDATE, NOT THE CONSTRUCTOR, AND THAT IS THE HONEST FORM OF THIS
        TEST. AuthoringRequest(payload="...") is a STATIC error that mypy
        rejects before the suite runs, so the test would assert something the
        type checker already forbids. The runtime risk is untyped input arriving
        as a mapping, which is what model_validate takes. Writing it this way
        also avoids a type: ignore, which would suppress real errors on that
        line forever.
        """
        with pytest.raises(ValidationError):
            AuthoringRequest.model_validate({"path": "a.py", "payload": "print('hello')"})

    def test_an_absolute_path_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            AuthoringRequest(path=Path("/etc/passwd"), payload=SOURCE)

    def test_a_path_escaping_the_repository_is_refused(self) -> None:
        """`..` IS THE TRAVERSAL THIS REFUSES.

        A writer that will write anywhere eventually overwrites something
        outside the tree it was pointed at.
        """
        with pytest.raises(ValidationError):
            AuthoringRequest(path=Path("../elsewhere/a.py"), payload=SOURCE)

    def test_an_empty_payload_is_refused(self) -> None:
        """A zero-byte write is the misfired heredoc, caught at the boundary."""
        with pytest.raises(ValidationError):
            AuthoringRequest(path=Path("a.py"), payload=b"")


class TestAuthorVerbatim:
    def test_the_bytes_on_disk_are_exactly_the_bytes_offered(self, tmp_path: Path) -> None:
        written = author_verbatim(
            AuthoringRequest(path=Path("pkg/mod.py"), payload=SOURCE), root=tmp_path
        )

        assert (tmp_path / "pkg/mod.py").read_bytes() == SOURCE
        assert written.bytes_written == len(SOURCE)

    def test_crlf_in_the_payload_survives_untranslated(self, tmp_path: Path) -> None:
        """Kept as an EXAMPLE despite the property above, because this is the
        specific corruption text mode causes and it deserves a named test."""
        payload = b"a\r\nb\r\n"

        author_verbatim(AuthoringRequest(path=Path("f.txt"), payload=payload), root=tmp_path)

        assert (tmp_path / "f.txt").read_bytes() == payload

    def test_missing_parent_directories_are_created(self, tmp_path: Path) -> None:
        """THE DEFICIENCY THAT RELOCATED THIS FILE, ASSERTED AS A REQUIREMENT."""
        author_verbatim(AuthoringRequest(path=Path("a/b/c/d.py"), payload=SOURCE), root=tmp_path)

        assert (tmp_path / "a/b/c/d.py").read_bytes() == SOURCE

    def test_an_existing_file_is_fully_replaced_rather_than_appended(self, tmp_path: Path) -> None:
        """FULL-FILE REWRITE. A partial edit is how two versions of one fact appear."""
        target = tmp_path / "f.py"
        target.write_bytes(b"# a much longer previous version\n" * 10)

        author_verbatim(AuthoringRequest(path=Path("f.py"), payload=SOURCE), root=tmp_path)

        assert target.read_bytes() == SOURCE

    def test_the_write_is_atomic_leaving_no_temporary_files_behind(self, tmp_path: Path) -> None:
        author_verbatim(AuthoringRequest(path=Path("f.py"), payload=SOURCE), root=tmp_path)

        assert [entry.name for entry in tmp_path.iterdir()] == ["f.py"]

    def test_the_original_survives_when_the_rename_fails(self, tmp_path: Path) -> None:
        """THE GUARANTEE THE REDIRECT CANNOT MAKE.

        `cat > f` truncates f before the payload arrives. Here the target is
        untouched until the payload is completely on disk, so a failure costs
        nothing -- and the temporary file is removed rather than left behind.
        """
        target = tmp_path / "f.py"
        target.write_bytes(b"# original\n")

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(Path, "replace", _raise_os_error)
            with pytest.raises(OSError):
                author_verbatim(AuthoringRequest(path=Path("f.py"), payload=SOURCE), root=tmp_path)

        assert target.read_bytes() == b"# original\n"
        assert [entry.name for entry in tmp_path.iterdir()] == ["f.py"]

    def test_the_report_is_frozen(self, tmp_path: Path) -> None:
        written = author_verbatim(
            AuthoringRequest(path=Path("f.py"), payload=SOURCE), root=tmp_path
        )

        with pytest.raises(ValidationError):
            written.bytes_written = 0  # type: ignore[misc]


class TestObserveWrittenFile:
    def test_a_header_naming_another_path_fails_and_names_the_check(self, tmp_path: Path) -> None:
        """Exactly the mistake a copied file makes, now impossible to state twice."""
        written = author_verbatim(
            AuthoringRequest(path=Path("pkg/other.py"), payload=payload_headed("pkg/mod.py")),
            root=tmp_path,
        )

        verdict = observe_written_file(written, root=tmp_path)

        assert verdict.verdict is GateVerdict.FAIL
        assert "path_header_comment" in verdict.reasons

    def test_a_digest_mismatch_fails(self, tmp_path: Path) -> None:
        """The caller states the digest it expected; the gate compares against disk."""
        written = author_verbatim(
            AuthoringRequest(path=Path("f.py"), payload=payload_headed("f.py")), root=tmp_path
        )

        verdict = observe_written_file(written, root=tmp_path, expected_sha256="0" * 64)

        assert verdict.verdict is GateVerdict.FAIL
        assert "content_digest" in verdict.reasons

    def test_a_stray_heredoc_delimiter_in_the_file_fails(self, tmp_path: Path) -> None:
        """THE FAILURE MODE OF THE MECHANISM BEING REPLACED, STILL CHECKED.

        A line reading EOF or PY means a delimiter was captured as content. The
        check stays because payloads still arrive through a terminal.
        """
        payload = b"# f.py\nprint('x')\nPY\n"
        written = author_verbatim(
            AuthoringRequest(path=Path("f.py"), payload=payload), root=tmp_path
        )

        verdict = observe_written_file(written, root=tmp_path)

        assert verdict.verdict is GateVerdict.FAIL
        assert "no_stray_delimiter" in verdict.reasons

    def test_a_file_deleted_after_authoring_is_unknown_rather_than_passing(
        self, tmp_path: Path
    ) -> None:
        """THE GATE TRUSTS NOTHING THE WRITER REPORTED.

        Handed a report for a file no longer there, it cannot conclude "pass" --
        and must not conclude "fail" either, because nothing was measured.
        """
        written = author_verbatim(
            AuthoringRequest(path=Path("f.py"), payload=payload_headed("f.py")), root=tmp_path
        )
        (tmp_path / "f.py").unlink()

        verdict = observe_written_file(written, root=tmp_path)

        assert verdict.verdict is GateVerdict.UNKNOWN

    def test_the_line_count_is_reported_as_context_and_decides_nothing(
        self, tmp_path: Path
    ) -> None:
        written = author_verbatim(
            AuthoringRequest(path=Path("f.py"), payload=payload_headed("f.py")), root=tmp_path
        )

        verdict = observe_written_file(written, root=tmp_path)
        line_count = next(check for check in verdict.checks if check.id == "line_count")

        assert line_count.verdict is CheckVerdict.INFORMATIONAL
        assert line_count.observed == 2

    def test_the_subject_and_gate_identify_what_was_judged(self, tmp_path: Path) -> None:
        written = author_verbatim(
            AuthoringRequest(path=Path("pkg/mod.py"), payload=payload_headed("pkg/mod.py")),
            root=tmp_path,
        )

        verdict = observe_written_file(written, root=tmp_path)

        assert verdict.subject == "pkg/mod.py"
        assert verdict.gate == "authored_file_integrity"


class TestWrittenFileContract:
    def test_bytes_written_may_not_be_negative(self) -> None:
        with pytest.raises(ValidationError):
            WrittenFile(path=Path("f.py"), bytes_written=-1, sha256="0" * 64)

    def test_the_digest_must_be_a_sha256_hex_string(self) -> None:
        """A SHORT OR NON-HEX DIGEST IS A BUG, NOT A DIGEST."""
        with pytest.raises(ValidationError):
            WrittenFile(path=Path("f.py"), bytes_written=1, sha256="abc")
