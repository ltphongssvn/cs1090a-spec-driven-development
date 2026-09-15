# src/cs1090a_spec_driven_development/contracts/mise.py
# THE TASK FILE, PARSED AT THE BOUNDARY RATHER THAN READ BY HAND.
#
# --- WHY THIS EXISTS ----------------------------------------------------------
#
# read_tasks used `str(body.get("run", ""))` behind an `isinstance(body, dict)`
# guard -- three mutants in the default, and a guarded lookup sitting beside
# unguarded assumptions about a hand-written TOML file.
#
# mise.toml IS EXTERNAL INPUT, so guarding is right; doing it at the point of
# use is not. pydantic is the idiomatic way to parse rather than validate data
# that does not come from your own codebase, and declaring the shape once
# removes both the defaults a mutant can delete and the type checks scattered
# through the reader.
#
# THE FOURTH INSTANCE OF ONE LESSON. This branch has now fixed locators, policy
# paths and opa's envelope the same way, each time after the previous fix was
# applied to a single call site rather than to the concept. This is the last
# place the pattern appears.
#
# --- WHY extra IS IGNORED -----------------------------------------------------
#
# mise owns this schema. A task carries description, depends, usage, sources,
# outputs, and whatever mise adds next -- none of which this gate reads.
# Forbidding them would turn a mise release into an outage in our pipeline,
# which is the opposite of what a gate is for.
#
# [task_config] IS DELIBERATELY UNMODELLED. It sits beside [tasks] and is not
# one; reading it as a task would evaluate a shell declaration against rules
# about command bodies and deny the repository for its own interpreter setting.

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ForeignSchema(BaseModel):
    """Base for models describing a document another tool owns.

    THE DELIBERATE INVERSE of this repository's own contracts, which forbid
    extra fields because a field nobody declared is a mistake. A foreign schema
    grows on someone else's timetable.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")


class MiseTask(ForeignSchema):
    """One task as mise.toml declares it.

    run DEFAULTS TO EMPTY because a task may legitimately declare none -- an
    alias, or a placeholder carrying only a description. All 25 tasks in this
    repository declare one, which is exactly why the old `.get("run", "")`
    default went unexercised and held three mutants.
    """

    run: str = ""


class MiseConfiguration(ForeignSchema):
    """The parts of mise.toml this gate reads.

    tools IS MODELLED ONLY TO BE DETECTED. The policy asks whether the toolchain
    is declared twice, and flake.nix is the single declaration -- so its
    PRESENCE is the fact, and its contents are none of this gate's business.
    """

    tasks: dict[str, MiseTask] = Field(default_factory=dict)
    tools: dict[str, Any] | None = None
