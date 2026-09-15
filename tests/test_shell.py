# tests/test_shell.py
# TASK BODIES, PARSED INTO STRUCTURE BEFORE A POLICY EVER SEES THEM.
#
# --- THE ROAD HERE, BECAUSE IT DECIDES THE DESIGN -----------------------------
#
# ATTEMPT ONE: Rego asked whether a body contained "git " and "| grep". It
# denied `setup`, wrongly: that task has `git rev-parse` on one line and
# `ls | grep -v sample` on another, thirty lines apart.
#
# ATTEMPT TWO: correlate per line. Still substring matching -- it fixes that
# example and leaves quoted text and `;`-separated commands for next time. The
# 2026 consensus on the technique is blunt: static pattern matching on shell
# without token awareness yields frequent false positives and negatives.
#
# ATTEMPT THREE: tokenise with shlex. MEASURED AGAINST THE REAL mise.toml AND
# REJECTED -- 16 lines raised, and nested substitution was destroyed:
#
#   root="$(cd "$(dirname "$common")" && pwd)"
#     -> ['root=$(cd $', '(', 'dirname', '$common', ')', ' && pwd)']
#
# ATTEMPT FOUR, AND THE ONE HERE: bashlex, a transliteration of GNU bash's own
# parser producing a real AST. Measured too -- it reads 19 of 25 bodies and
# fails on 6.
#
# --- WHAT THE FAILURES REVEALED -----------------------------------------------
#
# The six are repo:configure, setup, start:check, start:here, worktree:add and
# worktree:remove. Every one contains real shell logic: nested substitution,
# `case` patterns, conditionals. The other nineteen parse instantly because they
# are single invocations.
#
# THE ROOT CAUSE IS NOT THE PARSER. It is that logic lives in task bodies at
# all. A better parser would only let us keep the thing that needs removing --
# and this project has twice reached the same conclusion, for authoring and for
# gates: put the logic in tested Python and leave the task a single invocation.
#
# SO PARSEABILITY IS ITSELF THE RULE. A body a bash parser cannot read is a body
# nobody can analyse, review with confidence, or test. `parses` is therefore a
# reported fact rather than an internal detail, and an unparseable body is a
# policy violation rather than a crash.
#
# THE MODULE NEVER RAISES ON BAD INPUT. A task body is input; input can be
# anything. Reporting "this did not parse" keeps the distinction between "the
# repository has a problem" and "the gate is broken".

import pytest

from cs1090a_spec_driven_development.shell import (
    TaskBody,
    commands_in,
    parse_body,
    pipelines_in,
)

SINGLE = "uv run ruff check ."
GUARDED = "set -euo pipefail\nuv run mypy src\nuv run mypy tests"
PIPED = "uv run mutmut results | grep survived | awk '{print $1}'"
NESTED = 'root="$(cd "$(dirname "$common")" && pwd)"'
CASE = 'case "$slug" in\n  *[!a-z0-9-]*) exit 1 ;;\nesac'


class TestParsing:
    def test_a_single_invocation_parses(self) -> None:
        assert parse_body(SINGLE).parses is True

    def test_a_guarded_multi_command_body_parses(self) -> None:
        assert parse_body(GUARDED).parses is True

    def test_a_pipeline_parses(self) -> None:
        assert parse_body(PIPED).parses is True

    def test_nested_command_substitution_does_not_parse(self) -> None:
        """MEASURED, NOT ASSUMED. bashlex raises ParsingError on this exact line
        from worktree:add, and the module reports that as a fact rather than
        letting the exception escape.
        """
        assert parse_body(NESTED).parses is False

    def test_a_case_statement_does_not_parse(self) -> None:
        """bashlex RAISES NotImplementedError on `case` patterns. Both failure
        modes must be caught, or one of them takes the gate down."""
        assert parse_body(CASE).parses is False

    def test_an_unparseable_body_reports_why(self) -> None:
        """A REFUSAL THAT DOES NOT SAY WHAT IT REFUSED costs a reader the whole
        investigation."""
        body = parse_body(NESTED)

        assert body.parse_error is not None
        assert body.parse_error != ""

    def test_a_parseable_body_has_no_error(self) -> None:
        assert parse_body(SINGLE).parse_error is None

    def test_an_empty_body_parses_and_contains_nothing(self) -> None:
        """ABSENCE IS NOT A FAILURE. A task may legitimately be a comment."""
        body = parse_body("")

        assert body.parses is True
        assert body.commands == []

    def test_a_comment_only_body_parses_and_contains_nothing(self) -> None:
        body = parse_body("# just a note")

        assert body.parses is True
        assert body.commands == []

    def test_parsing_never_raises(self) -> None:
        """THE CONTRACT THAT KEEPS A GATE HONEST. A body is input; a gatherer
        that raises turns "this task is odd" into "the tooling is broken", and
        those have different remedies.
        """
        for hostile in ("(", "'", '"', "if", "${", "$(", "case", "|||"):
            assert parse_body(hostile).parses in (True, False)


class TestCommands:
    def test_the_leading_command_is_reported(self) -> None:
        assert commands_in(SINGLE) == [["uv", "run", "ruff", "check", "."]]

    def test_every_command_in_a_body_is_reported(self) -> None:
        commands = commands_in(GUARDED)

        assert [argv[0] for argv in commands] == ["set", "uv", "uv"]

    def test_each_stage_of_a_pipeline_is_a_command(self) -> None:
        """A PIPELINE IS SEVERAL COMMANDS, and a rule about what git was called
        with must see git's own arguments rather than the whole line."""
        commands = commands_in(PIPED)

        assert [argv[0] for argv in commands] == ["uv", "grep", "awk"]

    def test_an_unparseable_body_reports_no_commands(self) -> None:
        """NOT A GUESS. Half-parsed structure is worse than none: a rule reading
        it would decide on a fragment of the truth.
        """
        assert commands_in(NESTED) == []

    def test_quoting_does_not_affect_the_argument_vector(self) -> None:
        """THE DISTINCTION shlex COULD NOT MAKE, now free: a quoted pipe is an
        argument, not a pipeline separator.
        """
        commands = commands_in('echo "a | b"')

        assert len(commands) == 1
        assert commands[0][0] == "echo"


class TestPipelines:
    def test_a_simple_command_is_not_a_pipeline(self) -> None:
        assert pipelines_in(SINGLE) == []

    def test_a_pipeline_reports_its_stages_in_order(self) -> None:
        """ORDER IS THE FACT. "git piped into grep" and "grep piped into git"
        are different programs, and a set would lose the distinction."""
        assert pipelines_in(PIPED) == [["uv", "grep", "awk"]]

    def test_a_quoted_pipe_is_not_a_pipeline(self) -> None:
        assert pipelines_in('echo "a | b"') == []

    def test_an_unparseable_body_reports_no_pipelines(self) -> None:
        assert pipelines_in(NESTED) == []

    def test_two_pipelines_are_reported_separately(self) -> None:
        body = "ls | grep a\ncat x | wc -l"

        assert pipelines_in(body) == [["ls", "grep"], ["cat", "wc"]]


class TestTaskBodyContract:
    def test_the_body_is_frozen(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            parse_body(SINGLE).parses = False  # type: ignore[misc]

    def test_the_body_serialises_for_opa(self) -> None:
        """THE POLICY RECEIVES STRUCTURE, which is the whole reason parsing
        moved out of Rego."""
        import json

        restored = json.loads(parse_body(PIPED).model_dump_json())

        assert restored["parses"] is True
        assert restored["pipelines"] == [["uv", "grep", "awk"]]

    def test_the_source_is_carried_alongside_the_structure(self) -> None:
        """A DENIAL NAMES WHAT IT READ. Without the source, a reader must go
        find the task to understand the message."""
        assert parse_body(SINGLE).run == SINGLE

    def test_a_body_is_constructible_from_nothing(self) -> None:
        assert TaskBody().parses is True


class TestRedirections:
    """Why walk() follows `parts` and nothing else.

    A REDIRECT TARGET IS NOT A COMMAND AND NOT AN ARGUMENT. bashlex hangs it off
    a redirect node's `output` field, and an earlier version of walk() followed
    that field -- eleven mutants survived there, and measurement showed it was
    the only named attribute ever populated. Following it would have reported
    `out.txt` as a program this task runs.
    """

    def test_a_redirect_target_is_not_an_argument(self) -> None:
        commands = commands_in("ls > out.txt")

        assert commands == [["ls"]]

    def test_an_append_target_is_not_an_argument(self) -> None:
        assert commands_in("echo hello >> log.txt") == [["echo", "hello"]]

    def test_a_redirect_target_is_not_reported_as_a_command(self) -> None:
        """THE DEFECT THE DELETED LOOP WOULD HAVE CAUSED, stated directly."""
        leading = [argv[0] for argv in commands_in("ls > out.txt")]

        assert "out.txt" not in leading

    def test_a_redirected_pipeline_still_reports_its_stages(self) -> None:
        """REDIRECTION AND PIPING COMPOSE, and the pipeline must survive the
        presence of a redirect on its last stage."""
        assert pipelines_in("ls | grep a > found.txt") == [["ls", "grep"]]

    def test_stderr_duplication_is_not_an_argument(self) -> None:
        assert commands_in("cmd 2>&1") == [["cmd"]]
