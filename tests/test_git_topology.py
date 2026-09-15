# tests/test_git_topology.py
# WHERE THE REPOSITORY IS, ASKED OF GIT AND VALIDATED AS A PATH THAT EXISTS.
#
# --- THE BUG THIS REPLACES ----------------------------------------------------
#
# A test located the repository with Path(__file__).resolve().parent.parent. Under
# mutmut that resolves to ./mutants -- a scratch copy holding Python source and
# no policies/ -- so every policy test failed on a refusal that was itself
# correct. The refusal was right; the locator was naive.
#
# THE SAME DEFECT IS DOCUMENTED ELSEWHERE IN 2026, with a worse outcome: a tool
# anchored to `Path(__file__).resolve().parents[2]` and invoked from a WORKTREE
# that lacked its own copy silently resolved to the MAIN CLONE's root, so it
# read the wrong branch and wrote into an unrelated workflow. This repository
# uses worktrees for every feature branch, so that is our exact exposure.
#
# PYTEST'S OWN config.rootpath DOES NOT HELP: rootdir derives from the
# configfile, and mutmut's scratch tree carries its own pyproject.toml, so it
# resolves to ./mutants too -- the same wrong answer arrived at more
# respectably.
#
# --- WHY ONE SUBPROCESS, NOT THREE --------------------------------------------
#
# git answers all three questions in a single invocation:
#
#   git rev-parse --git-dir --git-common-dir --show-toplevel
#
# A 2026 benchmark of exactly this change measured a median of 33.2 ms for three
# sequential calls against 11.5 ms combined -- 65% faster -- and this runs on
# every gate invocation.
#
# --- WHY NO MANUAL TRAVERSAL --------------------------------------------------
#
# `git -C <somewhere> rev-parse` already walks up from wherever it is pointed.
# Adding `../../..` to the path first reintroduces precisely the brittleness the
# git call removes: it breaks the day the caller moves.
#
# --- WHY DirectoryPath RATHER THAN Path ---------------------------------------
#
# pydantic's DirectoryPath is "like Path, but the path must exist and be a
# directory". A gate that accepts a root which is not there fails later, deeper,
# and with a worse message -- and this repository has twice watched a gate
# report success over something it never examined.

import re
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from cs1090a_spec_driven_development.git_topology import (
    DISCOVERY_TIMEOUT_SECONDS,
    ROOT_VARIABLE,
    RepositoryLayout,
    discover_layout,
    repository_root,
)


def init_repository(root: Path) -> Path:
    """A real repository, because a fake one proves nothing about git.

    THE DIRECTORY IS CREATED FIRST. `git init` with cwd= a path that does not
    exist fails inside fork, reporting a missing directory rather than anything
    about git -- a confusing failure that belongs to the helper, not the module
    under test.
    """
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True, timeout=30)
    (root / "README.md").write_text("# sample\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, timeout=30)
    subprocess.run(
        ["git", "-c", "user.email=t@e", "-c", "user.name=t", "commit", "-qm", "first"],
        cwd=root,
        check=True,
        timeout=30,
    )
    return root


class TestDiscovery:
    def test_the_toplevel_is_the_repository_root(self, tmp_path: Path) -> None:
        init_repository(tmp_path)

        layout = discover_layout(tmp_path)

        assert layout.toplevel == tmp_path.resolve()

    def test_discovery_works_from_a_subdirectory(self, tmp_path: Path) -> None:
        """THE WHOLE POINT. git walks up; a caller need not know how deep it is."""
        init_repository(tmp_path)
        nested = tmp_path / "a/b/c"
        nested.mkdir(parents=True)

        assert discover_layout(nested).toplevel == tmp_path.resolve()

    def test_the_git_directory_is_reported(self, tmp_path: Path) -> None:
        init_repository(tmp_path)

        assert discover_layout(tmp_path).git_dir == (tmp_path / ".git").resolve()

    def test_the_common_directory_equals_the_git_directory_in_a_plain_clone(
        self, tmp_path: Path
    ) -> None:
        """THE TWO DIVERGE ONLY IN A LINKED WORKTREE, which is what makes the
        pair worth reporting rather than just the one."""
        init_repository(tmp_path)
        layout = discover_layout(tmp_path)

        assert layout.git_dir == layout.common_dir
        assert layout.is_linked_worktree is False

    def test_paths_are_absolute(self, tmp_path: Path) -> None:
        """git MAY ANSWER RELATIVELY -- `--git-dir` returns ".git" when run at
        the root. A relative answer resolved against the wrong cwd later is the
        class of bug this module exists to remove.
        """
        init_repository(tmp_path)
        layout = discover_layout(tmp_path)

        assert layout.toplevel.is_absolute()
        assert layout.git_dir.is_absolute()
        assert layout.common_dir.is_absolute()

    def test_one_subprocess_answers_every_question(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MEASURED ELSEWHERE AT 65% FASTER than three sequential calls, and
        this runs on every gate invocation. Asserted by counting the calls
        rather than trusting the implementation to have stayed combined.
        """
        init_repository(tmp_path)
        calls: list[list[str]] = []
        real = subprocess.run

        def counting(argv, *args, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(list(argv))
            return real(argv, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", counting)
        discover_layout(tmp_path)

        assert len(calls) == 1


class TestLinkedWorktrees:
    def test_a_linked_worktree_reports_its_own_toplevel(self, tmp_path: Path) -> None:
        """THE FAILURE MODE FROM THE HEADER, ASSERTED.

        A worktree invocation must anchor to the WORKTREE, not the main clone.
        The documented 2026 defect had a tool silently read the wrong branch
        because it anchored to a script's location instead.
        """
        main = init_repository(tmp_path / "main")
        linked = tmp_path / "linked"
        subprocess.run(
            ["git", "worktree", "add", "-q", str(linked), "-b", "feature/x"],
            cwd=main,
            check=True,
            timeout=30,
        )

        assert discover_layout(linked).toplevel == linked.resolve()

    def test_a_linked_worktree_shares_the_common_directory(self, tmp_path: Path) -> None:
        """THE SHARED OBJECT STORE. A worktree's own git dir is private; the
        common dir is where refs and objects actually live, which is why both
        are reported.
        """
        main = init_repository(tmp_path / "main")
        linked = tmp_path / "linked"
        subprocess.run(
            ["git", "worktree", "add", "-q", str(linked), "-b", "feature/x"],
            cwd=main,
            check=True,
            timeout=30,
        )

        layout = discover_layout(linked)

        assert layout.common_dir == (main / ".git").resolve()
        assert layout.git_dir != layout.common_dir
        assert layout.is_linked_worktree is True


class TestRefusals:
    def test_a_directory_outside_any_repository_raises(self, tmp_path: Path) -> None:
        """AND SAYS SO. A gate that silently guesses a root is a gate that
        examines the wrong tree and reports confidently about it.
        """
        with pytest.raises(FileNotFoundError, match="not inside a git repository"):
            discover_layout(tmp_path)

    def test_a_missing_directory_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            discover_layout(tmp_path / "absent")

    def test_a_layout_pointing_at_a_missing_directory_is_rejected(self, tmp_path: Path) -> None:
        """DirectoryPath VALIDATES EXISTENCE, so a root that is not there fails
        at construction rather than at first use.
        """
        with pytest.raises(ValidationError):
            RepositoryLayout(
                toplevel=tmp_path / "absent",
                git_dir=tmp_path,
                common_dir=tmp_path,
            )

    def test_a_layout_pointing_at_a_file_is_rejected(self, tmp_path: Path) -> None:
        """A FILE IS NOT A DIRECTORY, and in a linked worktree `.git` IS a file
        -- so the distinction is a real one here, not a hypothetical.
        """
        target = tmp_path / "plain.txt"
        target.write_text("x")

        with pytest.raises(ValidationError):
            RepositoryLayout(toplevel=target, git_dir=tmp_path, common_dir=tmp_path)

    def test_the_layout_is_frozen(self, tmp_path: Path) -> None:
        init_repository(tmp_path)
        layout = discover_layout(tmp_path)

        with pytest.raises(ValidationError):
            layout.toplevel = tmp_path  # type: ignore[misc]


class TestRepositoryRoot:
    def test_the_root_is_the_toplevel(self, tmp_path: Path) -> None:
        init_repository(tmp_path)

        assert repository_root(tmp_path) == tmp_path.resolve()

    def test_an_explicit_override_wins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """EXPLICIT OPERATOR INTENT OUTRANKS DISCOVERY. CI sometimes stages a
        tree deliberately, and a tool that overrules the operator is a tool the
        operator works around.
        """
        init_repository(tmp_path)
        elsewhere = tmp_path / "staged"
        elsewhere.mkdir()
        monkeypatch.setenv(ROOT_VARIABLE, str(elsewhere))

        assert repository_root(tmp_path) == elsewhere.resolve()

    def test_an_override_naming_a_missing_directory_is_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A TYPO IN AN ENVIRONMENT VARIABLE must fail loudly rather than send
        the gate to a directory nobody meant.
        """
        init_repository(tmp_path)
        monkeypatch.setenv(ROOT_VARIABLE, str(tmp_path / "absent"))

        with pytest.raises(ValidationError):
            repository_root(tmp_path)

    def test_an_empty_override_is_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AN UNSET VARIABLE IN CI COMMONLY ARRIVES AS THE EMPTY STRING, and
        treating that as a path points the gate at the current directory.
        """
        init_repository(tmp_path)
        monkeypatch.setenv(ROOT_VARIABLE, "")

        assert repository_root(tmp_path) == tmp_path.resolve()

    def test_the_variable_is_named_as_documented(self) -> None:
        """A CONSTANT NOBODY ASSERTS CAN BE RENAMED WITHOUT ANY TEST OBJECTING,
        and every operator's override would then be silently ignored.
        """
        assert ROOT_VARIABLE == "CS1090A_GATE_ROOT"

    def test_the_default_start_is_the_working_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """THE CALLER'S cwd, NOT A SCRIPT'S LOCATION. That distinction is the
        entire fix: a worktree invocation must anchor to the worktree.
        """
        init_repository(tmp_path)
        monkeypatch.delenv(ROOT_VARIABLE, raising=False)
        monkeypatch.chdir(tmp_path)

        assert repository_root() == tmp_path.resolve()


class TestTheSubprocessContract:
    """The arguments that make the call safe, asserted rather than assumed."""

    def recorded_call(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[list[str], dict[str, object]]:
        """Run a real discovery while capturing how the subprocess was invoked.

        DELEGATING TO THE REAL CALL rather than stubbing it: a stub would make
        every assertion below true of a function that never ran git.
        """
        argv: list[str] = []
        options: dict[str, object] = {}
        real = subprocess.run

        def recording(command, *args, **kwargs):  # type: ignore[no-untyped-def]
            argv.extend(command)
            options.update(kwargs)
            return real(command, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", recording)
        discover_layout(root)
        return argv, options

    def test_the_wait_is_bounded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AN EXTERNAL PROCESS CAN HANG FOREVER. Without a timeout a wedged git
        turns a gate into a stuck CI job a human must notice and cancel.
        """
        init_repository(tmp_path)

        _, options = self.recorded_call(tmp_path, monkeypatch)

        assert options["timeout"] == DISCOVERY_TIMEOUT_SECONDS

    def test_a_non_zero_exit_is_an_answer_rather_than_an_exception(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """check=False IS DELIBERATE. "Not a repository" is a fact about where
        the caller is standing; reporting it as CalledProcessError would
        describe a crash where the truth is simply that there is none here.
        """
        init_repository(tmp_path)

        _, options = self.recorded_call(tmp_path, monkeypatch)

        assert options["check"] is False

    def test_the_executable_is_an_absolute_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RESOLVED, NOT NAMED. A bare name is looked up against PATH -- and can
        consult the working directory first, which is the untrusted search path
        GitPython's advisory describes. A gate runs inside the tree it judges.
        """
        init_repository(tmp_path)

        argv, _ = self.recorded_call(tmp_path, monkeypatch)

        assert argv[0].startswith("/")

    def test_every_question_is_asked_in_the_one_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """THE COMBINED rev-parse, measured elsewhere at 65% faster than three
        sequential calls, and this runs on every gate invocation.
        """
        init_repository(tmp_path)

        argv, _ = self.recorded_call(tmp_path, monkeypatch)

        assert "--git-dir" in argv
        assert "--git-common-dir" in argv
        assert "--show-toplevel" in argv


class TestPathsContainingSpaces:
    def test_a_repository_path_with_a_space_is_read_whole(self, tmp_path: Path) -> None:
        """split("\\n"), NOT split(). Splitting on all whitespace shatters a
        path containing a space -- and macOS ships directories like
        "Application Support" as a matter of course.
        """
        spaced = tmp_path / "my repository"
        init_repository(spaced)

        assert discover_layout(spaced).toplevel == spaced.resolve()

    def test_a_subdirectory_with_a_space_still_finds_the_root(self, tmp_path: Path) -> None:
        spaced = tmp_path / "my repository"
        init_repository(spaced)
        nested = spaced / "some folder"
        nested.mkdir()

        assert discover_layout(nested).toplevel == spaced.resolve()

    def test_the_git_directory_of_a_spaced_path_is_whole(self, tmp_path: Path) -> None:
        """THE SECOND FIELD TOO. A shattered read would leave this one wrong
        while the toplevel happened to look right.
        """
        spaced = tmp_path / "my repository"
        init_repository(spaced)

        assert discover_layout(spaced).git_dir == (spaced / ".git").resolve()


class TestRefusalMessages:
    def test_a_directory_outside_a_repository_names_itself(self, tmp_path: Path) -> None:
        """A REFUSAL THAT DOES NOT SAY WHAT IT EXAMINED costs the reader the
        whole investigation."""
        with pytest.raises(FileNotFoundError, match=re.escape(str(tmp_path))):
            discover_layout(tmp_path)

    def test_a_missing_directory_names_itself(self, tmp_path: Path) -> None:
        absent = tmp_path / "absent"

        with pytest.raises(FileNotFoundError, match=re.escape(str(absent))):
            discover_layout(absent)

    def test_the_two_refusals_are_distinguishable(self, tmp_path: Path) -> None:
        """A TYPO IN A PATH AND STANDING IN THE WRONG PLACE are different
        problems with different fixes, and one message for both would send the
        reader looking in the wrong direction.
        """
        with pytest.raises(FileNotFoundError, match="is not a directory"):
            discover_layout(tmp_path / "absent")

        with pytest.raises(FileNotFoundError, match="not inside a git repository"):
            discover_layout(tmp_path)
