# src/cs1090a_spec_driven_development/contracts/ruleset.py
# THE BRANCH RULESET, PARSED AT THE BOUNDARY RATHER THAN HAND-WALKED.
#
# --- WHY THIS REPLACES DEFENSIVE GUARDS ---------------------------------------
#
# read_required_contexts used to walk raw JSON with isinstance checks and
# chained .get() defaults. SIX MUTANTS SURVIVED THERE: `or` could become `and`,
# the `{}` and `[]` defaults could be deleted, and nothing objected -- because
# every fixture supplied a well-formed ruleset and the guards existed for input
# nobody had written.
#
# WRITING TESTS FOR THOSE GUARDS WOULD HAVE BEEN THE TREADMILL. The guards ARE
# hand-parsing, and the 2026 position on hand-parsing is unambiguous: pydantic
# is the idiomatic way to "parse, don't validate" in Python, and it should be
# run over ALL data that does not come from your own codebase -- form input,
# JSON from a database, queue messages. A GitHub ruleset is exactly that.
#
# PARSING AT THE BOUNDARY MAKES THOSE MUTANTS UNWRITABLE rather than merely
# detected: there is no isinstance to invert and no default to delete, because
# the shape is declared once and enforced by the library.
#
# --- WHY A TAGGED UNION -------------------------------------------------------
#
# A ruleset carries rules of several types. Only `required_status_checks`
# carries the contexts this project reads; `deletion` and `non_fast_forward`
# carry none, and other types carry parameters of entirely different shapes.
#
# pydantic's own guidance is to prefer a TAGGED union over a plain one, because
# the discriminating field makes both the match and the error message specific.
# `type` is that tag. A rule which is not a status-check rule parses as the
# catch-all and contributes nothing -- which is what the old `or` guard was
# reaching for by hand, and getting wrong in a way no test could see.
#
# LEFT-TO-RIGHT UNION MODE, NOT A DISCRIMINATED UNION, because a true
# discriminated union requires every member to declare a Literal tag and this
# one has a deliberate catch-all. Left-to-right tries the specific shape first
# and falls back, which is the behaviour wanted and is stated explicitly rather
# than left to pydantic's smart-union heuristics.
#
# --- WHY extra IS IGNORED HERE AND FORBIDDEN EVERYWHERE ELSE ------------------
#
# Every internal contract in this repository sets extra="forbid", because a
# field nobody declared is a mistake. THIS MODEL IS DIFFERENT: GitHub owns this
# schema and adds fields whenever it likes. Forbidding them would fail the gate
# on the day GitHub ships a feature nobody here uses -- turning a foreign
# schema's evolution into an outage in our pipeline.
#
# WHAT IS STILL REFUSED IS OUR OWN INCOHERENCE: a status-check rule with no
# parameters, or a required check with no context. The old guards skipped both
# silently, which is worse than failing -- a ruleset claiming to require checks
# and naming none is a configuration error somebody should hear about.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag

STATUS_CHECK_RULE = "required_status_checks"


class ForeignSchema(BaseModel):
    """Base for models describing a document GitHub owns.

    extra="ignore" IS THE DELIBERATE INVERSE of this repository's own contracts.
    See the module header: a foreign schema grows fields on someone else's
    timetable, and treating that as an error makes their release our incident.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")


class RequiredCheck(ForeignSchema):
    """One status check a ruleset demands.

    context IS REQUIRED. A check naming nothing cannot be compared against a CI
    job name, and accepting it would let a ruleset appear to require something
    while requiring nothing.
    """

    context: str


class StatusCheckParameters(ForeignSchema):
    """The parameters of a required-status-checks rule."""

    required_status_checks: list[RequiredCheck] = Field(default_factory=list)


class StatusCheckRule(ForeignSchema):
    """The one rule type carrying the contexts this project reads.

    parameters IS REQUIRED HERE, unlike in the hand-walked version which
    defaulted it to {} and skipped on. A rule of this type with no parameters is
    malformed, and saying so is more useful than quietly contributing nothing.
    """

    type: Literal["required_status_checks"]
    parameters: StatusCheckParameters


class OtherRule(ForeignSchema):
    """Any rule this project does not read.

    THE CATCH-ALL IS DELIBERATE AND NAMED. deletion and non_fast_forward are
    real rules carrying no contexts, and future types will exist that nobody
    here has heard of. Parsing them as "some rule" is accurate; refusing them
    would be a gate that breaks on someone else's roadmap.
    """

    type: str


UNKNOWN_RULE = "_unknown"


def rule_tag(value: Any) -> str:
    """Which arm a rule belongs to, decided by its own `type` field.

    READ BEFORE VALIDATION, WHICH IS THE WHOLE POINT. A rule declaring
    `required_status_checks` is routed to the strict arm and FAILS THERE if its
    parameters are malformed -- it cannot quietly fall through to the catch-all,
    which is what a left-to-right union allowed and what the hand-rolled guards
    did before it.

    THE TWO INPUT SHAPES ARE PYDANTIC'S, not a defensive flourish: a discriminator
    is called with a raw mapping during validation and with a model instance
    during serialisation, so both are read -- in ONE place rather than scattered
    through a hand-walk.
    """
    declared = value.get("type") if isinstance(value, dict) else getattr(value, "type", None)
    return STATUS_CHECK_RULE if declared == STATUS_CHECK_RULE else UNKNOWN_RULE


Rule = Annotated[
    Annotated[StatusCheckRule, Tag(STATUS_CHECK_RULE)] | Annotated[OtherRule, Tag(UNKNOWN_RULE)],
    Discriminator(rule_tag),
]


class Ruleset(ForeignSchema):
    """A GitHub branch ruleset, as far as this project reads it.

    CONSTRUCTIBLE FROM NOTHING, because a repository may have no ruleset and the
    gatherer must still produce something evaluable rather than an exception.
    """

    rules: list[Rule] = Field(default_factory=list)


def required_contexts_of(ruleset: Ruleset) -> list[str]:
    """Every status check the ruleset demands, in declaration order.

    NO GUARDS, BECAUSE THE TYPES ARE THE GUARD. Each item is already a
    StatusCheckRule or it is not, and each check already has a context -- so
    this reads as the sentence it is rather than as a walk through a document
    that might be anything.
    """
    return [
        check.context
        for rule in ruleset.rules
        if isinstance(rule, StatusCheckRule)
        for check in rule.parameters.required_status_checks
    ]
