# src/cs1090a_spec_driven_development/policies/repository/repository.rego
# THIS REPOSITORY'S INVARIANTS, AS EXECUTABLE POLICY.
#
# WHAT THIS EXPRESSES THAT NO OTHER GATE CAN. ruff checks Python, mypy checks
# types, mutmut checks assertions. None can state "no task may parse
# human-readable git output" or "the CI job name must equal the context the
# branch ruleset requires": those are facts ABOUT the configuration, spanning
# files no single tool reads together.
#
# --- THESE RULES READ STRUCTURE, NOT TEXT -------------------------------------
#
# THE EARLIER VERSIONS READ TEXT AND WERE WRONG. The parsing rule asked whether
# a body contained "git " and "| grep", and denied `setup`, which has
#
#   git rev-parse --git-path hooks
#   ls "$hooks_dir" | grep -v sample
#
# thirty lines apart. Correlating per line was still substring matching, and
# would have been defeated next by quoted text or a `;`-separated command.
#
# TASK BODIES NOW ARRIVE PARSED. src/cs1090a_spec_driven_development/shell.py
# runs them through bashlex -- a transliteration of GNU bash's own parser -- and
# the gatherer hands over `commands` and `pipelines` as structure. The question
# below is "is there a PIPELINE whose first stage is git and whose LATER stage
# is a parser", which no quoting, comment or line break can fool, because it is
# a question about a tree.
#
# THE MEASUREMENT THAT SETTLED IT: shlex tore apart nested substitution on 16
# lines of the real mise.toml; bashlex reads 19 of 25 task bodies. The 6 it
# cannot read are exactly the tasks carrying shell logic.
#
# --- ORDER IS EXPRESSED BY SLICING, NOT BY INDEX ARITHMETIC -------------------
#
# The first structural version compared two indices, and regal's
# prefer-some-in-iteration objected. It was right for a reason beyond style:
# index arithmetic states HOW to find the answer, while a slice states WHAT is
# being asked -- "somewhere after git, a parser" -- and cannot be written with
# the comparison accidentally reversed.
#
# --- DENY RATHER THAN ALLOW ---------------------------------------------------
#
# A deny set permits anything unstated, which is right for rules about a
# repository's own conventions: an allow list would enumerate every legitimate
# command and block work the day someone used a tool nobody anticipated.
#
# --- SHAPE, AND WHY NOTHING IS CONFIGURED AWAY --------------------------------
#
# regal reported five kinds of violation across these revisions and its
# documentation says it "is not meant to be the law" -- a .regal/config.yaml
# would have silenced all of them in five lines. Each was fixed structurally:
# helpers first and every `deny` head grouped (messy-rule), the directory
# mirroring the package (directory-package-mismatch), the entrypoint annotated
# (no-defined-entrypoint), messages kept short (line-length), and ordering
# expressed by slicing (prefer-some-in-iteration).
#
# NO `import rego.v1`. OPA 1.19 reports `Rego Version: v1`, so `if` and
# `contains` are the language default and the import is a no-op regal flags.

# METADATA
# description: Invariants this repository holds about its own configuration.
# entrypoint: true
package repository

# --- Helpers ------------------------------------------------------------------

# THE PORCELAIN FORMATS CARRY A STABILITY CONTRACT: git guarantees they will not
# change in a backwards-incompatible way. The long format carries no such
# promise -- hint text changes, headers get reworded, sections are added -- so a
# script reading it works until someone upgrades git.
_parsing_commands := {"grep", "awk", "sed", "cut", "wc", "head", "tail", "sort"}

_stable_output_flags := ["--porcelain", "-z", "--format=", "--pretty=format:"]

# git status performs an OPTIONAL index write-back that TAKES A LOCK. A
# concurrent foreground git command then fails because it cannot acquire it,
# producing intermittent errors that are near-impossible to reproduce -- and
# this repository already runs four mutmut children in parallel.
_observational_reads := {"status", "diff", "describe"}

# A PIPELINE IS A LIST OF LEADING COMMANDS, IN ORDER. `git | grep` and
# `grep | git` are different programs, so position is the fact being read: the
# parser must come AFTER git, which the slice states directly.
_downstream_of_git(pipeline) := array.slice(pipeline, _git_position(pipeline) + 1, count(pipeline))

_git_position(pipeline) := position if {
	some position, command in pipeline
	command == "git"
}

_git_feeds_a_parser(pipeline) if {
	some downstream in _downstream_of_git(pipeline)
	downstream in _parsing_commands
}

_git_command(task) := argv if {
	some argv in task.commands
	argv[0] == "git"
}

_declares_stable_output(argv) if {
	some argument in argv
	some flag in _stable_output_flags
	startswith(argument, flag)
}

_is_observational(argv) if {
	some argument in argv
	argument in _observational_reads
}

_guards_the_lock(argv) if {
	some argument in argv
	argument == "--no-optional-locks"
}

_invokes_python(argv) if {
	some argument in argv
	argument in {"python", "python3"}
}

_sets_errexit(task) if {
	some argv in task.commands
	argv[0] == "set"
	some argument in argv
	argument == "-euo"
}

# FORTY LOWERCASE HEX CHARACTERS OR IT IS NOT A FULL SHA. An abbreviated hash is
# ambiguous in principle and unpinned in practice; git renders hashes in
# lowercase, so accepting both spellings would let one reference be written two
# ways and compared unequal.
_is_full_sha(reference) if {
	regex.match(`^[0-9a-f]{40}$`, reference)
}

# --- Decisions ----------------------------------------------------------------

# Git output is read through an interface that carries a stability contract.
deny contains message if {
	some name, task in input.tasks
	some pipeline in task.pipelines
	_git_feeds_a_parser(pipeline)
	not _declares_stable_output(_git_command(task))

	message := sprintf("task '%s' parses human-readable git output", [name])
}

# Observational reads leave the index alone.
deny contains message if {
	some name, task in input.tasks
	some argv in task.commands
	argv[0] == "git"
	_is_observational(argv)
	not _guards_the_lock(argv)

	message := sprintf("task '%s' reads git state without --no-optional-locks", [name])
}

# Python is resolved by the project, never by PATH. A bare interpreter is
# whichever one PATH happens to offer, carrying none of the project's
# dependencies -- already encountered here, where a bare python3 inside the
# devShell failed on `import yaml` while `uv run python` succeeded.
deny contains message if {
	some name, task in input.tasks
	some argv in task.commands
	_invokes_python(argv)
	argv[0] != "uv"

	message := sprintf("task '%s' invokes python outside uv", [name])
}

# Multi-command task bodies fail closed. BASH DOES NOT SET errexit, so without
# the preamble a failing command mid-body is ignored and the task reports
# success -- a green gate over a step that did not happen.
deny contains message if {
	some name, task in input.tasks
	count(task.commands) > 1
	not _sets_errexit(task)

	message := sprintf("task '%s' runs several commands without errexit", [name])
}

# The policy suite refuses to be empty. `opa test` EXITS ZERO WHEN ZERO TESTS
# RUN, so a renamed package or mistyped path produces a green policy gate that
# tested nothing -- the same vacuity this repository already found in its
# mutation gate, in a different tool.
deny contains message if {
	some name, task in input.tasks
	some argv in task.commands
	argv[0] == "opa"
	some subcommand in argv
	subcommand == "test"
	not _declares_fail_on_empty(argv)

	message := sprintf("task '%s' runs opa test without --fail-on-empty", [name])
}

# The toolchain is declared exactly once. flake.nix is that declaration; a
# [tools] block is the drift this repository exists to remove, reproduced at its
# centre.
deny contains message if {
	input.has_tools_block

	message := "mise.toml declares a [tools] block; flake.nix is the declaration"
}

# CI reports the context the branch ruleset requires. GitHub uses the JOB'S
# `name` as the status check context, so renaming the job makes the requirement
# unsatisfiable and every pull request waits forever on a check that will never
# report -- a deadlock that looks like a slow build.
deny contains message if {
	some required in input.required_contexts
	not required in input.ci_job_names

	message := sprintf("no CI job declares the required check '%s'", [required])
}

# Workflow actions are pinned to an immutable reference. A tag is a mutable
# pointer its owner can move, so `@v4` means "run whatever that repository
# contains when the job starts" -- the supply-chain hole flake.lock and uv.lock
# exist to close, reopened in the file that runs them.
deny contains message if {
	some action in input.workflow_actions
	parts := split(action, "@")
	count(parts) == 2
	not _is_full_sha(parts[1])

	message := sprintf("action '%s' is not pinned to a commit sha", [action])
}

_declares_fail_on_empty(argv) if {
	some argument in argv
	argument == "--fail-on-empty"
}
