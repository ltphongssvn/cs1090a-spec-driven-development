# tests/test_ruleset_contract.py
# THE BRANCH RULESET, PARSED AT THE BOUNDARY RATHER THAN HAND-WALKED.
#
# --- WHY THIS REPLACES DEFENSIVE GUARDS ---------------------------------------
#
# read_required_contexts used to walk raw JSON with isinstance checks and
# chained .get() defaults. SIX MUTANTS SURVIVED THERE: `or` could become `and`,
# `{}` and `[]` defaults could be deleted, and nothing objected -- because every
# fixture supplied a well-formed ruleset and the guards existed for input nobody
# had written.
#
# WRITING TESTS FOR THOSE GUARDS WOULD HAVE BEEN THE TREADMILL. The guards are
# hand-parsing, and the 2026 position on hand-parsing is unambiguous: pydantic
# is the idiomatic way to "parse, don't validate" in Python, and it should be
# run over ALL data that does not come from your own codebase. A GitHub ruleset
# is exactly that.
#
# PARSING AT THE BOUNDARY MAKES THE MUTANTS UNWRITABLE rather than merely
# detected: there is no isinstance to invert and no default to delete, because
# the shape is declared once and enforced by the library.
#
# --- WHY A TAGGED UNION -------------------------------------------------------
#
# A ruleset carries rules of several types. Only `required_status_checks`
# carries the contexts this project reads; `deletion` and `non_fast_forward`
# carry none, and other types carry parameters of entirely different shapes.
#
# pydantic's guidance is to use a TAGGED union rather than a plain one, because
# the discriminating field makes both the match and the error message specific.
# A rule that is not a status-check rule parses as the catch-all and contributes
# nothing, which is the behaviour the old `or` guard was reaching for by hand.
#
# --- WHY extra IS IGNORED HERE AND FORBIDDEN ELSEWHERE ------------------------
#
# Every internal contract in this repository sets extra="forbid", because a
# field nobody declared is a mistake. THIS MODEL IS DIFFERENT: GitHub owns the
# ruleset schema and adds fields whenever it likes. Forbidding them would make
# this gate fail on the day GitHub ships a feature nobody here uses.

import json

import pytest
from pydantic import ValidationError

from cs1090a_spec_driven_development.contracts.ruleset import (
    UNKNOWN_RULE,
    OtherRule,
    Ruleset,
    StatusCheckRule,
    required_contexts_of,
    rule_tag,
)

REAL = """
{
  "name": "develop-and-main-protection",
  "target": "branch",
  "enforcement": "active",
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "required_status_checks": [{"context": "quality gate"}]
      }
    }
  ]
}
"""


class TestParsingTheRealShape:
    def test_the_committed_ruleset_shape_parses(self) -> None:
        """THE SHAPE THIS REPOSITORY ACTUALLY COMMITS, not an invented one."""
        parsed = Ruleset.model_validate_json(REAL)

        assert len(parsed.rules) == 3

    def test_the_required_contexts_are_read(self) -> None:
        assert required_contexts_of(Ruleset.model_validate_json(REAL)) == ["quality gate"]

    def test_rules_carrying_no_contexts_contribute_nothing(self) -> None:
        """deletion AND non_fast_forward PROTECT WITHOUT REQUIRING A CHECK, so
        reading them as though they did would have to invent a value."""
        only_protective = '{"rules": [{"type": "deletion"}, {"type": "non_fast_forward"}]}'

        assert required_contexts_of(Ruleset.model_validate_json(only_protective)) == []

    def test_an_empty_ruleset_requires_nothing(self) -> None:
        assert required_contexts_of(Ruleset.model_validate_json("{}")) == []

    def test_several_required_checks_are_all_read(self) -> None:
        """ONE MESSAGE PER MISSING CHECK depends on all of them being read."""
        document = json.dumps(
            {
                "rules": [
                    {
                        "type": "required_status_checks",
                        "parameters": {
                            "required_status_checks": [
                                {"context": "quality gate"},
                                {"context": "security"},
                            ]
                        },
                    }
                ]
            }
        )

        assert required_contexts_of(Ruleset.model_validate_json(document)) == [
            "quality gate",
            "security",
        ]


class TestGitHubMayAddFields:
    def test_an_unknown_rule_type_is_tolerated(self) -> None:
        """GitHub OWNS THIS SCHEMA. A rule type nobody here uses must not fail
        the gate -- that would break on the day a feature ships.
        """
        document = '{"rules": [{"type": "some_future_rule", "parameters": {"x": 1}}]}'

        assert required_contexts_of(Ruleset.model_validate_json(document)) == []

    def test_unknown_top_level_fields_are_tolerated(self) -> None:
        document = '{"rules": [], "invented_by_github": true, "id": 42}'

        assert Ruleset.model_validate_json(document).rules == []

    def test_unknown_fields_beside_a_required_check_are_tolerated(self) -> None:
        """A CHECK MAY CARRY integration_id AND MORE. Only the context is read."""
        document = json.dumps(
            {
                "rules": [
                    {
                        "type": "required_status_checks",
                        "parameters": {
                            "required_status_checks": [
                                {"context": "quality gate", "integration_id": 15368}
                            ]
                        },
                    }
                ]
            }
        )

        assert required_contexts_of(Ruleset.model_validate_json(document)) == ["quality gate"]


class TestMalformedInput:
    def test_a_status_check_rule_without_parameters_is_refused(self) -> None:
        """THE OLD GUARD SKIPPED THIS SILENTLY, which is worse: a ruleset
        claiming to require checks and naming none is a configuration error
        somebody should hear about, not a rule quietly contributing nothing.
        """
        with pytest.raises(ValidationError):
            Ruleset.model_validate_json('{"rules": [{"type": "required_status_checks"}]}')

    def test_a_check_without_a_context_is_refused(self) -> None:
        document = json.dumps(
            {
                "rules": [
                    {
                        "type": "required_status_checks",
                        "parameters": {"required_status_checks": [{"integration_id": 1}]},
                    }
                ]
            }
        )

        with pytest.raises(ValidationError):
            Ruleset.model_validate_json(document)

    def test_rules_that_are_not_objects_are_refused(self) -> None:
        """WHERE THE isinstance GUARD USED TO BE. The refusal is now the
        library's, and it names the field and the offending value.
        """
        with pytest.raises(ValidationError):
            Ruleset.model_validate_json('{"rules": ["deletion", 7, null]}')

    def test_a_rule_without_a_type_is_refused(self) -> None:
        """THE DISCRIMINATOR IS REQUIRED. Without it nothing can decide which
        shape a rule is, and guessing is how a status-check rule gets read as a
        deletion.
        """
        with pytest.raises(ValidationError):
            Ruleset.model_validate_json('{"rules": [{"parameters": {}}]}')

    def test_a_refusal_names_the_offending_path(self) -> None:
        """A VALIDATION ERROR THAT DOES NOT SAY WHERE costs the reader the whole
        investigation -- the complaint made of hand-rolled guards is that they
        raise without a hint that the root problem is the document's shape.
        """
        with pytest.raises(ValidationError, match="rules"):
            Ruleset.model_validate_json('{"rules": [7]}')


class TestTheContract:
    def test_a_ruleset_is_frozen(self) -> None:
        parsed = Ruleset.model_validate_json(REAL)

        with pytest.raises(ValidationError):
            parsed.rules = []  # type: ignore[misc]

    def test_a_ruleset_is_constructible_from_nothing(self) -> None:
        """A REPOSITORY MAY HAVE NO RULESET, and the gatherer must still produce
        something evaluable rather than an exception."""
        assert Ruleset().rules == []


class TestSerialisation:
    """A discriminator runs in BOTH directions, and only one was tested.

    pydantic USES CALLABLE DISCRIMINATORS FOR SERIALISATION, handing them a
    model instance rather than a mapping. Its documentation is explicit that
    failing to account for both yields warnings when dumping and runtime errors
    when validating -- so the branch is required, and untested it held three
    mutants including one reading the wrong attribute name entirely.

    THE ROUND TRIP IS THE SANCTIONED CHECK: dump, reparse, compare.
    """

    def test_a_parsed_ruleset_round_trips(self) -> None:
        original = Ruleset.model_validate_json(REAL)

        restored = Ruleset.model_validate_json(original.model_dump_json())

        assert required_contexts_of(restored) == required_contexts_of(original)

    def test_the_status_check_rule_survives_the_round_trip(self) -> None:
        """THE STRICT ARM SPECIFICALLY. If the discriminator misread a model's
        tag, this rule would return as the catch-all and its contexts would
        vanish -- a ruleset that silently stopped requiring anything.
        """
        original = Ruleset.model_validate_json(REAL)

        restored = Ruleset.model_validate_json(original.model_dump_json())
        strict = [rule for rule in restored.rules if isinstance(rule, StatusCheckRule)]

        assert len(strict) == 1
        assert strict[0].parameters.required_status_checks[0].context == "quality gate"

    def test_the_other_rules_survive_the_round_trip(self) -> None:
        original = Ruleset.model_validate_json(REAL)

        restored = Ruleset.model_validate_json(original.model_dump_json())
        others = [rule for rule in restored.rules if isinstance(rule, OtherRule)]

        assert sorted(rule.type for rule in others) == ["deletion", "non_fast_forward"]

    def test_the_tag_is_read_from_a_model_instance(self) -> None:
        """THE SERIALISATION BRANCH, CALLED DIRECTLY."""
        rule = StatusCheckRule.model_validate(
            {
                "type": "required_status_checks",
                "parameters": {"required_status_checks": [{"context": "quality gate"}]},
            }
        )

        assert rule_tag(rule) == "required_status_checks"

    def test_the_tag_of_an_unknown_model_is_the_catch_all(self) -> None:
        assert rule_tag(OtherRule(type="deletion")) == UNKNOWN_RULE

    def test_the_tag_is_read_from_a_mapping(self) -> None:
        """THE VALIDATION BRANCH, for symmetry: a test covering one direction is
        not a test of the other."""
        assert rule_tag({"type": "required_status_checks"}) == "required_status_checks"

    def test_a_value_that_is_neither_falls_to_the_catch_all(self) -> None:
        """A BARE SCALAR WHERE A RULE BELONGS routes to the catch-all, which
        refuses it -- rather than raising inside the discriminator, where the
        error would name nothing useful."""
        assert rule_tag(7) == UNKNOWN_RULE
