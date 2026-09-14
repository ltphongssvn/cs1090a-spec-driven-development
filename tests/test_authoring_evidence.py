# tests/test_authoring_evidence.py
# THE SURVIVORS THE FIRST TWO SUITES LEFT ALIVE, KILLED DELIBERATELY.
#
# WHY A SEPARATE FILE. tests/test_authoring.py asserts BEHAVIOUR: bytes land
# verbatim, the write is atomic, a bad header fails. Fifty-seven mutants
# survived it anyway, because behaviour is not the only thing this module
# publishes. It also publishes EVIDENCE -- the observed and expected values in
# every Check, and the message on every refusal -- and nothing asserted those.
#
# THREE CLASSES OF SURVIVOR, EACH NEEDING DIFFERENT TREATMENT:
#
#   EQUIVALENT. `decode("utf-8", ...)` mutated to `decode(...)` is the same
#   program, since utf-8 is already the default. No test can kill it. It was
#   removed from the source instead, which is the remedy the literature
#   prescribes: refactor away the construct that generates the mutant.
#
#   REACHED AND INFECTED BUT NOT PROPAGATED. `dir=target.parent` mutated to
#   `dir=None` passes every existing test on a machine whose temp directory
#   shares a device with the repository, and breaks the atomic rename where it
#   does not. The consequence had to be MADE observable, so the test asserts
#   WHERE the temporary file is created.
#
#   SIMPLY UNASSERTED. Refusal messages and Check literals.
#
# THE SPY'S SIGNATURE IS THE REAL ONE, AND GETTING IT WRONG COST A RUN. It was
# first written with `dir: str | None`, which typechecked -- mkstemp accepts
# `str | PathLike[str] | None`, so a narrower annotation is still assignable --
# and then recorded a Path while the assertion compared against a str. The
# lesson is not "annotate carefully"; it is that a test double narrowing its
# subject's types will diverge from it silently. The spy now takes what mkstemp
# takes, and the assertion compares Path to Path, which is also immune to
# trailing separators and platform rendering.

import hashlib
import tempfile
from os import PathLike
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from cs1090a_spec_driven_development.authoring import (
    DELIMITERS,
    GATE,
    HEX_DIGITS,
    NO_DELIMITER,
    SHA256_HEX_LENGTH,
    TEMPORARY_SUFFIX,
    AuthoringRequest,
    WrittenFile,
    author_verbatim,
    decode_lenient,
    digest_check,
    digest_of,
    first_line_of,
    header_check,
    is_sha256_hex,
    line_count_check,
    missing_file_check,
    observe_written_file,
    reject_absolute,
    reject_empty_payload,
    reject_traversal,
    stray_delimiter_check,
    temporary_prefix_for,
)
from cs1090a_spec_driven_development.contracts.verdict import CheckVerdict

SOURCE = b"# example.py\nprint('hello')\n"


def payload_headed(path: str) -> bytes:
    return f"# {path}\nprint('hello')\n".encode()


# --- Properties ---------------------------------------------------------------


@given(content=st.binary(max_size=200))
def test_decoding_never_raises_on_any_byte_sequence(content: bytes) -> None:
    """errors="replace" IS THE POINT, asserted over invalid UTF-8 too.

    A gate that raises on a malformed file reports nothing about it; a gate that
    decodes leniently reports a failed header check, which is useful.
    """
    assert isinstance(decode_lenient(content), str)


@given(digest=st.text(alphabet=HEX_DIGITS, max_size=80))
def test_only_a_sixty_four_character_hex_string_is_a_digest(digest: str) -> None:
    assert is_sha256_hex(digest) is (len(digest) == SHA256_HEX_LENGTH)


@given(payload=st.binary(min_size=1, max_size=200))
def test_the_temporary_file_is_always_created_beside_the_target(payload: bytes) -> None:
    """THE MUTANT THAT REACHED AND INFECTED BUT DID NOT PROPAGATE.

    dir=None sends the temporary file to the system temp directory. On this
    laptop that shares a device with the repository, so the rename still
    succeeds and every behavioural test passes. Where the temp directory is a
    separate filesystem the rename raises, and the atomicity guarantee is gone.

    ASSERTING THE DIRECTORY rather than the outcome is what makes the difference
    observable here instead of in production.

    mkdtemp RATHER THAN tmp_path: Hypothesis runs many examples inside one test
    call, and a function-scoped fixture would be shared across all of them.
    """
    root = Path(tempfile.mkdtemp())
    seen: list[Path] = []
    real_mkstemp = tempfile.mkstemp

    def recording_mkstemp(
        suffix: str | None = None,
        prefix: str | None = None,
        dir: str | PathLike[str] | None = None,
        text: bool = False,
    ) -> tuple[int, str]:
        assert dir is not None, "the temporary file must be placed deliberately"
        seen.append(Path(dir))
        return real_mkstemp(suffix=suffix, prefix=prefix, dir=dir, text=text)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(tempfile, "mkstemp", recording_mkstemp)
        author_verbatim(AuthoringRequest(path=Path("pkg/mod.py"), payload=payload), root=root)

    assert seen == [root / "pkg"]


# --- Refusal messages ----------------------------------------------------------


class TestRefusalMessages:
    def test_an_absolute_path_refusal_names_the_path(self) -> None:
        with pytest.raises(ValueError, match="/etc/passwd"):
            reject_absolute(Path("/etc/passwd"))

    def test_an_absolute_path_refusal_explains_the_rule(self) -> None:
        with pytest.raises(ValueError, match="relative to the repository root"):
            reject_absolute(Path("/etc/passwd"))

    def test_a_relative_path_is_returned_unchanged(self) -> None:
        path = Path("a/b.py")

        assert reject_absolute(path) is path

    def test_a_traversal_refusal_names_the_path(self) -> None:
        with pytest.raises(ValueError, match="elsewhere"):
            reject_traversal(Path("../elsewhere/a.py"))

    def test_a_traversal_refusal_explains_the_rule(self) -> None:
        with pytest.raises(ValueError, match="must not traverse"):
            reject_traversal(Path("../a.py"))

    def test_a_traversal_in_the_middle_of_a_path_is_refused(self) -> None:
        """`a/../../b` ESCAPES TOO. Checking only the first segment is not enough."""
        with pytest.raises(ValueError):
            reject_traversal(Path("a/../../b.py"))

    def test_a_path_without_traversal_is_returned_unchanged(self) -> None:
        path = Path("a/b.py")

        assert reject_traversal(path) is path

    def test_an_empty_payload_refusal_explains_the_rule(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            reject_empty_payload(b"")

    def test_a_nonempty_payload_is_returned_unchanged(self) -> None:
        assert reject_empty_payload(SOURCE) is SOURCE


class TestDigestRefusal:
    def test_the_refusal_shows_the_offending_digest(self) -> None:
        """THE VALUE IS IN THE MESSAGE, so the reader need not go looking.

        repr() IS USED IN THE SOURCE, which is why the quotes appear here: a
        digest of "" or "  " is otherwise invisible in a log line.
        """
        with pytest.raises(ValidationError, match="'abc'"):
            WrittenFile(path=Path("f.py"), bytes_written=1, sha256="abc")

    def test_the_refusal_states_the_required_shape(self) -> None:
        with pytest.raises(ValidationError, match="64 lowercase hex characters"):
            WrittenFile(path=Path("f.py"), bytes_written=1, sha256="abc")

    def test_an_uppercase_digest_is_refused(self) -> None:
        """hexdigest() IS LOWERCASE. Accepting both spellings would let one
        digest compare unequal to itself."""
        with pytest.raises(ValidationError):
            WrittenFile(path=Path("f.py"), bytes_written=1, sha256="A" * 64)

    def test_a_sixty_five_character_digest_is_refused(self) -> None:
        """THE LENGTH CHECK IS EQUALITY, not a minimum."""
        with pytest.raises(ValidationError):
            WrittenFile(path=Path("f.py"), bytes_written=1, sha256="a" * 65)

    def test_a_valid_digest_is_accepted(self) -> None:
        written = WrittenFile(path=Path("f.py"), bytes_written=1, sha256=digest_of(SOURCE))

        assert written.sha256 == digest_of(SOURCE)


# --- Evidence literals ---------------------------------------------------------


class TestCheckEvidence:
    def test_the_header_check_reports_both_the_observed_and_expected_line(self) -> None:
        check = header_check(payload_headed("pkg/mod.py"), Path("pkg/other.py"))

        assert check.id == "path_header_comment"
        assert check.verdict is CheckVerdict.FAIL
        assert check.observed == "# pkg/mod.py"
        assert check.expected == "# pkg/other.py"

    def test_a_matching_header_reports_the_same_value_in_both_fields(self) -> None:
        check = header_check(payload_headed("pkg/mod.py"), Path("pkg/mod.py"))

        assert check.verdict is CheckVerdict.PASS
        assert check.observed == check.expected == "# pkg/mod.py"

    def test_the_first_line_of_an_empty_file_is_empty(self) -> None:
        assert first_line_of(b"") == ""

    def test_a_file_with_no_newline_is_entirely_its_first_line(self) -> None:
        assert first_line_of(b"# a.py") == "# a.py"

    def test_a_carriage_return_is_not_a_line_boundary_for_the_header(self) -> None:
        r"""SPLITTING ON b"\n" ONLY.

        A CRLF file's header keeps its trailing carriage return, which correctly
        FAILS the check rather than silently passing.
        """
        assert first_line_of(b"# a.py\r\nx") == "# a.py\r"

    def test_the_delimiter_check_reports_the_offending_line(self) -> None:
        check = stray_delimiter_check(b"# f.py\nx\nPY\n")

        assert check.id == "no_stray_delimiter"
        assert check.verdict is CheckVerdict.FAIL
        assert check.observed == "PY"
        assert check.expected == NO_DELIMITER

    def test_a_clean_file_reports_the_sentinel_in_both_fields(self) -> None:
        check = stray_delimiter_check(SOURCE)

        assert check.verdict is CheckVerdict.PASS
        assert check.observed == check.expected == NO_DELIMITER

    def test_the_first_offending_line_is_reported_when_there_are_several(self) -> None:
        check = stray_delimiter_check(b"# f.py\nEOF\nPY\n")

        assert check.observed == "EOF"

    def test_an_indented_delimiter_is_still_a_leak(self) -> None:
        """THE STRIP IS ASSERTED. Without it this file passes."""
        check = stray_delimiter_check(b"# f.py\n   PY   \n")

        assert check.verdict is CheckVerdict.FAIL

    def test_a_delimiter_inside_a_longer_line_is_not_a_leak(self) -> None:
        """`print("PY")` IS CONTENT. Substring matching would fail real source."""
        check = stray_delimiter_check(b'# f.py\nprint("PY")\n')

        assert check.verdict is CheckVerdict.PASS

    def test_every_known_delimiter_is_detected(self) -> None:
        for delimiter in DELIMITERS:
            content = f"# f.py\n{delimiter}\n".encode()

            assert stray_delimiter_check(content).verdict is CheckVerdict.FAIL

    def test_the_digest_check_reports_both_digests(self) -> None:
        check = digest_check(SOURCE, "0" * 64)

        assert check.id == "content_digest"
        assert check.verdict is CheckVerdict.FAIL
        assert check.observed == digest_of(SOURCE)
        assert check.expected == "0" * 64

    def test_a_matching_digest_passes(self) -> None:
        check = digest_check(SOURCE, digest_of(SOURCE))

        assert check.verdict is CheckVerdict.PASS

    def test_the_line_count_check_counts_lines(self) -> None:
        check = line_count_check(b"a\nb\nc\n")

        assert check.id == "line_count"
        assert check.verdict is CheckVerdict.INFORMATIONAL
        assert check.observed == 3
        assert check.expected is None

    def test_an_empty_file_has_no_lines(self) -> None:
        assert line_count_check(b"").observed == 0

    def test_the_missing_file_check_states_absent_against_present(self) -> None:
        """THE LITERALS, ASSERTED. Blanking either survived every earlier run."""
        check = missing_file_check()

        assert check.id == "file_present"
        assert check.verdict is CheckVerdict.INFORMATIONAL
        assert check.observed == "absent"
        assert check.expected == "present"


# --- Naming and wiring ---------------------------------------------------------


class TestTemporaryNaming:
    def test_the_prefix_hides_the_file_and_keeps_the_target_name(self) -> None:
        """A DOT PREFIX, so a half-written file is not mistaken for source, and
        the target's name is retained so an abandoned temp file is traceable."""
        assert temporary_prefix_for("mod.py") == ".mod.py."

    def test_the_suffix_marks_the_file_as_this_module_s(self) -> None:
        assert TEMPORARY_SUFFIX == ".authoring"

    def test_the_gate_name_is_stable(self) -> None:
        """CONSUMERS KEY ON IT, so a rename is a breaking change and is asserted."""
        assert GATE == "authored_file_integrity"


class TestObservationWiring:
    def test_a_clean_file_produces_three_checks_without_a_digest_expectation(
        self, tmp_path: Path
    ) -> None:
        """THE OPTIONAL CHECK IS ABSENT, not present-and-passing."""
        written = author_verbatim(
            AuthoringRequest(path=Path("f.py"), payload=payload_headed("f.py")), root=tmp_path
        )

        verdict = observe_written_file(written, root=tmp_path)

        assert [check.id for check in verdict.checks] == [
            "path_header_comment",
            "no_stray_delimiter",
            "line_count",
        ]

    def test_supplying_a_digest_adds_exactly_one_check(self, tmp_path: Path) -> None:
        payload = payload_headed("f.py")
        written = author_verbatim(
            AuthoringRequest(path=Path("f.py"), payload=payload), root=tmp_path
        )

        verdict = observe_written_file(
            written, root=tmp_path, expected_sha256=hashlib.sha256(payload).hexdigest()
        )

        assert [check.id for check in verdict.checks][-1] == "content_digest"

    def test_a_missing_file_produces_only_the_presence_check(self, tmp_path: Path) -> None:
        written = author_verbatim(
            AuthoringRequest(path=Path("f.py"), payload=payload_headed("f.py")), root=tmp_path
        )
        (tmp_path / "f.py").unlink()

        verdict = observe_written_file(written, root=tmp_path)

        assert [check.id for check in verdict.checks] == ["file_present"]

    def test_a_directory_where_a_file_was_expected_is_not_a_file(self, tmp_path: Path) -> None:
        """is_file() RATHER THAN exists(). A directory exists and is not source."""
        written = author_verbatim(
            AuthoringRequest(path=Path("f.py"), payload=payload_headed("f.py")), root=tmp_path
        )
        (tmp_path / "f.py").unlink()
        (tmp_path / "f.py").mkdir()

        verdict = observe_written_file(written, root=tmp_path)

        assert [check.id for check in verdict.checks] == ["file_present"]

    def test_the_subject_is_rendered_with_posix_separators(self, tmp_path: Path) -> None:
        """THE SUBJECT IS EVIDENCE TOO, and must read the same on every platform."""
        written = author_verbatim(
            AuthoringRequest(path=Path("a/b/c.py"), payload=payload_headed("a/b/c.py")),
            root=tmp_path,
        )

        verdict = observe_written_file(written, root=tmp_path)

        assert verdict.subject == "a/b/c.py"
