# src/cs1090a_spec_driven_development/policies/repository/repository_test.rego
# THE TESTS FOR THIS REPOSITORY'S OWN POLICIES.
#
# --- THE FIXTURES CARRY STRUCTURE, NOT SHELL TEXT -----------------------------
#
# EARLIER VERSIONS SUPPLIED `run` STRINGS, because the rules read strings. Both
# were wrong together, and the repository proved it: the parsing rule denied
# `setup` for having `git rev-parse` on one line and `ls | grep -v sample`
# thirty lines away.
#
# TASK BODIES ARE NOW PARSED BY bashlex BEFORE A POLICY SEES THEM, so a fixture
# states what a task IS -- which commands it runs, which pipelines it forms --
# rather than what its text happens to contain. tests/test_shell.py proves the
# real parser produces this shape from real shell, and the two meet in
# tests/test_policy_decisions.py, which runs the real engine over the real tree.
#
# --- A FIXTURE MUST VIOLATE ONLY THE RULE IT TESTS ----------------------------
#
# THIS SUITE HAS NOW MADE THE SAME MISTAKE TWICE, in two different dimensions.
#
# FIRST: a case meant to show porcelain output is ALLOWED used
# `git status --porcelain=v2`, which the parsing rule permits and the
# OPTIONAL-LOCKS rule forbids. The test failed while both policies were correct.
#
# SECOND: a case meant to show a pipeline is DENIED supplied two commands and no
# `set -euo pipefail`, so the errexit rule fired as well -- and the exact-set
# assertion failed on a second message that was entirely correct.
#
# `opa eval -f pretty 'data.repository.deny'` NAMED BOTH, which is the
# difference between fixing a fixture and "fixing" a policy that was never
# wrong. Rego fails silently by design: a rule that does not match contributes
# nothing, so a denial has to be READ rather than guessed at.
#
# EVERY MULTI-COMMAND FIXTURE THEREFORE CARRIES `set -euo pipefail` unless the
# errexit rule is the one under test. The cost is one line per fixture; the
# alternative is a suite that fails for reasons unrelated to its subject.
#
# --- WHY NOT `count(deny) == 0` ----------------------------------------------
#
# IT IS A NAMED FALSE-POSITIVE ANTI-PATTERN. Asserting the ABSENCE of violations
# passes whenever a rule fails to fire -- including when it fails because the
# fixture's shape is wrong. `deny == set()` states the exact decision, and each
# deny-case states the exact message set, so a wrong message, an extra denial or
# a missing one all fail.
#
# --- WHAT REGO CAN AND CANNOT BE HELD TO --------------------------------------
#
# STATED PLAINLY BECAUSE IT WOULD OTHERWISE LOOK LIKE COVERAGE: mutmut mutates
# Python and does not mutate Rego, so these rules are NOT mutation-tested. Their
# assurance comes from `opa test` and from the exact-set assertions below.

package repository_test

import data.repository

# THE errexit PREAMBLE, PRESENT IN EVERY MULTI-COMMAND FIXTURE that is not
# testing the errexit rule itself. See the header: without it, every such
# fixture violates two rules and every exact-set assertion fails on the second.
_guard := ["set", "-euo", "pipefail"]

# A TASK, AS THE GATHERER PRESENTS IT. `commands` is every simple command's
# argument vector; `pipelines` is the leading command of each stage, in order.
_task(name, commands, pipelines) := {"tasks": {name: {
	"parses": true,
	"commands": commands,
	"pipelines": pipelines,
}}}

_simple(name, argv) := _task(name, [argv], [])

_actions(references) := {"workflow_actions": references}

_ci(job_names, required) := {"ci_job_names": job_names, "required_contexts": required}

# --- Git output is read through a stable interface ----------------------------

test_porcelain_output_is_allowed if {
	fixture := _task(
		"status",
		[_guard, ["git", "--no-optional-locks", "status", "--porcelain=v2", "-z"], ["grep", "M"]],
		[["git", "grep"]],
	)

	repository.deny == set() with input as fixture
}

test_git_feeding_a_parser_is_denied if {
	# THE STRUCTURAL QUESTION: git's output reaches grep. No quoting or line
	# break can disguise it, because this is a pipeline rather than a string.
	fixture := _task(
		"branches",
		[_guard, ["git", "branch", "-a"], ["grep", "develop"]],
		[["git", "grep"]],
	)

	repository.deny == {"task 'branches' parses human-readable git output"} with input as fixture
}

test_git_and_a_parser_in_separate_pipelines_are_allowed if {
	# THE FALSE POSITIVE THAT CAUSED THE REWRITE, now a permanent test.
	#
	#   git rev-parse --git-path hooks
	#   ls "$hooks_dir" | grep -v sample
	#
	# Two commands, two pipelines, nothing piped from git. The old text-matching
	# rule denied this and was wrong.
	fixture := _task(
		"setup",
		[
			_guard,
			["git", "rev-parse", "--git-path", "hooks"],
			["ls", "$hooks_dir"],
			["grep", "-v", "sample"],
		],
		[["ls", "grep"]],
	)

	repository.deny == set() with input as fixture
}

test_an_explicit_format_is_allowed if {
	# `--format` AND `--pretty=format:` ARE CONTRACTS TOO: the caller states the
	# fields and their order, so the output is as stable as porcelain.
	fixture := _task(
		"tip",
		[_guard, ["git", "log", "-1", "--pretty=format:%H"], ["cut", "-c1-7"]],
		[["git", "cut"]],
	)

	repository.deny == set() with input as fixture
}

test_a_parser_feeding_git_is_allowed if {
	# DIRECTION MATTERS. `grep x | git apply` writes to git's INPUT and reads
	# none of its output, so the rule about reading must not fire.
	fixture := _task(
		"apply",
		[_guard, ["grep", "x", "patch"], ["git", "apply"]],
		[["grep", "git"]],
	)

	repository.deny == set() with input as fixture
}

# --- Observational reads leave the index alone --------------------------------

test_a_read_without_no_optional_locks_is_denied if {
	# git status performs an OPTIONAL index write-back that takes a lock. A
	# concurrent foreground git command then fails, producing intermittent
	# errors nobody can reproduce -- and this repository runs four mutmut
	# children in parallel.
	fixture := _simple("topology", ["git", "status", "--porcelain=v2", "-z"])

	repository.deny == {"task 'topology' reads git state without --no-optional-locks"} with input as fixture
}

test_a_read_with_no_optional_locks_is_allowed if {
	fixture := _simple("topology", ["git", "--no-optional-locks", "status", "--porcelain=v2"])

	repository.deny == set() with input as fixture
}

test_a_non_observational_git_command_needs_no_guard if {
	# `git fetch` WRITES; it does not perform the optional index write-back the
	# rule is about, and demanding the flag there would be noise.
	fixture := _simple("fetch", ["git", "fetch", "origin", "--prune"])

	repository.deny == set() with input as fixture
}

# --- Multi-command task bodies fail closed ------------------------------------

test_a_multi_command_task_without_errexit_is_denied if {
	# NO _guard HERE, DELIBERATELY: this is the rule under test.
	fixture := _task("broken", [["mise", "run", "lint"], ["mise", "run", "types"]], [])

	repository.deny == {"task 'broken' runs several commands without errexit"} with input as fixture
}

test_a_multi_command_task_with_errexit_is_allowed if {
	fixture := _task("fine", [_guard, ["mise", "run", "lint"]], [])

	repository.deny == set() with input as fixture
}

test_a_single_command_task_needs_no_errexit if {
	# ONE COMMAND CANNOT CONTINUE PAST ITS OWN FAILURE, so demanding the
	# preamble there is noise that trains people to ignore the rule.
	fixture := _simple("lint", ["uv", "run", "ruff", "check", "."])

	repository.deny == set() with input as fixture
}

# --- Python is resolved by the project, never by PATH -------------------------

test_bare_python3_is_denied if {
	# BARE python3 IS WHICHEVER INTERPRETER PATH HAPPENS TO OFFER, carrying none
	# of the project's dependencies. Already encountered here: a bare python3
	# inside the devShell failed on `import yaml`.
	fixture := _simple("broken", ["python3", "-c", "import yaml"])

	repository.deny == {"task 'broken' invokes python outside uv"} with input as fixture
}

test_python_through_uv_is_allowed if {
	fixture := _simple("fine", ["uv", "run", "python", "-c", "import yaml"])

	repository.deny == set() with input as fixture
}

test_a_path_containing_python_is_not_an_invocation if {
	# THE ARGUMENT IS A PATH, not a command. Text matching denied this; reading
	# the argument vector cannot.
	fixture := _simple("fine", ["uv", "run", "ruff", "check", "my-python-files/"])

	repository.deny == set() with input as fixture
}

# --- The policy suite refuses to be empty -------------------------------------

test_a_policy_task_without_fail_on_empty_is_denied if {
	fixture := _task("check:policy", [_guard, ["opa", "test", "policies/"]], [])

	repository.deny == {"task 'check:policy' runs opa test without --fail-on-empty"} with input as fixture
}

test_a_policy_task_with_fail_on_empty_is_allowed if {
	fixture := _task(
		"check:policy",
		[_guard, ["opa", "test", "policies/", "--fail-on-empty"]],
		[],
	)

	repository.deny == set() with input as fixture
}

test_another_opa_subcommand_is_not_affected if {
	# `opa fmt` HAS NO TESTS TO BE EMPTY OF, and demanding the flag there would
	# be a rule about a command that does not accept it.
	fixture := _task("check:policy", [_guard, ["opa", "fmt", "--fail"]], [])

	repository.deny == set() with input as fixture
}

# --- The toolchain is declared exactly once -----------------------------------

test_a_tools_block_is_denied if {
	expected := {"mise.toml declares a [tools] block; flake.nix is the declaration"}

	repository.deny == expected with input as {"has_tools_block": true}
}

test_no_tools_block_is_allowed if {
	repository.deny == set() with input as {"has_tools_block": false}
}

# --- CI reports the context the branch ruleset requires -----------------------

test_a_mismatched_ci_context_is_denied if {
	fixture := _ci(["build"], ["quality gate"])

	repository.deny == {"no CI job declares the required check 'quality gate'"} with input as fixture
}

test_a_matching_ci_context_is_allowed if {
	fixture := _ci(["quality gate"], ["quality gate"])

	repository.deny == set() with input as fixture
}

test_an_extra_ci_job_is_allowed if {
	# THE REQUIREMENT IS COVERAGE, NOT EQUALITY. A repository may run jobs the
	# ruleset does not demand; what it may not do is fail to declare one it does.
	fixture := _ci(["quality gate", "docs"], ["quality gate"])

	repository.deny == set() with input as fixture
}

test_no_ci_jobs_at_all_is_denied if {
	fixture := _ci([], ["quality gate"])

	repository.deny == {"no CI job declares the required check 'quality gate'"} with input as fixture
}

# --- Workflow actions are pinned to an immutable reference --------------------

test_a_tag_pinned_action_is_denied if {
	fixture := _actions(["actions/checkout@v4"])

	repository.deny == {"action 'actions/checkout@v4' is not pinned to a commit sha"} with input as fixture
}

test_a_branch_pinned_action_is_denied if {
	fixture := _actions(["some/action@main"])

	repository.deny == {"action 'some/action@main' is not pinned to a commit sha"} with input as fixture
}

test_a_short_sha_is_denied if {
	fixture := _actions(["actions/checkout@11bd719"])

	repository.deny == {"action 'actions/checkout@11bd719' is not pinned to a commit sha"} with input as fixture
}

test_an_uppercase_sha_is_denied if {
	# git RENDERS HASHES IN LOWERCASE. Accepting both spellings would let one
	# reference be written two ways and compared unequal.
	reference := "actions/checkout@11BD71901BBE5B1630CEEA73D27597364C9AF683"
	expected := sprintf("action '%s' is not pinned to a commit sha", [reference])

	repository.deny == {expected} with input as _actions([reference])
}

test_a_sha_pinned_action_is_allowed if {
	reference := "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683"

	repository.deny == set() with input as _actions([reference])
}

test_several_unpinned_actions_are_each_reported if {
	# ONE MESSAGE PER OFFENDER, so a reader fixes them all in one pass rather
	# than discovering the next on the following run.
	fixture := _actions(["a/b@v1", "c/d@main"])

	count(repository.deny) == 2 with input as fixture
}

# --- Absent input is not a pass -----------------------------------------------

test_an_empty_document_denies_nothing if {
	# THE HONEST BASELINE. With no tasks, no workflow and no ruleset to compare,
	# there is nothing to object to -- and the rules must not fabricate a denial
	# from missing fields.
	repository.deny == set() with input as {}
}
