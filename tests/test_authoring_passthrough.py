# tests/test_authoring_passthrough.py
# THE LAST UNOBSERVABLE DECISIONS IN author_verbatim.
#
# EXTRACTING temporary_name_parts WAS NECESSARY AND NOT SUFFICIENT. The function
# is now tested directly, but four mutants still survived:
#
#   mkstemp(dir=directory, prefix=None,   suffix=suffix)
#   mkstemp(dir=directory, prefix=prefix, suffix=None)
#   mkstemp(dir=directory,               suffix=suffix)
#   mkstemp(dir=directory, prefix=prefix)
#
# All four discard a value temporary_name_parts computed correctly. Testing the
# producer does not test that the caller USES what it produced -- the wiring
# between them is its own behaviour, and it was unasserted.
#
# WHY A SPY IS THE RIGHT TOOL HERE AND WAS THE WRONG TOOL BEFORE. Earlier, a spy
# would have asserted that author_verbatim calls mkstemp with values computed
# inline -- a change-detector test restating the implementation. Now the
# expected values come from temporary_name_parts, which is independently tested
# against the statute of this module. The assertion is "the caller passes
# through what the namer decided", which survives any refactor that keeps that
# true.
#
# THE FILE IS OTHERWISE UNOBSERVABLE BY CONSTRUCTION: the temporary file is
# renamed away on success, so its name never reaches disk under that name for
# any test to find.

import tempfile
from os import PathLike
from pathlib import Path

import pytest

from cs1090a_spec_driven_development.authoring import (
    AuthoringRequest,
    author_verbatim,
    temporary_name_parts,
)

SOURCE = b"# pkg/mod.py\nprint('hello')\n"


class RecordedCall:
    """What author_verbatim actually asked tempfile for."""

    def __init__(self) -> None:
        self.directory: Path | None = None
        self.prefix: str | None = None
        self.suffix: str | None = None


@pytest.fixture
def recorded_mkstemp(monkeypatch: pytest.MonkeyPatch) -> RecordedCall:
    """Record the arguments, then delegate to the real implementation.

    DELEGATING RATHER THAN STUBBING. A stub returning a fake handle would make
    every assertion below true of a function that never wrote anything; the real
    call keeps the rest of author_verbatim honest.
    """
    recorded = RecordedCall()
    real_mkstemp = tempfile.mkstemp

    def recording(
        suffix: str | None = None,
        prefix: str | None = None,
        dir: str | PathLike[str] | None = None,
        text: bool = False,
    ) -> tuple[int, str]:
        recorded.directory = Path(dir) if dir is not None else None
        recorded.prefix = prefix
        recorded.suffix = suffix
        return real_mkstemp(suffix=suffix, prefix=prefix, dir=dir, text=text)

    monkeypatch.setattr(tempfile, "mkstemp", recording)
    return recorded


class TestNamePartsAreUsed:
    def test_the_directory_prefix_and_suffix_all_reach_tempfile(
        self, tmp_path: Path, recorded_mkstemp: RecordedCall
    ) -> None:
        """THE FOUR SURVIVING MUTANTS, KILLED TOGETHER.

        Each of them dropped one of these three values. The expected values are
        taken from temporary_name_parts rather than restated, so this asserts
        the WIRING and not a second copy of the naming rule.
        """
        target = tmp_path / "pkg/mod.py"
        expected_directory, expected_prefix, expected_suffix = temporary_name_parts(target)

        author_verbatim(AuthoringRequest(path=Path("pkg/mod.py"), payload=SOURCE), root=tmp_path)

        assert recorded_mkstemp.directory == expected_directory
        assert recorded_mkstemp.prefix == expected_prefix
        assert recorded_mkstemp.suffix == expected_suffix

    def test_no_argument_is_dropped(self, tmp_path: Path, recorded_mkstemp: RecordedCall) -> None:
        """OMITTING AN ARGUMENT AND PASSING None ARE DIFFERENT MUTATIONS with
        the same effect, and both are covered by asserting each value present."""
        author_verbatim(AuthoringRequest(path=Path("f.py"), payload=SOURCE), root=tmp_path)

        assert recorded_mkstemp.directory is not None
        assert recorded_mkstemp.prefix is not None
        assert recorded_mkstemp.suffix is not None

    def test_the_recorded_prefix_names_the_target_file(
        self, tmp_path: Path, recorded_mkstemp: RecordedCall
    ) -> None:
        author_verbatim(AuthoringRequest(path=Path("pkg/mod.py"), payload=SOURCE), root=tmp_path)

        assert recorded_mkstemp.prefix == ".mod.py."

    def test_the_recorded_directory_is_the_target_s_parent_not_the_root(
        self, tmp_path: Path, recorded_mkstemp: RecordedCall
    ) -> None:
        """A NESTED TARGET DISTINGUISHES THE TWO. With a top-level file, parent
        and root are the same directory and the assertion proves nothing."""
        author_verbatim(
            AuthoringRequest(path=Path("a/b/mod.py"), payload=b"# a/b/mod.py\nx\n"),
            root=tmp_path,
        )

        assert recorded_mkstemp.directory == tmp_path / "a/b"
