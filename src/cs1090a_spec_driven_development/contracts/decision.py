# src/cs1090a_spec_driven_development/contracts/decision.py
# OPA'S ANSWER, PARSED AT THE BOUNDARY RATHER THAN NAVIGATED BY HAND.
#
# --- WHY THIS EXISTS ----------------------------------------------------------
#
# read_decision read the envelope with one guarded `.get("result", [])` followed
# by three UNGUARDED subscripts -- results[0]["expressions"][0]["value"]. Two
# mutants lived in the guard, and the subscripts had no guard at all, so the two
# halves of one function disagreed about how much to trust the same document.
#
# THIS IS THE RULESET LESSON, APPLIED WHERE IT WAS MISSED. pydantic is the
# idiomatic way to parse rather than validate data that does not come from your
# own codebase, and opa's output is exactly that. Declaring the shape once
# removes the defaults a mutant can delete AND the subscripts that would raise
# an IndexError naming nothing.
#
# THE SAME MISTAKE TWICE IS THE REAL FINDING. The ruleset was fixed, this was
# not, and the branch has now repeated "fixed one call site, left the concept"
# for a third time -- locators, then policy paths, now envelopes.
#
# --- WHAT OPA ACTUALLY SENDS --------------------------------------------------
#
# MEASURED, NOT ASSUMED. `opa eval --format json` on an UNDEFINED query returns
# `{}` -- no `result` key whatsoever -- which for a partial set rule means
# nothing was denied rather than that anything went wrong. On a defined query it
# returns one result per expression, each carrying the value.
#
# EVERY FIELD IS THEREFORE OPTIONAL WITH AN EMPTY DEFAULT, and an absent or null
# result is a clean empty decision rather than a parse error.
#
# extra="ignore" BECAUSE OPA OWNS THIS SCHEMA. It adds `metrics`, `explanation`
# and more under flags this gate does not pass, and forbidding them would make
# an unrelated opa feature break our pipeline.

from pydantic import BaseModel, ConfigDict, Field


class ForeignSchema(BaseModel):
    """Base for models describing a document another tool owns.

    THE DELIBERATE INVERSE of this repository's own contracts, which forbid
    extra fields. A foreign schema grows on someone else's timetable, and
    treating that as an error makes their release our incident.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")


class Expression(ForeignSchema):
    """One expression's value within a result.

    THE VALUE IS THE DENY SET. A partial set rule yields a list of strings; an
    empty default covers the shape where the rule matched nothing.
    """

    value: list[str] = Field(default_factory=list)


class DecisionResult(ForeignSchema):
    """One result from an evaluation, carrying its expressions."""

    expressions: list[Expression] = Field(default_factory=list)


class DecisionEnvelope(ForeignSchema):
    """What `opa eval --format json` returns.

    result IS OPTIONAL BECAUSE OPA OMITS IT ENTIRELY for an undefined query --
    measured, not assumed. For a partial set rule that means nothing was denied,
    which is a decision rather than a failure.
    """

    result: list[DecisionResult] = Field(default_factory=list)


def denials_of(envelope: DecisionEnvelope) -> list[str]:
    """Every denial the engine reported, flattened in order.

    NO SUBSCRIPTS AND NO GUARDS, because the types are both. An envelope with no
    result, a result with no expressions, or an expression with no value each
    contribute nothing -- which is what an empty decision means, expressed as
    iteration rather than as a chain of defensive lookups.
    """
    return [
        denial
        for result in envelope.result
        for expression in result.expressions
        for denial in expression.value
    ]
