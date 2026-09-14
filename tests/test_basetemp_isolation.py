# tests/test_basetemp_isolation.py
# ONE TEMPORARY ROOT PER PROCESS, SO CONCURRENT SESSIONS CANNOT COLLIDE.
#
# THE FAILURE THIS FIXES. A mutation run aborted mid-flight with:
#
#   FileNotFoundError: .../pytest-of-thanhphongle/pytest-current
#     in cleanup_dead_symlinks -> left_dir.unlink()
#
# NOT A TEST FAILURE, AND NOT OUR CODE. pytest derives its base temp directory
# from tempfile.gettempdir() plus a USER-scoped subdirectory, keeps a
# `pytest-current` SYMLINK inside it, and garbage-collects stale numbered
# directories at session end. That structure is shared by every pytest session
# on the machine.
#
# mutmut RUNS FOUR CHILDREN at --max-children 4, each calling pytest.main() in
# process. Four sessions create, relink and clean up the same symlink
# concurrently; one unlinks it between another's existence check and its own
# unlink, and the loser dies with FileNotFoundError.
#
# WHY IT MATTERS THOUGH THE RUN FINISHED. That crash landed after the verdict
# was written. A race has no such manners: the same collision midway leaves a
# PARTIAL report, and a gate reading a partial report publishes a number nobody
# produced -- the exact failure the mutation gate exists to prevent, arriving
# through the back door.
#
# ISOLATION RATHER THAN RETRY. Giving each PROCESS its own base temp directory
# removes the shared resource instead of serialising access to it.
#
# --- WHY THE ROOT IN THESE TESTS IS NOT /tmp ----------------------------------
#
# The first version passed Path("/tmp") and ruff raised S108 ten times:
# hardcoded temporary paths are world-writable and predictable, which is a real
# hazard even though these particular assertions touch no filesystem at all.
#
# TEN SUPPRESSIONS WOULD HAVE BEEN THE WRONG ANSWER. The function under test
# takes the root as a PARAMETER precisely so it does not care what the root is,
# so any directory proves the property. Using one that is obviously not a
# temporary directory also makes the tests say what they mean: the composition
# is being asserted, not the choice of /tmp. The real root arrives from
# tempfile.gettempdir() in conftest, in one place, tested separately below
# through an actual tmp_path.

import os
import re
from pathlib import Path

from conftest import session_basetemp

# A ROOT THAT IS DELIBERATELY NOT A TEMPORARY DIRECTORY. session_basetemp takes
# the root as an argument and joins a name onto it; nothing here is created, so
# the value only has to be recognisable in an assertion.
ROOT = Path("/example-root")


class TestSessionBasetemp:
    def test_the_path_is_scoped_to_the_process(self) -> None:
        """THE PID IS THE ISOLATION. Two concurrent sessions cannot share a
        directory named after different processes."""
        assert session_basetemp(ROOT, pid=4321) == ROOT / "pytest-session-4321"

    def test_two_processes_receive_different_paths(self) -> None:
        assert session_basetemp(ROOT, pid=1) != session_basetemp(ROOT, pid=2)

    def test_the_same_process_receives_a_stable_path(self) -> None:
        """STABLE WITHIN A SESSION, because pytest CLEARS basetemp on first use;
        a path that varied per call would delete the directory it just made.
        """
        assert session_basetemp(ROOT, pid=99) == session_basetemp(ROOT, pid=99)

    def test_the_path_sits_directly_under_the_supplied_root(self) -> None:
        """ONE LEVEL DOWN, so the caller's root is honoured rather than nested
        inside a structure of our own."""
        assert session_basetemp(ROOT, pid=7).parent == ROOT

    def test_a_different_root_is_honoured(self) -> None:
        """THE ROOT IS A PARAMETER, not a decoration. conftest supplies the real
        one from tempfile.gettempdir(), which varies by platform and by shell --
        under `nix develop` it is not /tmp at all.
        """
        other = Path("/another-root")

        assert session_basetemp(other, pid=7) == other / "pytest-session-7"

    def test_the_name_does_not_collide_with_pytest_s_own_layout(self) -> None:
        """pytest-of-<user> AND pytest-current ARE PYTEST'S. Reusing either name
        would put us back inside the structure being avoided.
        """
        name = session_basetemp(ROOT, pid=7).name

        assert name != "pytest-current"
        assert not name.startswith("pytest-of-")

    def test_the_name_is_filesystem_safe(self) -> None:
        """NO SEPARATORS OR SPACES, so the path is one directory and not two."""
        assert re.fullmatch(r"[A-Za-z0-9_-]+", session_basetemp(ROOT, pid=12345).name)

    def test_the_current_process_id_is_used_by_default(self) -> None:
        """THE DEFAULT IS THE POINT: a caller that must remember to pass its own
        pid is a caller that will one day forget."""
        assert session_basetemp(ROOT) == session_basetemp(ROOT, pid=os.getpid())


class TestIsolationInPractice:
    """Asserted through a REAL fixture, so the hook is proven to have applied."""

    def test_this_session_is_not_using_the_shared_pytest_root(self, tmp_path: Path) -> None:
        """THE CONFIGURATION, NOT THE HELPER.

        tmp_path is allocated under whatever basetemp pytest resolved. If the
        conftest hook had not taken effect this path would still sit under
        pytest-of-<user> and the race would remain, so the assertion is on the
        actual directory rather than on the option.
        """
        assert "pytest-of-" not in str(tmp_path)

    def test_the_session_directory_is_named_for_this_process(self, tmp_path: Path) -> None:
        assert f"pytest-session-{os.getpid()}" in str(tmp_path)

    def test_the_session_directory_is_writable(self, tmp_path: Path) -> None:
        """A PATH THAT CANNOT BE WRITTEN TO IS NOT A FIX.

        Every other test in this repository depends on tmp_path working, so the
        redirection is proven end to end rather than only by its name.
        """
        target = tmp_path / "probe.txt"
        target.write_text("written")

        assert target.read_text() == "written"
