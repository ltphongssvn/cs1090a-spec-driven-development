# tests/test_policy_decisions.py
# EVALUATING THIS REPOSITORY AGAINST ITS OWN POLICIES.
#
# WHAT THIS ADDS TO tests/test_policy_input.py. That file proves the gatherer
# reads the configuration correctly. This one proves the gathered document is
# handed to OPA, that OPA's answer becomes a Verdict, and that the exit code
# follows the verdict rather than the other way round.
#
# --- WHY opa IS INVOKED FOR REAL ----------------------------------------------
#
# A STUBBED ENGINE WOULD TEST THE STUB. The value of this gate is that a real
# policy engine reads a real document; mocking the subprocess would assert that
# we can build a command line, which is not the claim being made. opa is on PATH
# because the flake puts it there, so the test is hermetic in the sense that
# matters: no network, no credentials, a binary pinned by flake.lock.
#
# --- WHY THE RECORD IS READ THROUGH THE MODEL ---------------------------------
#
# The first version returned `dict[str, object]` from a json.loads, and mypy
# reported five errors: callers iterating `object`, and an Any escaping a
# function that claimed to return something specific.
#
# ANNOTATING IT BETTER WOULD HAVE BEEN THE WEAKER FIX. Parsing the file through
# Verdict asserts that what the gate WROTE is a valid Verdict -- not merely that
# it is JSON with the keys this test happens to read. A record that no longer
# satisfies its own contract now fails here rather than being read as a dict.

from pathlib import Path

import pytest

from cs1090a_spec_driven_development.contracts.verdict import (
    CheckVerdict,
    GateVerdict,
    Verdict,
)
from cs1090a_spec_driven_development.git_topology import (
    repository_root as git_repository_root,
)
from cs1090a_spec_driven_development.policy import PolicyInput
from cs1090a_spec_driven_development.policy_gate import (
    POLICY_DIRECTORY,
    build_verdict,
    evaluate_policies,
    read_decision,
    require_policies,
    run_policy_gate,
)
from cs1090a_spec_driven_development.shell import TaskBody

CLEAN = PolicyInput(
    tasks={
        "lint": TaskBody(
            run="uv run ruff check .",
            commands=[["uv", "run", "ruff", "check", "."]],
        )
    },
    ci_job_names=["quality gate"],
    required_contexts=["quality gate"],
    workflow_actions=["actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683"],
    has_tools_block=False,
)

TOOLS_BLOCK_DENIAL = "mise.toml declares a [tools] block; flake.nix is the declaration"


def repository_root() -> Path:
    """The real working tree, ASKED OF GIT rather than inferred from a path.

    DERIVING IT FROM __file__ WAS WRONG, AND MUTATION TESTING PROVED IT. mutmut
    copies the package to ./mutants and runs the suite from there, so __file__
    resolved to a scratch tree holding Python source and no policies/ -- every
    policy test then failed on a refusal that was itself correct.

    git_topology.repository_root ANSWERS FROM ANYWHERE INSIDE THE REPOSITORY,
    validates the result as a directory that exists, and lets an operator name
    a staged tree explicitly. See that module for why one combined rev-parse,
    and why no manual path traversal.
    """
    return git_repository_root()


def policies() -> Path:
    return repository_root() / POLICY_DIRECTORY


def verdict_at(root: Path) -> Verdict:
    """The recorded verdict, PARSED THROUGH ITS CONTRACT.

    A record that is JSON but not a Verdict fails here, which is the stronger
    assertion: the gate's own output must satisfy the model every other gate in
    this repository emits.
    """
    recorded = root / ".artifacts/verdicts/repository_policy.json"
    return Verdict.model_validate_json(recorded.read_text())


def informational(verdict: Verdict) -> dict[str, int | str | None]:
    return {
        check.id: check.observed
        for check in verdict.checks
        if check.verdict is CheckVerdict.INFORMATIONAL
    }


def failing(verdict: Verdict) -> list[str]:
    return [str(check.observed) for check in verdict.checks if check.verdict is CheckVerdict.FAIL]


class TestEvaluation:
    def test_a_conforming_document_is_allowed(self) -> None:
        """THE REAL ENGINE, THE REAL POLICIES, A CONFORMING DOCUMENT."""
        assert evaluate_policies(CLEAN, policies=policies()) == []

    def test_a_tools_block_is_denied_by_the_real_engine(self) -> None:
        """END TO END: a gathered fact reaches Rego and returns as prose."""
        offending = CLEAN.model_copy(update={"has_tools_block": True})

        assert evaluate_policies(offending, policies=policies()) == [TOOLS_BLOCK_DENIAL]

    def test_an_unpinned_action_is_denied(self) -> None:
        offending = CLEAN.model_copy(update={"workflow_actions": ["actions/checkout@v4"]})

        decision = evaluate_policies(offending, policies=policies())

        assert decision == ["action 'actions/checkout@v4' is not pinned to a commit sha"]

    def test_several_violations_are_all_returned(self) -> None:
        """NO SHORT-CIRCUITING, for the same reason the FMLA rules do not: one
        fix per run is a treadmill.
        """
        offending = CLEAN.model_copy(
            update={
                "has_tools_block": True,
                "workflow_actions": ["a/b@v1"],
                "ci_job_names": ["build"],
            }
        )

        assert len(evaluate_policies(offending, policies=policies())) == 3

    def test_the_decision_is_sorted_for_a_stable_record(self) -> None:
        """A REGO SET HAS NO ORDER. Emitting it unsorted makes the recorded
        verdict differ between runs over identical input, destroying the
        diffability the record exists for.
        """
        offending = CLEAN.model_copy(update={"workflow_actions": ["z/z@v1", "a/a@v1"]})

        decision = evaluate_policies(offending, policies=policies())

        assert decision == sorted(decision)
        assert len(decision) == 2


class TestRefusals:
    def test_a_missing_policy_directory_raises_rather_than_allowing(self, tmp_path: Path) -> None:
        """THE MOST DANGEROUS FAILURE MODE. An engine with no policies denies
        nothing, which is indistinguishable from a conforming repository -- and
        this project has already watched a gate report green over an empty
        measurement twice.
        """
        with pytest.raises(FileNotFoundError, match="no policies found"):
            evaluate_policies(CLEAN, policies=tmp_path / "absent")

    def test_a_directory_with_no_rego_files_is_refused(self, tmp_path: Path) -> None:
        """EXISTING IS NOT THE SAME AS CONTAINING POLICIES."""
        (tmp_path / "policies").mkdir()

        with pytest.raises(FileNotFoundError, match="without evaluating anything"):
            require_policies(tmp_path / "policies")

    def test_a_directory_holding_policies_is_accepted(self) -> None:
        assert require_policies(policies()) == policies()


class TestDecisionParsing:
    def test_an_undefined_query_is_an_empty_decision(self) -> None:
        """OPA OMITS `result` ENTIRELY when a query is undefined, and for a
        partial set rule that means nothing was denied -- not that something
        went wrong.
        """
        assert read_decision("{}") == []

    def test_an_empty_result_list_is_an_empty_decision(self) -> None:
        assert read_decision('{"result": []}') == []

    def test_the_deny_set_is_extracted_from_the_envelope(self) -> None:
        envelope = '{"result": [{"expressions": [{"value": ["a", "b"]}]}]}'

        assert read_decision(envelope) == ["a", "b"]


class TestVerdict:
    def test_a_conforming_repository_exits_zero(self, tmp_path: Path) -> None:
        assert run_policy_gate(tmp_path, policies=policies()) == 0

    def test_the_verdict_is_recorded_as_data(self, tmp_path: Path) -> None:
        run_policy_gate(tmp_path, policies=policies())

        recorded = verdict_at(tmp_path)

        assert recorded.gate == "repository_policy"
        assert recorded.verdict is GateVerdict.PASS

    def test_a_violating_repository_exits_one(self, tmp_path: Path) -> None:
        """A REPOSITORY WITH A [tools] BLOCK, evaluated where it actually is."""
        (tmp_path / "mise.toml").write_text('[tools]\npython = "3.12"\n')

        assert run_policy_gate(tmp_path, policies=policies()) == 1

    def test_a_violation_is_named_in_the_record(self, tmp_path: Path) -> None:
        (tmp_path / "mise.toml").write_text('[tools]\npython = "3.12"\n')

        run_policy_gate(tmp_path, policies=policies())
        recorded = verdict_at(tmp_path)

        assert recorded.verdict is GateVerdict.FAIL
        assert recorded.reasons == ["policy_violation_0"]

    def test_each_violation_becomes_its_own_check(self, tmp_path: Path) -> None:
        """ONE CHECK PER VIOLATION, so the record is queryable rather than a
        paragraph. A single check carrying a joined string would make the count
        impossible to read without parsing prose.
        """
        (tmp_path / "mise.toml").write_text('[tools]\npython = "3.12"\n')

        run_policy_gate(tmp_path, policies=policies())

        assert failing(verdict_at(tmp_path)) == [TOOLS_BLOCK_DENIAL]

    def test_a_passing_gate_carries_a_deciding_check(self, tmp_path: Path) -> None:
        """WITHOUT ONE THE VERDICT WOULD BE UNKNOWN. The contract derives UNKNOWN
        from informational checks alone, which is right for a gate that measured
        nothing and wrong for one that evaluated the repository and found it
        clean.
        """
        run_policy_gate(tmp_path, policies=policies())
        recorded = verdict_at(tmp_path)
        deciding = [
            check.id for check in recorded.checks if check.verdict is not CheckVerdict.INFORMATIONAL
        ]

        assert deciding == ["no_policy_violations"]

    def test_what_was_examined_is_recorded_as_context(self, tmp_path: Path) -> None:
        """THE ANTI-VACUITY CLAUSE. Zero violations over zero tasks is not the
        same fact as zero violations over twenty-five, and a reader must be able
        to tell them apart without re-running the gate.
        """
        run_policy_gate(tmp_path, policies=policies())

        assert informational(verdict_at(tmp_path)) == {
            "tasks_evaluated": 0,
            "workflow_actions_evaluated": 0,
            "required_contexts_evaluated": 0,
        }

    def test_the_real_repository_reports_what_it_examined(self) -> None:
        """THE SAME GATE OVER THE REAL TREE records non-zero counts, which is
        what distinguishes it from the empty-directory case above.
        """
        run_policy_gate(repository_root(), policies=policies())
        counts = informational(verdict_at(repository_root()))

        assert counts["tasks_evaluated"] != 0
        assert counts["workflow_actions_evaluated"] != 0
        assert counts["required_contexts_evaluated"] != 0


class TestThisRepository:
    def test_this_repository_satisfies_its_own_policies(self) -> None:
        """THE POINT OF THE WHOLE EXERCISE, asserted against the real tree.

        Not a fixture: the actual mise.toml, the actual workflow, the actual
        ruleset. If this fails, the repository has violated a rule it published
        about itself -- which is exactly the signal the gate exists to give.
        """
        assert run_policy_gate(repository_root(), policies=policies()) == 0


class TestEvidenceFields:
    """The values a record carries, not merely the verdict it reaches.

    MUTATION TESTING FOUND ALL OF THESE BLANKABLE. A verdict that says FAIL
    without saying what failed, or PASS without saying what was examined, is the
    console output this project replaced with documents.
    """

    def test_a_violation_check_states_what_was_expected(self) -> None:
        verdict = build_verdict(CLEAN, [TOOLS_BLOCK_DENIAL])
        failing = [check for check in verdict.checks if check.verdict is CheckVerdict.FAIL]

        assert failing[0].expected == "no violation"

    def test_a_violation_check_carries_the_denial_as_observed(self) -> None:
        """THE DENIAL IS THE OBSERVATION. Without it the record says something
        failed and not what -- which costs the reader the investigation."""
        verdict = build_verdict(CLEAN, [TOOLS_BLOCK_DENIAL])
        failing = [check for check in verdict.checks if check.verdict is CheckVerdict.FAIL]

        assert failing[0].observed == TOOLS_BLOCK_DENIAL

    def test_each_violation_becomes_its_own_check(self) -> None:
        """ONE CHECK PER VIOLATION, so the record is queryable rather than a
        paragraph. A single check carrying a joined string would make the count
        unreadable without parsing prose."""
        verdict = build_verdict(CLEAN, ["first denial", "second denial"])
        failing = [check for check in verdict.checks if check.verdict is CheckVerdict.FAIL]

        assert [check.observed for check in failing] == ["first denial", "second denial"]

    def test_violation_ids_are_distinct_and_ordered(self) -> None:
        """CHECK IDS MUST BE UNIQUE WITHIN A VERDICT -- the contract enforces it
        -- and two violations are two facts rather than one repeated."""
        verdict = build_verdict(CLEAN, ["first denial", "second denial"])
        failing = [check.id for check in verdict.checks if check.verdict is CheckVerdict.FAIL]

        assert failing == ["policy_violation_0", "policy_violation_1"]

    def test_the_conformance_check_reports_zero_against_zero(self) -> None:
        """observed AND expected, both of which mutated to None and survived."""
        verdict = build_verdict(CLEAN, [])
        passing = [check for check in verdict.checks if check.verdict is CheckVerdict.PASS]

        assert (passing[0].observed, passing[0].expected) == (0, 0)

    def test_the_conformance_check_is_named(self) -> None:
        verdict = build_verdict(CLEAN, [])
        passing = [check.id for check in verdict.checks if check.verdict is CheckVerdict.PASS]

        assert passing == ["no_policy_violations"]

    def test_a_failing_verdict_carries_no_conformance_check(self) -> None:
        """A RECORD CLAIMING BOTH WOULD CONTRADICT ITSELF: the gate cannot have
        found no violations and also listed one."""
        verdict = build_verdict(CLEAN, ["a denial"])

        assert "no_policy_violations" not in [check.id for check in verdict.checks]

    def test_a_passing_verdict_carries_exactly_one_deciding_check(self) -> None:
        """WITHOUT A DECIDING CHECK the contract derives UNKNOWN -- right for a
        gate that measured nothing, wrong for one that examined the repository
        and found it clean."""
        verdict = build_verdict(CLEAN, [])
        deciding = [
            check.id for check in verdict.checks if check.verdict is not CheckVerdict.INFORMATIONAL
        ]

        assert deciding == ["no_policy_violations"]

    def test_the_context_counts_come_from_the_document(self) -> None:
        """THE ANTI-VACUITY EVIDENCE. Zero violations over zero tasks is not the
        same fact as zero violations over twenty-five, and a reader must be able
        to tell them apart without re-running the gate."""
        verdict = build_verdict(CLEAN, [])
        context = {
            check.id: check.observed
            for check in verdict.checks
            if check.verdict is CheckVerdict.INFORMATIONAL
        }

        assert context == {
            "tasks_evaluated": len(CLEAN.tasks),
            "workflow_actions_evaluated": len(CLEAN.workflow_actions),
            "required_contexts_evaluated": len(CLEAN.required_contexts),
        }

    def test_the_context_counts_are_present_on_a_failing_verdict_too(self) -> None:
        """EVIDENCE MATTERS MOST WHEN THE GATE FAILED, so the counts must not be
        reserved for the passing case."""
        verdict = build_verdict(CLEAN, ["a denial"])
        context = {
            check.id for check in verdict.checks if check.verdict is CheckVerdict.INFORMATIONAL
        }

        assert context == {
            "tasks_evaluated",
            "workflow_actions_evaluated",
            "required_contexts_evaluated",
        }

    def test_the_verdict_names_the_gate_and_its_subject(self) -> None:
        """A RECORD THAT DOES NOT SAY WHAT IT JUDGED cannot be filed beside the
        others, and this repository now writes one file per gate."""
        verdict = build_verdict(CLEAN, [])

        assert verdict.gate == "repository_policy"
        assert verdict.subject == "repository configuration"
