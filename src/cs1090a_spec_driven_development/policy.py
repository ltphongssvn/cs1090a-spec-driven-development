# src/cs1090a_spec_driven_development/policy.py
# THIS REPOSITORY'S CONFIGURATION, GATHERED AS POLICY INPUT.
#
# WHY THIS EXISTS. policies/repository/ can be immaculate and enforce nothing: a
# suite evaluated only against fixtures proves its rules are self-consistent and
# says nothing about the repository. The split is a difference in kind --
#
#   check:policy            are the policies well-formed, idiomatic and tested?
#   check:policy-decisions  does THIS REPOSITORY satisfy them?
#
# --- WHY NOT CONFTEST ---------------------------------------------------------
#
# NEITHER CONFTEST NOR `opa eval` PARSES TOML, and mise.toml carries every task
# body. A gatherer is required whichever engine evaluates.
#
# THE INVARIANTS ARE ALSO CROSS-FILE: "the CI job name must equal the ruleset's
# required context" spans .github/workflows/ci.yml and contracts/. Conftest
# evaluates FILE BY FILE and would never see both at once, so the rule is not
# awkward to express there -- it is inexpressible.
#
# --- TASK BODIES ARRIVE PARSED, NOT AS STRINGS --------------------------------
#
# THIS IS THE SECOND HALF OF A FIX WHOSE FIRST HALF WAS shell.py, and without it
# that module changed nothing: the policy still received `run` as text and still
# asked whether it contained "git " and "| grep". That denied `setup` -- which
# has `git rev-parse` on one line and `ls | grep -v sample` thirty lines away --
# and the parser sitting unused two modules over could not help.
#
# EACH TASK NOW CARRIES ITS PARSED STRUCTURE: whether it parsed at all, the
# argument vector of every command, and the leading command of every pipeline
# stage. A Rego rule asks "is there a pipeline whose first stage is git and
# whose later stage is a parser", which no quoting, comment or line break can
# fool -- because the question is about a tree rather than a substring.
#
# `parses` IS ITSELF A FACT THE POLICY READS. A body no parser can read is a
# body nobody can analyse, review with confidence, or test.
#
# EVERY FILE IS PARSED, NEVER GREPPED, for the same reason: a parser returns a
# structure, and a structure cannot be misread the way a regex can.
#
# THE GATHERER IS TOTAL ABOUT ABSENCE. A repository without a workflow, or
# without a ruleset, must produce a document the policies can evaluate rather
# than an exception. A gate that crashes reports "broken" where it should report
# "nothing to object to", and those have different remedies.

import tomllib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from cs1090a_spec_driven_development.contracts.mise import MiseConfiguration
from cs1090a_spec_driven_development.contracts.ruleset import (
    Ruleset,
    required_contexts_of,
)
from cs1090a_spec_driven_development.shell import TaskBody, parse_body

MISE_FILE = Path("mise.toml")
WORKFLOW_FILE = Path(".github/workflows/ci.yml")
RULESET_FILE = Path("contracts/ruleset-develop-and-main.json")


class PolicyInput(BaseModel):
    """Everything the policies need, in the shape they read it.

    FROZEN, because these are OBSERVATIONS. A caller editing them between
    gathering and evaluation would produce a verdict about a repository that
    does not exist.

    EVERY FIELD DEFAULTS TO EMPTY, so a gatherer finding no files still produces
    something evaluable rather than a half-built object.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tasks: dict[str, TaskBody] = Field(default_factory=dict)
    ci_job_names: list[str] = Field(default_factory=list)
    required_contexts: list[str] = Field(default_factory=list)
    workflow_actions: list[str] = Field(default_factory=list)
    has_tools_block: bool = False


def read_toml(path: Path) -> dict[str, Any]:
    """Parse a TOML file, or report an empty document when absent.

    ABSENCE IS DATA, NOT AN ERROR. See the module header: a missing file must
    still produce something the policies can evaluate.
    """
    if not path.is_file():
        return {}
    return tomllib.loads(path.read_text())


def read_yaml(path: Path) -> dict[str, Any]:
    """Parse a YAML file, or report an empty document when absent.

    safe_load, NEVER load. A workflow file is input; full YAML can construct
    arbitrary Python objects, and a policy gatherer is the last place to hand a
    file that power.
    """
    if not path.is_file():
        return {}
    loaded = yaml.safe_load(path.read_text())
    return loaded if isinstance(loaded, dict) else {}


def read_ruleset(path: Path) -> Ruleset:
    """Parse the branch ruleset, or report an empty one when absent.

    model_validate_json RATHER THAN model_validate(json.loads(...)), which is
    pydantic's documented preference: the JSON is validated internally instead
    of being parsed into a dict first and validated after.

    ABSENCE IS AN EMPTY RULESET, NOT AN ERROR. A repository may legitimately
    have none, and a gate that crashes there reports "broken" where it should
    report "nothing to object to".
    """
    if not path.is_file():
        return Ruleset()
    return Ruleset.model_validate_json(path.read_text())


def read_tasks(mise: dict[str, Any]) -> dict[str, TaskBody]:
    """Each task's body, PARSED.

    [task_config] SITS NEXT TO [tasks] AND IS NOT A TASK. Reading the whole file
    would evaluate the shell declaration against rules about command bodies and
    deny the repository for its own interpreter setting.

    THE PARSE HAPPENS HERE so that every consumer -- the policy engine, the
    verdict, a future report -- sees the same structure rather than each
    re-deriving it from text and disagreeing.
    """
    configuration = MiseConfiguration.model_validate(mise)
    return {name: parse_body(task.run) for name, task in configuration.tasks.items()}


def has_tools_block(mise: dict[str, Any]) -> bool:
    """Whether the toolchain is declared twice.

    THE FACT THE POLICY ASKS FOR, not the file it lives in. A Rego rule cannot
    read TOML, so the question is answered here.
    """
    return MiseConfiguration.model_validate(mise).tools is not None


def read_ci_job_names(workflow: dict[str, Any]) -> list[str]:
    """The names GitHub will report as status check contexts.

    THE `name`, FALLING BACK TO THE KEY -- exactly what GitHub does. Gathering
    `quality-gate` where the job declares `quality gate` would make the policy
    compare the wrong string and deny a correct workflow.
    """
    jobs = workflow.get("jobs", {})
    return [job.get("name", key) for key, job in jobs.items() if isinstance(job, dict)]


def read_workflow_actions(workflow: dict[str, Any]) -> list[str]:
    """Every action reference the workflow depends on.

    ONLY `uses` STEPS. A step is either `uses` or `run`, and counting a run step
    would produce a reference with no `@` and a denial nobody could act on.
    """
    references: list[str] = []
    for job in workflow.get("jobs", {}).values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps", []):
            if isinstance(step, dict) and "uses" in step:
                references.append(step["uses"])
    return references


def gather_policy_input(root: Path) -> PolicyInput:
    """Read the repository's configuration into one document.

    ONE DOCUMENT IS THE POINT. Cross-file invariants -- the CI job name against
    the ruleset's required context -- exist only when both files are visible at
    once, which is why this is not a per-file check.
    """
    mise = read_toml(root / MISE_FILE)
    workflow = read_yaml(root / WORKFLOW_FILE)
    ruleset = read_ruleset(root / RULESET_FILE)

    return PolicyInput(
        tasks=read_tasks(mise),
        ci_job_names=read_ci_job_names(workflow),
        required_contexts=required_contexts_of(ruleset),
        workflow_actions=read_workflow_actions(workflow),
        has_tools_block=has_tools_block(mise),
    )
