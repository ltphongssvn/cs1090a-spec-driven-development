# src/cs1090a_spec_driven_development/git_topology.py
# WHERE THE REPOSITORY IS, ASKED OF GIT AND VALIDATED AS A PATH THAT EXISTS.
#
# --- THE DEFECT THIS REMOVES --------------------------------------------------
#
# Code located the repository with Path(__file__).resolve().parent.parent. Under
# mutmut that resolves to ./mutants -- a scratch copy holding Python source and
# no policies/ -- so every policy test failed on a refusal that was itself
# correct. The refusal was right; the locator was naive.
#
# THE SAME DEFECT IS DOCUMENTED ELSEWHERE IN 2026 WITH A WORSE OUTCOME: a tool
# anchored to `Path(__file__).resolve().parents[2]`, invoked from a WORKTREE
# that lacked its own copy, silently resolved to the MAIN CLONE's root -- so it
# read the wrong branch and wrote into an unrelated workflow. This repository
# uses a worktree per feature branch, so that is our exact exposure.
#
# PYTEST'S config.rootpath IS NOT THE ANSWER EITHER: rootdir derives from the
# configfile, and mutmut's scratch tree carries its own pyproject.toml, so it
# resolves to ./mutants as well -- the same wrong answer arrived at more
# respectably.
#
# --- ONE SUBPROCESS, NOT THREE ------------------------------------------------
#
# git answers every question in a single invocation:
#
#   git rev-parse --git-dir --git-common-dir --show-toplevel
#
# A 2026 benchmark of exactly this consolidation measured a median of 33.2 ms
# for three sequential calls against 11.5 ms combined -- 65% faster -- and this
# runs on every gate invocation. The required directories are emitted first,
# which is why the answers are read in that order below.
#
# --- NO MANUAL TRAVERSAL ------------------------------------------------------
#
# `git -C <somewhere> rev-parse` already walks up from wherever it is pointed.
# Prefixing `../../..` reintroduces precisely the brittleness the git call
# removes -- it breaks the day the caller moves -- and a 2026 review names it as
# undermining the very fix it accompanies.
#
# --- DirectoryPath, NOT Path --------------------------------------------------
#
# pydantic's DirectoryPath is "like Path, but the path must exist and be a
# directory". A gate accepting a root that is not there fails later, deeper, and
# with a worse message. This repository has twice watched a gate report success
# over something it never examined, and a validated type is how that stops being
# a matter of care.
#
# THE DISTINCTION IS ALSO REAL RATHER THAN DEFENSIVE: in a linked worktree,
# `.git` is a FILE, so "exists" and "is a directory" genuinely differ here.
#
# --- THE SUBPROCESS CONTRACT --------------------------------------------------
#
# A LIST, NEVER A STRING, so no shell is involved and nothing can be quoted into
# a command. timeout BOUNDS THE WAIT, because an external process can hang
# forever and a wedged git turns a gate into a stuck CI job. check=False here
# because "not a repository" is an ANSWER, not a crash -- it is reported as a
# refusal naming the directory that was examined.

import os
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict, DirectoryPath

from cs1090a_spec_driven_development.executables import resolve

ROOT_VARIABLE = "CS1090A_GATE_ROOT"
DISCOVERY_TIMEOUT_SECONDS = 30

# THE ORDER IS GIT'S, NOT OURS. `rev-parse` emits the required directories
# before the toplevel, so the answers are unpacked in the order requested.
DISCOVERY_ARGUMENTS = ["--git-dir", "--git-common-dir", "--show-toplevel"]


class RepositoryLayout(BaseModel):
    """Where git says this repository lives.

    THREE DIRECTORIES BECAUSE THEY DIFFER, and the difference is the point:

      toplevel    the working tree a caller is standing in
      git_dir     that worktree's own administrative directory
      common_dir  the shared store where refs and objects actually live

    IN A PLAIN CLONE THE LAST TWO ARE THE SAME. In a linked worktree they are
    not, and code that assumes otherwise writes to the wrong place -- which is
    why both are reported rather than one being derived from the other.

    FROZEN, because a layout is an OBSERVATION. A caller editing it between
    discovery and use would be describing a repository that does not exist.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    toplevel: DirectoryPath
    git_dir: DirectoryPath
    common_dir: DirectoryPath

    @property
    def is_linked_worktree(self) -> bool:
        """Whether this working tree is linked rather than the main clone."""
        return self.git_dir != self.common_dir


def ask_git(start: Path) -> list[str]:
    """Put every discovery question to git in one invocation.

    check=False BECAUSE "NOT A REPOSITORY" IS AN ANSWER. Raising
    CalledProcessError here would report a crash where the truth is simply that
    the caller is standing outside a repository, and the two deserve different
    messages.
    """
    completed = subprocess.run(  # noqa: S603
        [resolve("git"), "-C", str(start), "rev-parse", *DISCOVERY_ARGUMENTS],
        capture_output=True,
        text=True,
        check=False,
        timeout=DISCOVERY_TIMEOUT_SECONDS,
    )

    if completed.returncode != 0:
        raise FileNotFoundError(f"{start} is not inside a git repository")

    return completed.stdout.split("\n")


def absolute(answer: str, relative_to: Path) -> Path:
    """Resolve one of git's answers against the directory it was asked from.

    GIT ANSWERS RELATIVELY WHEN IT CAN: `--git-dir` returns ".git" when run at
    the root of a plain clone. A relative path resolved later against a
    different working directory is the class of defect this module exists to
    remove, so resolution happens HERE, against the directory actually used.
    """
    return Path(relative_to, answer.strip()).resolve()


def discover_layout(start: Path | None = None) -> RepositoryLayout:
    """Ask git where the repository is, from wherever the caller happens to be.

    THE DEFAULT IS THE WORKING DIRECTORY, deliberately -- not this file's
    location. A worktree invocation must anchor to the WORKTREE, and anchoring
    to a script's path is the documented way to end up reading the main clone
    instead.
    """
    origin = Path.cwd() if start is None else start
    if not origin.is_dir():
        raise FileNotFoundError(f"{origin} is not a directory")

    git_dir, common_dir, toplevel = ask_git(origin)[:3]

    return RepositoryLayout(
        toplevel=absolute(toplevel, origin),
        git_dir=absolute(git_dir, origin),
        common_dir=absolute(common_dir, origin),
    )


def override_root() -> Path | None:
    """An explicitly staged root, when an operator has named one.

    EXPLICIT INTENT OUTRANKS DISCOVERY. CI sometimes assembles a tree
    deliberately, and a tool that overrules its operator is a tool the operator
    routes around.

    AN EMPTY VALUE IS NOT A PATH. An unset variable commonly arrives as the
    empty string, and treating that as a directory silently points the gate at
    the current one.
    """
    named = os.environ.get(ROOT_VARIABLE)
    return Path(named) if named else None


def repository_root(start: Path | None = None) -> Path:
    """The directory a gate should read and write, in priority order.

    OVERRIDE, THEN GIT. There is no third fallback: if the caller is not in a
    repository and has named no root, a gate cannot know which tree it is
    judging, and guessing is how one comes to report confidently about the
    wrong one.

    THE OVERRIDE IS VALIDATED, NOT TRUSTED. A typo in an environment variable
    fails here, naming the directory, rather than sending every subsequent read
    somewhere nobody meant.
    """
    named = override_root()
    if named is not None:
        return RepositoryLayout(
            toplevel=named,
            git_dir=named,
            common_dir=named,
        ).toplevel

    return discover_layout(start).toplevel
