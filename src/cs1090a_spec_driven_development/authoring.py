# src/cs1090a_spec_driven_development/authoring.py
# AUTHORING AS CODE. The Python-native replacement for `cat > path << 'EOF'`.
#
# --- WHY THE SHELL STOPS BEING THE WRITER -------------------------------------
#
#   1. THE SHELL CORRUPTS MULTI-LINE PAYLOADS. Editor and agent tooling
#      normalises a command by collapsing newlines to spaces, which turns a
#      heredoc into one line and writes a broken file with no error. 2026
#      tooling now hard-blocks heredoc file writes for exactly this reason,
#      while still permitting heredocs consumed by an INTERPRETER -- the
#      distinction this module implements: the shell may carry the bytes, but
#      Python writes them.
#   2. THE REDIRECT TRUNCATES BEFORE THE PAYLOAD ARRIVES. `cat > f` empties f
#      the moment the command is parsed, so an interrupted write destroys the
#      previous version and leaves nothing in its place.
#   3. THE SHELL CANNOT CREATE PARENT DIRECTORIES.
#   4. TEXT MODE TRANSFORMS. Only write_bytes is verbatim.
#
# AUTHORING IS NOT A GATE. author_verbatim writes and reports what it did;
# observe_written_file reads the file BACK FROM DISK and judges it.
#
# --- EQUIVALENT MUTANTS, REMOVED AT THE SOURCE --------------------------------
#
# An equivalent mutant is syntactically different and semantically identical, so
# NO test can kill it. The remedy is to refactor away the construct that
# generates it. Leaving one is not neutral: it is a false negative that depresses
# the score and must be re-triaged by hand every run, and since equivalence is
# undecidable, a survivor is otherwise ambiguous between "equivalent" and
# "stubborn but killable".
#
#   decode("utf-8", ...) -> decode(...)   utf-8 is already the default.
#   split(NEWLINE, 1)[0] -> split(NEWLINE)[0]   maxsplit is unobservable once
#   [0] is taken; partition() says what is meant and has no number to mutate.
#
# --- WHY THE TEMPORARY FILE'S NAME IS BUILT BY A NAMED FUNCTION ---------------
#
# SEVEN MUTANTS SURVIVED IN THIS FUNCTION, all of the same shape: prefix=None,
# suffix=None, the argument deleted entirely, missing_ok flipped. They survived
# because the temporary file is RENAMED AWAY on success, so its name never
# reaches an assertion -- the code was correct and untestable at the same time.
#
# THE FIX IS STRUCTURAL, NOT ANOTHER TEST. The naming decision moves into
# temporary_name_parts, which returns the values and can be asserted directly;
# author_verbatim then passes them through. A decision that cannot be observed
# from outside the function it lives in belongs in a function of its own.
#
# THE CLEANUP IS NOW EXPLICIT for the same reason. `missing_ok=True` silently
# tolerated a state this code never reaches, so both mutations of the flag were
# unobservable. Checking existence first makes the intent -- remove the
# temporary file IF WE CREATED ONE -- a branch a test can take.
#
# THE LOGIC LIVES IN PLAIN UNDECORATED FUNCTIONS because mutmut 3 skips
# decorated ones.

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cs1090a_spec_driven_development.contracts.verdict import (
    Check,
    CheckVerdict,
    Verdict,
)

SHA256_HEX_LENGTH = 64
HEX_DIGITS = "0123456789abcdef"
GATE = "authored_file_integrity"
NO_DELIMITER = "none"
TEMPORARY_SUFFIX = ".authoring"
NEWLINE = b"\n"

# LINES THAT MEAN A DELIMITER WAS CAPTURED AS CONTENT. Payloads still arrive
# through a terminal, so the failure mode of the mechanism being replaced is
# still worth checking for.
DELIMITERS = frozenset({"EOF", "PY", "TOML", "JSON", "SH", "YAML"})


def decode_lenient(content: bytes) -> str:
    """Decode for INSPECTION, never for writing.

    errors="replace" RATHER THAN A RAISE. A file whose bytes are not valid UTF-8
    has failed the header check, and reporting that as a failed check is more
    useful than an exception that takes the whole verdict with it.
    """
    return content.decode(errors="replace")


def reject_absolute(path: Path) -> Path:
    """Authoring is scoped to a repository, so the target is relative."""
    if path.is_absolute():
        raise ValueError(f"path must be relative to the repository root: {path}")
    return path


def reject_traversal(path: Path) -> Path:
    """`..` IS THE TRAVERSAL THIS REFUSES."""
    if ".." in path.parts:
        raise ValueError(f"path must not traverse outside the repository: {path}")
    return path


def reject_empty_payload(payload: bytes) -> bytes:
    """A zero-byte write is the misfired heredoc, caught at the boundary."""
    if not payload:
        raise ValueError("payload must not be empty")
    return payload


class AuthoringRequest(BaseModel):
    """What to write, and where.

    PAYLOAD IS bytes, NOT str, AND THE DISTINCTION IS LOAD-BEARING. Text mode
    applies an encoding and newline translation, so the file could differ from
    what was offered.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    path: Path
    payload: bytes

    @model_validator(mode="after")
    def _validate(self) -> Self:
        return validate_authoring_request(self)


def validate_authoring_request[RequestT: AuthoringRequest](request: RequestT) -> RequestT:
    reject_absolute(request.path)
    reject_traversal(request.path)
    reject_empty_payload(request.payload)
    return request


def expected_header_for(path: Path) -> str:
    """The first line a file at this path must carry.

    THE ONE PLACE THE HEADER CONTRACT IS STATED, so a header naming some other
    file is impossible to assert. as_posix() because path rendering is
    OS-dependent and a header is source read on every platform.
    """
    return f"# {path.as_posix()}"


def is_sha256_hex(value: str) -> bool:
    """A short, long, or non-hex digest is a bug rather than a digest.

    LOWERCASE ONLY, because hexdigest() produces lowercase.
    """
    if len(value) != SHA256_HEX_LENGTH:
        return False
    return all(character in HEX_DIGITS for character in value)


class WrittenFile(BaseModel):
    """What authoring actually did, as facts rather than a claim of success."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: Path
    bytes_written: int = Field(ge=0)
    sha256: str

    @model_validator(mode="after")
    def _validate(self) -> Self:
        return validate_written_file(self)


def validate_written_file[WrittenT: WrittenFile](written: WrittenT) -> WrittenT:
    if not is_sha256_hex(written.sha256):
        raise ValueError(f"sha256 must be 64 lowercase hex characters: {written.sha256!r}")
    return written


def digest_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def temporary_prefix_for(name: str) -> str:
    """A hidden sibling name, so a half-written file is not mistaken for source."""
    return f".{name}."


def temporary_name_parts(target: Path) -> tuple[Path, str, str]:
    """Where the temporary file goes, and what it is called.

    RETURNED RATHER THAN PASSED INLINE, so the decision is observable. Inline,
    the name existed only between mkstemp and the rename that destroyed it, and
    four separate mutations of it survived every test.

    THE DIRECTORY IS THE TARGET'S OWN, which is the atomicity guarantee: a
    rename ACROSS filesystems is not atomic. It raises, and any fallback becomes
    copy-then-delete, reintroducing the partial file this module prevents.
    """
    return target.parent, temporary_prefix_for(target.name), TEMPORARY_SUFFIX


def discard_temporary(temporary: Path) -> bool:
    """Remove a temporary file, reporting whether there was one to remove.

    EXPLICIT RATHER THAN missing_ok=True. The flag silently tolerated a state
    this code never reaches, so both of its mutations were unobservable.
    Returning the outcome makes the branch assertable.
    """
    if not temporary.exists():
        return False
    temporary.unlink()
    return True


def author_verbatim(request: AuthoringRequest, *, root: Path) -> WrittenFile:
    """Write the payload atomically, then report what landed on disk.

    THE SEQUENCE IS THE GUARANTEE: the payload is written completely to a
    sibling temporary file, flushed and fsynced, and only then renamed over the
    target. A rename within one filesystem is atomic, so a reader sees either
    the old file or the new one -- never a half-written one -- and a failure at
    any earlier point leaves the previous version untouched.
    """
    target = root / request.path
    target.parent.mkdir(parents=True, exist_ok=True)

    directory, prefix, suffix = temporary_name_parts(target)
    handle, temporary_name = tempfile.mkstemp(dir=directory, prefix=prefix, suffix=suffix)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(request.payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
    except BaseException:
        discard_temporary(temporary)
        raise

    # READ BACK, RATHER THAN DIGESTING THE BUFFER. Hashing the input would
    # report a digest for bytes that may never have reached the disk, which is
    # the writer vouching for itself.
    landed = target.read_bytes()
    return WrittenFile(path=request.path, bytes_written=len(landed), sha256=digest_of(landed))


def first_line_of(content: bytes) -> str:
    """Everything before the first newline.

    partition RATHER THAN split(NEWLINE, 1): both are correct, but partition
    carries no maxsplit argument to mutate. NOT splitlines(), which also breaks
    on form feed, vertical tab and the Unicode line separators -- all legal
    inside a Python comment and none of which end the header line.
    """
    head, _, _ = content.partition(NEWLINE)
    return decode_lenient(head)


def header_check(content: bytes, path: Path) -> Check:
    """The first line must name the file's own path.

    A file whose header names a path it no longer occupies is worse than one
    with no header: it is confidently wrong.
    """
    expected = expected_header_for(path)
    observed = first_line_of(content)
    return Check(
        id="path_header_comment",
        verdict=CheckVerdict.PASS if observed == expected else CheckVerdict.FAIL,
        observed=observed,
        expected=expected,
    )


def stray_delimiter_check(content: bytes) -> Check:
    """A line consisting only of a heredoc delimiter means transport leaked.

    THE LINE IS STRIPPED BEFORE COMPARISON: a delimiter that arrived with
    surrounding whitespace is the same leak.
    """
    lines = decode_lenient(content).splitlines()
    found = [line for line in lines if line.strip() in DELIMITERS]
    return Check(
        id="no_stray_delimiter",
        verdict=CheckVerdict.FAIL if found else CheckVerdict.PASS,
        observed=found[0] if found else NO_DELIMITER,
        expected=NO_DELIMITER,
    )


def digest_check(content: bytes, expected_sha256: str) -> Check:
    observed = digest_of(content)
    return Check(
        id="content_digest",
        verdict=CheckVerdict.PASS if observed == expected_sha256 else CheckVerdict.FAIL,
        observed=observed,
        expected=expected_sha256,
    )


def line_count_check(content: bytes) -> Check:
    """Context, not a condition. Nobody chose a bound for it, so it decides nothing."""
    return Check(
        id="line_count",
        verdict=CheckVerdict.INFORMATIONAL,
        observed=len(decode_lenient(content).splitlines()),
    )


def missing_file_check() -> Check:
    """Informational ON PURPOSE, so the gate resolves to UNKNOWN.

    Handed a report for a file that is no longer there, the gate cannot conclude
    "pass" -- and must not conclude "fail" either, because nothing was measured.
    """
    return Check(
        id="file_present",
        verdict=CheckVerdict.INFORMATIONAL,
        observed="absent",
        expected="present",
    )


def observe_written_file(
    written: WrittenFile,
    *,
    root: Path,
    expected_sha256: str | None = None,
) -> Verdict:
    """Read the file back from disk and judge it.

    NOTHING THE WRITER REPORTED IS TRUSTED HERE. The content is re-read, the
    digest re-computed, and the verdict derived from the checks by the contract.
    """
    target = root / written.path
    if not target.is_file():
        return Verdict(gate=GATE, subject=written.path.as_posix(), checks=[missing_file_check()])

    content = target.read_bytes()
    checks = [
        header_check(content, written.path),
        stray_delimiter_check(content),
        line_count_check(content),
    ]
    if expected_sha256 is not None:
        checks.append(digest_check(content, expected_sha256))

    return Verdict(gate=GATE, subject=written.path.as_posix(), checks=checks)
