# tests/test_policy_input.py
# THE REPOSITORY'S OWN CONFIGURATION, GATHERED AS POLICY INPUT.
#
# WHY THIS MODULE EXISTS. policies/repository/ can be immaculate and enforce
# nothing: a suite evaluated only against fixtures proves its rules are
# self-consistent and says nothing about the repository. The split is a
# difference in kind --
#
#   check:policy            are the policies well-formed, idiomatic and tested?
#   check:policy-decisions  does THIS REPOSITORY satisfy them?
#
# --- WHY NOT CONFTEST ---------------------------------------------------------
#
# NEITHER CONFTEST NOR `opa eval` PARSES TOML, and mise.toml carries every task
# body. A gatherer is required whichever engine evaluates. The invariants are
# also CROSS-FILE -- "the CI job name must equal the ruleset's required context"
# spans two files -- and Conftest evaluates FILE BY FILE, so the rule is not
# awkward to express there but inexpressible.
#
# --- TASKS ARRIVE PARSED, WHICH IS WHY THESE ASSERTIONS CHANGED ---------------
#
# `tasks` once held raw `{"run": "..."}` dictionaries and the policy matched
# substrings against them. That denied `setup` for having `git rev-parse` on one
# line and `ls | grep -v sample` thirty lines away.
#
# EACH TASK IS NOW A TaskBody: whether it parsed, every command's argument
# vector, and the leading command of every pipeline stage. mypy caught the
# assertions here that still subscripted a TaskBody like a dict -- drift between
# a contract and its tests, reported statically rather than discovered when a
# rule silently stopped matching.
#
# --- WHY A FROZEN-MODEL ASSERTION CARRIES A type: ignore ----------------------
#
# Enabling the pydantic mypy plugin turned `model.field = x` on a frozen model
# from a runtime ValidationError into a STATIC error: the plugin knows the field
# is read-only. That is the plugin working, and the test is still right -- it
# asserts the assignment is refused.
#
# THE SUPPRESSION IS THEREFORE NARROW AND DELIBERATE: this line is illegal on
# purpose, and the error code is named so a future unrelated error on the same
# line is not swallowed with it.

import json
import tomllib
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from cs1090a_spec_driven_development.policy import (
    PolicyInput,
    gather_policy_input,
    read_ci_job_names,
    read_tasks,
    read_workflow_actions,
)

MISE = """
[task_config]
shell = "nix develop --command bash -c"

[tasks.lint]
description = "Lint"
run = "uv run ruff check ."

[tasks.types]
run = '''
set -euo pipefail
uv run mypy src
'''
"""

WORKFLOW = """
name: ci
jobs:
  quality-gate:
    name: quality gate
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
      - name: Lint
        run: mise run lint
      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
"""

RULESET = """
{
  "name": "develop-and-main-protection",
  "rules": [
    {"type": "deletion"},
    {
      "type": "required_status_checks",
      "parameters": {"required_status_checks": [{"context": "quality gate"}]}
    }
  ]
}
"""


def write_repository(root: Path) -> None:
    """A miniature repository holding each file the gatherer reads."""
    (root / ".github/workflows").mkdir(parents=True)
    (root / "contracts").mkdir(parents=True)
    (root / "mise.toml").write_text(MISE)
    (root / ".github/workflows/ci.yml").write_text(WORKFLOW)
    (root / "contracts/ruleset-develop-and-main.json").write_text(RULESET)


class TestReadTasks:
    def test_every_task_is_gathered(self) -> None:
        assert set(read_tasks(tomllib.loads(MISE))) == {"lint", "types"}

    def test_a_task_arrives_parsed_into_commands(self) -> None:
        """THE SHAPE THE POLICY READS. Not the text, but the argument vector --
        which is what makes a rule immune to quoting and line breaks."""
        tasks = read_tasks(tomllib.loads(MISE))

        assert tasks["lint"].commands == [["uv", "run", "ruff", "check", "."]]

    def test_a_multi_command_body_yields_several_commands(self) -> None:
        """THE FACT THE errexit RULE COUNTS. A body collapsed into one command
        would make every task look single and disable that policy silently.
        """
        tasks = read_tasks(tomllib.loads(MISE))

        assert [argv[0] for argv in tasks["types"].commands] == ["set", "uv"]

    def test_the_source_travels_with_the_structure(self) -> None:
        """So a denial can name what it read without the reader going to find
        the task."""
        assert read_tasks(tomllib.loads(MISE))["lint"].run == "uv run ruff check ."

    def test_every_gathered_task_reports_whether_it_parsed(self) -> None:
        """PARSEABILITY IS A FACT THE POLICY READS, not an internal detail. A
        body no parser can read is a body nobody can analyse.
        """
        tasks = read_tasks(tomllib.loads(MISE))

        assert all(task.parses for task in tasks.values())

    def test_task_config_is_not_mistaken_for_a_task(self) -> None:
        """[task_config] SITS BESIDE [tasks] AND IS NOT ONE. Treating it as a
        task would evaluate a shell declaration against rules about command
        bodies, and deny the repository for its own interpreter setting.
        """
        assert "task_config" not in read_tasks(tomllib.loads(MISE))

    def test_a_file_with_no_tasks_yields_an_empty_mapping(self) -> None:
        """ABSENCE IS NOT AN ERROR. A repository may legitimately have none."""
        assert read_tasks({}) == {}


class TestReadWorkflow:
    def test_every_action_reference_is_gathered(self) -> None:
        actions = read_workflow_actions(yaml.safe_load(WORKFLOW))

        assert actions == [
            "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683",
            "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        ]

    def test_a_run_step_contributes_no_action(self) -> None:
        """A STEP IS EITHER `uses` OR `run`. Counting a run step would produce a
        reference with no `@` and a denial nobody could act on.
        """
        assert all("@" in action for action in read_workflow_actions(yaml.safe_load(WORKFLOW)))

    def test_the_job_name_is_gathered_not_the_job_id(self) -> None:
        """GitHub REPORTS THE `name` AS THE STATUS CHECK CONTEXT, not the key.

        Gathering `quality-gate` instead of `quality gate` would make the policy
        compare the wrong string and deny a workflow that is correct.
        """
        assert read_ci_job_names(yaml.safe_load(WORKFLOW)) == ["quality gate"]

    def test_a_job_without_a_name_falls_back_to_its_id(self) -> None:
        """GitHub DOES THE SAME, so the gatherer must not drop it."""
        document = yaml.safe_load("jobs:\n  build:\n    runs-on: ubuntu-latest\n")

        assert read_ci_job_names(document) == ["build"]

    def test_a_workflow_with_no_jobs_yields_nothing(self) -> None:
        assert read_ci_job_names({}) == []
        assert read_workflow_actions({}) == []

    def test_a_job_without_steps_yields_no_actions(self) -> None:
        """A JOB MAY CALL A REUSABLE WORKFLOW and have no steps at all."""
        reusable = "jobs:\n  call:\n    uses: org/repo/.github/workflows/x.yml@abc\n"

        assert read_workflow_actions(yaml.safe_load(reusable)) == []


class TestGatherPolicyInput:
    def test_the_whole_repository_becomes_one_document(self, tmp_path: Path) -> None:
        """THE CROSS-FILE SHAPE, which is why this is not Conftest."""
        write_repository(tmp_path)

        gathered = gather_policy_input(tmp_path)

        assert set(gathered.tasks) == {"lint", "types"}
        assert gathered.ci_job_names == ["quality gate"]
        assert gathered.required_contexts == ["quality gate"]
        assert len(gathered.workflow_actions) == 2

    def test_a_tools_block_is_reported(self, tmp_path: Path) -> None:
        """THE FACT THE POLICY NEEDS, not the file. A rule cannot read TOML, so
        the gatherer answers the question the rule actually asks.
        """
        write_repository(tmp_path)
        (tmp_path / "mise.toml").write_text('[tools]\npython = "3.12"\n')

        assert gather_policy_input(tmp_path).has_tools_block is True

    def test_no_tools_block_is_reported_as_false(self, tmp_path: Path) -> None:
        write_repository(tmp_path)

        assert gather_policy_input(tmp_path).has_tools_block is False

    def test_a_missing_workflow_is_not_an_error(self, tmp_path: Path) -> None:
        """ABSENCE MUST BE EVALUABLE. A gate that crashes on a repository
        without CI reports "broken" where it should report "nothing to object
        to", and those are different facts with different remedies.
        """
        write_repository(tmp_path)
        (tmp_path / ".github/workflows/ci.yml").unlink()

        gathered = gather_policy_input(tmp_path)

        assert gathered.ci_job_names == []
        assert gathered.workflow_actions == []

    def test_a_missing_ruleset_is_not_an_error(self, tmp_path: Path) -> None:
        write_repository(tmp_path)
        (tmp_path / "contracts/ruleset-develop-and-main.json").unlink()

        assert gather_policy_input(tmp_path).required_contexts == []

    def test_a_missing_mise_file_is_not_an_error(self, tmp_path: Path) -> None:
        write_repository(tmp_path)
        (tmp_path / "mise.toml").unlink()

        gathered = gather_policy_input(tmp_path)

        assert gathered.tasks == {}
        assert gathered.has_tools_block is False

    def test_an_entirely_empty_directory_yields_an_empty_document(self, tmp_path: Path) -> None:
        """THE DEGENERATE CASE, asserted so the gatherer is total rather than
        merely tolerant of the absences it was tested against.
        """
        gathered = gather_policy_input(tmp_path)

        assert gathered.tasks == {}
        assert gathered.ci_job_names == []
        assert gathered.required_contexts == []
        assert gathered.workflow_actions == []
        assert gathered.has_tools_block is False

    def test_the_document_serialises_for_opa(self, tmp_path: Path) -> None:
        """OPA TAKES JSON ON STDIN, so the model must round-trip through it --
        including the nested task structure the rules read."""
        write_repository(tmp_path)

        restored = json.loads(gather_policy_input(tmp_path).model_dump_json())

        assert restored["ci_job_names"] == ["quality gate"]
        assert restored["tasks"]["lint"]["commands"] == [["uv", "run", "ruff", "check", "."]]
        assert restored["tasks"]["lint"]["parses"] is True


class TestPolicyInputContract:
    def test_unknown_fields_are_rejected(self) -> None:
        """extra="forbid": a field the policies never read is a field somebody
        added expecting it to be evaluated.
        """
        with pytest.raises(ValidationError):
            PolicyInput.model_validate({"tasks": {}, "invented": 1})

    def test_every_field_defaults_to_empty(self) -> None:
        """A DOCUMENT IS CONSTRUCTIBLE FROM NOTHING, so a gatherer that finds no
        files still produces something the policies can evaluate.
        """
        empty = PolicyInput()

        assert empty.tasks == {}
        assert empty.has_tools_block is False

    def test_the_document_is_frozen(self) -> None:
        """Gathered facts are observations; a caller must not edit them between
        gathering and evaluation.

        THE type: ignore IS THE POINT, NOT AN ESCAPE. The pydantic mypy plugin
        knows the field is read-only, so this assignment is a STATIC error as
        well as a runtime one -- and this test asserts the runtime refusal, so
        the line is illegal on purpose.
        """
        with pytest.raises(ValidationError):
            PolicyInput().has_tools_block = True  # type: ignore[misc]
