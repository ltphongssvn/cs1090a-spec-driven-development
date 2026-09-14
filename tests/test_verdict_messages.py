# tests/test_verdict_messages.py
# THE REFUSAL MESSAGES, ASSERTED AS PART OF THE CONTRACT.
#
# WHY. Mutation testing mutated `raise ValueError("check id must not be blank")`
# to `raise ValueError(None)` and the mutant SURVIVED 201 tests. Every one of
# them asserted that a ValidationError was raised and none asserted what it
# said, so the module could have refused every malformed check with a blank
# message and the suite would have reported success.
#
# A MESSAGE IS NOT DECORATION HERE. This module is the one every gate depends
# on: when it refuses, the refusal is the only account anyone gets of why a
# build stopped. `ValueError(None)` renders as "None" in a traceback, which
# costs a bisect to interpret.
#
# THE SAME MUTANT CLASS APPEARS WHEREVER A RAISE IS TESTED ONLY BY ITS TYPE.
# pytest.raises(X) alone is a weak assertion in the sense of section 2.1.2: it
# pins that something went wrong and nothing about what.

import pytest
from pydantic import ValidationError

from cs1090a_spec_driven_development.contracts.verdict import (
    Check,
    CheckVerdict,
    Verdict,
    reject_blank_id,
    reject_duplicate_ids,
)


def check(identifier: str = "a", verdict: CheckVerdict = CheckVerdict.PASS) -> Check:
    return Check(id=identifier, verdict=verdict)


class TestBlankIdMessage:
    def test_the_refusal_states_the_rule(self) -> None:
        """THE MUTANT THAT SURVIVED 201 TESTS.

        Only an assertion on the text distinguishes this from ValueError(None).
        """
        with pytest.raises(ValidationError, match="check id must not be blank"):
            Check(id="   ", verdict=CheckVerdict.PASS)

    def test_a_tab_only_id_produces_the_same_refusal(self) -> None:
        """WHITESPACE IS NOT ONLY THE SPACE CHARACTER, and the message is the
        same one, so the rule reads identically however it was violated."""
        with pytest.raises(ValidationError, match="check id must not be blank"):
            Check(id="\t", verdict=CheckVerdict.PASS)

    def test_a_newline_only_id_produces_the_same_refusal(self) -> None:
        with pytest.raises(ValidationError, match="check id must not be blank"):
            Check(id="\n", verdict=CheckVerdict.PASS)

    def test_calling_the_validator_directly_raises_a_value_error(self) -> None:
        """THE UNDECORATED FUNCTION IS THE ONE MUTMUT MEASURES, so it is called
        directly rather than only through pydantic's wrapping."""
        subject = check()
        blank = subject.model_copy(update={"id": "  "})

        with pytest.raises(ValueError, match="check id must not be blank"):
            reject_blank_id(blank)

    def test_a_valid_id_passes_through_unchanged(self) -> None:
        subject = check(identifier="hours")

        assert reject_blank_id(subject) is subject


class TestDuplicateIdMessage:
    def test_the_refusal_names_the_duplicated_id(self) -> None:
        """WHICH ONE WAS DUPLICATED is the entire value of this message."""
        with pytest.raises(ValidationError, match="duplicate check id: hours"):
            Verdict(
                gate="g",
                subject="s",
                checks=[check(identifier="hours"), check(identifier="hours")],
            )

    def test_the_first_duplicate_encountered_is_the_one_reported(self) -> None:
        """DETERMINISTIC REPORTING. Two different duplicates must not produce a
        message that depends on dictionary ordering."""
        with pytest.raises(ValidationError, match="duplicate check id: a"):
            Verdict(
                gate="g",
                subject="s",
                checks=[
                    check(identifier="a"),
                    check(identifier="b"),
                    check(identifier="a"),
                    check(identifier="b"),
                ],
            )

    def test_calling_the_validator_directly_raises_a_value_error(self) -> None:
        checks = [check(identifier="a"), check(identifier="a")]

        with pytest.raises(ValueError, match="duplicate check id: a"):
            reject_duplicate_ids(checks)

    def test_distinct_ids_pass_through_unchanged(self) -> None:
        checks = [check(identifier="a"), check(identifier="b")]

        assert reject_duplicate_ids(checks) is checks

    def test_a_single_check_is_never_a_duplicate(self) -> None:
        checks = [check(identifier="a")]

        assert reject_duplicate_ids(checks) is checks
