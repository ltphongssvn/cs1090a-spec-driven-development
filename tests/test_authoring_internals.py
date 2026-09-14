# tests/test_authoring_internals.py
# THE DECISIONS THAT WERE CORRECT AND UNOBSERVABLE.
#
# WHY THIS FILE EXISTS. Seven mutants survived inside author_verbatim, all of
# one shape: prefix=None, suffix=None, the argument removed, missing_ok flipped.
# None of them could be killed by any test of author_verbatim, because the
# temporary file is RENAMED AWAY on success. Its name existed for microseconds
# between mkstemp and replace, and nothing outside the function could ever see
# it. The code was right and untestable at the same time.
#
# THE REMEDY WAS NOT A CLEVERER TEST. Spying on mkstemp to capture the name
# would assert that the function calls the function it calls -- a change-detector
# test that breaks on any refactor and proves nothing about behaviour. The
# naming decision moved into temporary_name_parts, which RETURNS the values, and
# cleanup moved into discard_temporary, which RETURNS whether it removed
# anything. Both are now ordinary functions with ordinary assertions.
#
# THE GENERAL RULE THIS ESTABLISHES: when a mutant cannot be killed because the
# decision is invisible from outside, extract the decision. A private choice
# nothing can observe is a choice nothing can protect.

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cs1090a_spec_driven_development.authoring import (
    TEMPORARY_SUFFIX,
    AuthoringRequest,
    author_verbatim,
    discard_temporary,
    temporary_name_parts,
    temporary_prefix_for,
)

SOURCE = b"# f.py\nprint('hello')\n"

names = st.text(alphabet=st.characters(whitelist_categories=("Ll", "Nd")), min_size=1, max_size=12)


# --- Properties ---------------------------------------------------------------


@given(name=names)
def test_the_temporary_name_always_hides_the_file(name: str) -> None:
    """A LEADING DOT, so a half-written file is not mistaken for source by a
    glob, an editor, or a reviewer reading a directory listing."""
    assert temporary_prefix_for(name).startswith(".")


@given(name=names)
def test_the_temporary_name_always_carries_the_target_name(name: str) -> None:
    """SO AN ABANDONED TEMPORARY FILE IS TRACEABLE.

    A generic prefix would leave a crashed run's debris with no indication of
    which file it belonged to.
    """
    assert name in temporary_prefix_for(name)


# --- The extracted decisions ---------------------------------------------------


class TestTemporaryNameParts:
    def test_the_directory_is_the_target_s_own(self) -> None:
        """THE ATOMICITY GUARANTEE, ASSERTED.

        A rename across filesystems is not atomic. Placing the temporary file
        anywhere but beside the target breaks the guarantee on any machine where
        the temp directory is a separate device -- and passes on one where it is
        not, which is why this needed an assertion rather than a comment.
        """
        directory, _, _ = temporary_name_parts(Path("/repo/pkg/mod.py"))

        assert directory == Path("/repo/pkg")

    def test_the_prefix_is_derived_from_the_target_file_name(self) -> None:
        _, prefix, _ = temporary_name_parts(Path("/repo/pkg/mod.py"))

        assert prefix == ".mod.py."

    def test_the_prefix_uses_the_file_name_and_not_the_whole_path(self) -> None:
        """A PATH IN A FILENAME would contain separators and fail to create."""
        _, prefix, _ = temporary_name_parts(Path("/repo/pkg/mod.py"))

        assert "/" not in prefix

    def test_the_suffix_marks_the_file_as_this_module_s(self) -> None:
        _, _, suffix = temporary_name_parts(Path("/repo/mod.py"))

        assert suffix == TEMPORARY_SUFFIX

    def test_none_of_the_three_parts_is_empty(self) -> None:
        """EACH MUTATED TO None INDEPENDENTLY and survived; each is asserted."""
        directory, prefix, suffix = temporary_name_parts(Path("/repo/mod.py"))

        assert str(directory)
        assert prefix
        assert suffix

    def test_a_file_at_the_root_uses_the_root_as_its_directory(self) -> None:
        directory, _, _ = temporary_name_parts(Path("/mod.py"))

        assert directory == Path("/")


class TestDiscardTemporary:
    def test_an_existing_file_is_removed_and_reported(self, tmp_path: Path) -> None:
        temporary = tmp_path / ".f.py.authoring"
        temporary.write_bytes(b"partial")

        removed = discard_temporary(temporary)

        assert removed is True
        assert not temporary.exists()

    def test_an_absent_file_is_reported_rather_than_raised_over(self, tmp_path: Path) -> None:
        """THE missing_ok MUTANTS.

        missing_ok=True silently tolerated a state the code never reaches, so
        both True and False survived. Returning the outcome makes the branch
        real: cleanup after a failure that occurred BEFORE mkstemp succeeded has
        nothing to remove, and that must not raise a second exception on top of
        the first.
        """
        removed = discard_temporary(tmp_path / "never-created")

        assert removed is False

    def test_removing_twice_is_safe(self, tmp_path: Path) -> None:
        temporary = tmp_path / ".f.py.authoring"
        temporary.write_bytes(b"partial")

        assert discard_temporary(temporary) is True
        assert discard_temporary(temporary) is False


class TestTemporaryFilesInPractice:
    def test_a_successful_write_leaves_only_the_target(self, tmp_path: Path) -> None:
        author_verbatim(AuthoringRequest(path=Path("f.py"), payload=SOURCE), root=tmp_path)

        assert [entry.name for entry in tmp_path.iterdir()] == ["f.py"]

    def test_a_failed_rename_leaves_only_the_previous_version(self, tmp_path: Path) -> None:
        """THE TEMPORARY FILE IS CLEANED UP, asserted through the directory
        listing rather than by spying on the call."""
        target = tmp_path / "f.py"
        target.write_bytes(b"# original\n")

        def refuse(*_args: object, **_kwargs: object) -> None:
            raise OSError("rename refused")

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(Path, "replace", refuse)
            with pytest.raises(OSError):
                author_verbatim(AuthoringRequest(path=Path("f.py"), payload=SOURCE), root=tmp_path)

        assert [entry.name for entry in tmp_path.iterdir()] == ["f.py"]
        assert target.read_bytes() == b"# original\n"

    def test_a_failed_write_into_a_new_directory_leaves_it_empty(self, tmp_path: Path) -> None:
        """NO DEBRIS WHERE THERE WAS NO PREVIOUS VERSION EITHER."""

        def refuse(*_args: object, **_kwargs: object) -> None:
            raise OSError("rename refused")

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(Path, "replace", refuse)
            with pytest.raises(OSError):
                author_verbatim(
                    AuthoringRequest(path=Path("pkg/f.py"), payload=SOURCE), root=tmp_path
                )

        assert list((tmp_path / "pkg").iterdir()) == []
