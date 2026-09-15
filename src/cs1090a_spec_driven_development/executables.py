# src/cs1090a_spec_driven_development/executables.py
# EVERY EXTERNAL TOOL, RESOLVED TO AN ABSOLUTE PATH BEFORE IT IS RUN.
#
# --- WHY THIS MODULE EXISTS ---------------------------------------------------
#
# Mutation testing turned `["git", ...]` into `["GIT", ...]` and the mutant
# SURVIVED. macOS has a case-insensitive filesystem, so "GIT" resolves and every
# test passes; on the Linux runner it would not. A defect that passes locally
# and fails in CI is the class this repository has already been bitten by once,
# in ruff's import classification.
#
# THE FIX IS NOT AN ASSERTION ABOUT LETTER CASE. CPython's own guidance is
# explicit: FOR MAXIMUM RELIABILITY USE A FULLY QUALIFIED PATH FOR THE
# EXECUTABLE, and to search for an unqualified name on PATH use shutil.which.
# Resolving once makes that mutation unwritable rather than merely detected --
# which is the difference between fixing a defect and testing around it.
#
# IT ALSO CLOSES A SECURITY CLASS. GitPython's advisory GHSA-wfm5-v35h-vwf4
# describes an untrusted search path leading to arbitrary code execution,
# because resolving a bare program name can consult the CURRENT WORKING
# DIRECTORY before PATH. A gate that runs inside the repository it is judging is
# exactly the situation that warning is about: the tree under examination is not
# necessarily trustworthy.
#
# AND IT REMOVES A SUPPRESSION. bandit's B607 flags a partial executable path;
# with an absolute path the finding disappears rather than being silenced.
#
# --- ONE RESOLVER, NOT ONE PER CALLER -----------------------------------------
#
# policy_gate already resolved `opa` this way and git_topology was about to grow
# its own copy. Two implementations of one rule drift, and the second is always
# the one nobody remembers to fix.
#
# --- WHY IT RAISES RATHER THAN RETURNING None ---------------------------------
#
# shutil.which returns None for a missing tool. Passing that to subprocess
# defers the failure to an OSError raised from inside the standard library,
# naming nothing useful. Failing here names the tool AND the way to get it,
# because in this project a missing tool almost always means the caller is
# outside the Nix devShell.

import shutil

# EVERY TOOL COMES FROM flake.nix, and every task runs inside the devShell, so
# "not found" has one overwhelmingly likely cause and one remedy.
REMEDY = "run this through `mise run`, which enters the Nix devShell"


def resolve(tool: str) -> str:
    """The absolute path to an external tool, or a refusal naming it.

    shutil.which FOLLOWS THE SHELL'S OWN PATH RULES, so the gate runs the tool
    an operator would get by typing its name -- rather than a path this project
    guessed at and pinned.
    """
    resolved = shutil.which(tool) if tool else None
    if resolved is None:
        raise FileNotFoundError(f"{tool!r} is not on PATH: {REMEDY}")
    return resolved
