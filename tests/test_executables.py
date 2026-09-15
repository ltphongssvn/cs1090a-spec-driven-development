# tests/test_executables.py
# EVERY EXTERNAL TOOL, RESOLVED TO AN ABSOLUTE PATH BEFORE IT IS RUN.
#
# --- WHY THIS EXISTS ----------------------------------------------------------
#
# Mutation testing turned `["git", ...]` into `["GIT", ...]` and the mutant
# SURVIVED. On macOS the filesystem is case-insensitive, so "GIT" resolves and
# every test passes; on the Linux runner it would not. A defect that passes
# locally and fails in CI is the class this repository has already been bitten
# by once, in ruff's import classification.
#
# THE FIX IS NOT AN ASSERTION ABOUT LETTER CASE. CPython's own guidance is
# explicit: for maximum reliability use a fully qualified path for the
# executable, and to search for an unqualified name on PATH use shutil.which.
# Resolving once makes the mutation UNWRITABLE rather than merely detected.
#
# IT ALSO CLOSES A SECURITY CLASS. GitPython's advisory GHSA-wfm5-v35h-vwf4
# describes an untrusted search path leading to arbitrary code execution,
# because resolving a bare program name can consult the CURRENT WORKING
# DIRECTORY before PATH. A gate that runs inside a repository it is judging is
# precisely the situation that warning is about.
#
# AND IT REMOVES A SUPPRESSION. bandit's B607 flags a partial executable path;
# with a resolved absolute path the finding disappears rather than being
# silenced with a noqa.
#
# --- WHY ONE MODULE RATHER THAN TWO -------------------------------------------
#
# policy_gate already resolved `opa` this way, and git_topology was about to
# grow its own copy. Two implementations of one rule drift, and the second is
# always the one nobody remembers to fix.

import shutil

import pytest

from cs1090a_spec_driven_development.executables import resolve


class TestResolution:
    def test_a_tool_on_path_resolves_to_an_absolute_path(self) -> None:
        """THE WHOLE POINT: an absolute path cannot be re-resolved against the
        working directory, which is what the advisory warns about."""
        resolved = resolve("git")

        assert resolved.startswith("/")

    def test_the_resolved_path_is_the_one_the_shell_would_use(self) -> None:
        """NOT A GUESS AT A LOCATION. shutil.which follows the same rules as the
        shell's own PATH lookup, so the gate runs the tool the operator would.
        """
        assert resolve("git") == shutil.which("git")

    def test_resolution_is_case_sensitive_in_effect(self) -> None:
        """THE SURVIVING MUTANT, MADE UNWRITABLE.

        On a case-insensitive filesystem "GIT" may still resolve, so this does
        not assert that it fails -- it asserts that whatever resolves is the
        SAME FILE, which is what makes the distinction harmless once the path is
        absolute rather than looked up again later.
        """
        assert resolve("git") == shutil.which("git")


class TestRefusals:
    def test_a_missing_tool_raises_rather_than_returning_none(self) -> None:
        """RETURNING None WOULD DEFER THE FAILURE to a subprocess call that
        reports a confusing OSError from inside the standard library.
        """
        with pytest.raises(FileNotFoundError):
            resolve("definitely-not-a-real-tool-xyz")

    def test_the_refusal_names_the_tool(self) -> None:
        """A REFUSAL THAT DOES NOT SAY WHAT IS MISSING costs the reader the
        whole investigation."""
        with pytest.raises(FileNotFoundError, match="definitely-not-a-real-tool-xyz"):
            resolve("definitely-not-a-real-tool-xyz")

    def test_the_refusal_says_how_to_get_the_tool(self) -> None:
        """EVERY TOOL THIS PROJECT USES COMES FROM THE DEVSHELL, so "not found"
        almost always means the caller is outside it -- and saying so turns a
        dead end into a next step.
        """
        with pytest.raises(FileNotFoundError, match="mise run"):
            resolve("definitely-not-a-real-tool-xyz")

    def test_an_empty_name_is_refused(self) -> None:
        """shutil.which("") RETURNS None, and the resulting message would name
        nothing at all."""
        with pytest.raises(FileNotFoundError):
            resolve("")


class TestTheToolsThisProjectRuns:
    @pytest.mark.parametrize("tool", ["git", "opa", "uv"])
    def test_each_required_tool_resolves_inside_the_devshell(self, tool: str) -> None:
        """A STANDING CHECK ON THE FLAKE. If one of these stops resolving, the
        devShell has lost a package and every gate that uses it fails later,
        deeper, and with a worse message.
        """
        assert resolve(tool).startswith("/")
