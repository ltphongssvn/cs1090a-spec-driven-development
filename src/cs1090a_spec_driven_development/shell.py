# src/cs1090a_spec_driven_development/shell.py
# TASK BODIES, PARSED INTO STRUCTURE BEFORE A POLICY EVER SEES THEM.
#
# --- FOUR ATTEMPTS, THREE MEASURED FAILURES -----------------------------------
#
# ONE: Rego asked whether a body contained "git " and "| grep". It denied
# `setup`, wrongly -- that task has `git rev-parse` on one line and
# `ls | grep -v sample` thirty lines away.
#
# TWO: correlate per line. Still substring matching; fixes that example and
# leaves quoted text and `;`-separated commands for next time.
#
# THREE: tokenise with shlex. MEASURED AGAINST THE REAL mise.toml AND REJECTED
# -- 16 lines raised, and nested substitution was destroyed:
#
#   root="$(cd "$(dirname "$common")" && pwd)"
#     -> ['root=$(cd $', '(', 'dirname', '$common', ')', ' && pwd)']
#
# FOUR, AND THE ONE HERE: bashlex, a transliteration of GNU bash's own parser
# producing a real AST. Measured too -- it reads 19 of this repository's 25 task
# bodies and fails on 6.
#
# --- WHY THE SIX FAILURES ARE THE POINT ---------------------------------------
#
# They are repo:configure, setup, start:check, start:here, worktree:add and
# worktree:remove -- every task with real shell logic. The other nineteen parse
# instantly because they are single invocations.
#
# THE ROOT CAUSE IS NOT THE PARSER. It is that logic lives in task bodies at
# all. A more complete parser would only let us keep the thing that needs
# removing. Parseability is therefore itself the rule: a body no parser can read
# is a body nobody can analyse, review with confidence, or test.
#
# --- THE TREE WALK WAS DEAD CODE, AND MUTATION TESTING SAID SO ----------------
#
# A surviving mutant means one of three things: a missing assertion, a missing
# edge case, or CODE THAT IS NOT NECESSARY FOR THE PROGRAM TO BE CORRECT. The
# third is the least expected and the most valuable, because no amount of test
# writing fixes it.
#
# walk() once also followed three named attributes -- `command`, `list` and
# `output` -- on the theory that bashlex hangs some children off fields rather
# than `parts`. ELEVEN MUTANTS SURVIVED IN THAT LOOP: every string could be
# corrupted, the getattr could return None, the condition could invert, and the
# recursion could be handed None, with nothing objecting. Code that cannot be
# broken is code that never runs.
#
# SO IT WAS MEASURED, not argued. Across redirections, appends, stderr
# duplication, conditionals, subshells, groupings, for- and while-loops,
# pipelines and and-lists, ONLY `output` was ever populated -- and only for a
# redirection, where it holds the TARGET FILENAME.
#
# WALKING INTO IT WOULD HAVE BEEN WRONG ANYWAY. `ls > out.txt` puts out.txt in
# `output`, and argv_of deliberately excludes redirect targets: a rule asking
# which commands a task runs must not be told that `out.txt` is one. The loop
# was both unexercised and, had it ever fired, incorrect -- so it is deleted
# rather than tested, and a case now pins the behaviour that made it wrong.
#
# --- COMMENTS ARE STRIPPED BEFORE PARSING -------------------------------------
#
# A comment-only body made bashlex raise AttributeError from inside its own
# visitor. Catching it merely stopped the crash and reported parses=False, which
# is WRONG: a comment is valid shell that does nothing, and denying a task for
# carrying documentation would be worse than the original defect. Comments are
# not commands, so they are removed upstream of the parser -- correct on its own
# terms, and it closes the crash at source.
#
# NOT A REGEX OVER `#`. A hash inside quotes is a character, not a comment --
# `grep '#define'` is a command -- so lines are classified by their first
# non-blank character, which is exactly what a comment line is.
#
# --- THE EXCEPTION HANDLER IS DELIBERATELY BROAD ------------------------------
#
# Three distinct failure types have now been observed from one library on one
# repository's input: ParsingError, NotImplementedError, AttributeError.
# Enumerating them was the bug the third one exposed. A gate that crashes on an
# unusual task reports "the tooling is broken" where it should report "this task
# cannot be analysed", and those have different owners.

from typing import Any

import bashlex
from pydantic import BaseModel, ConfigDict, Field

COMMAND = "command"
PIPELINE = "pipeline"
WORD = "word"
COMMENT = "#"


class TaskBody(BaseModel):
    """One task's shell, as structure a policy can reason over.

    THE SOURCE TRAVELS WITH THE STRUCTURE so a denial can name what it read.
    Without it a reader must go and find the task to understand the message.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run: str = ""
    parses: bool = True
    parse_error: str | None = None
    commands: list[list[str]] = Field(default_factory=list)
    pipelines: list[list[str]] = Field(default_factory=list)


def executable_lines(run: str) -> str:
    """The body with comment lines removed.

    CLASSIFIED BY FIRST NON-BLANK CHARACTER, not by searching for `#`. A hash
    inside quotes is a character in an argument, and treating it as a comment
    would truncate the line.
    """
    kept = [line for line in run.splitlines() if not line.lstrip().startswith(COMMENT)]
    return "\n".join(kept)


def walk(node: Any) -> list[Any]:
    """Every node in a bashlex tree, parents before children.

    `parts` IS THE WHOLE TRAVERSAL. See the module header: following `command`,
    `list` and `output` as well was measured to be dead in every construct this
    repository contains, and reaching `output` would have been wrong anyway --
    it holds a redirection's target filename, which is not a command.

    NODES WITHOUT A `kind` ARE SKIPPED, because bashlex sometimes leaves a bare
    string in a tree and a walker assuming otherwise propagates the failure.
    """
    if not hasattr(node, "kind"):
        return []

    nodes = [node]
    for child in getattr(node, "parts", []):
        nodes.extend(walk(child))
    return nodes


def argv_of(node: Any) -> list[str]:
    """A command node's argument vector.

    ONLY WORD PARTS. A command node also carries assignments and redirections,
    and treating a redirect as an argument would report a filename where a flag
    belongs -- or report `out.txt` as a command the task runs.
    """
    parts = getattr(node, "parts", [])
    return [part.word for part in parts if getattr(part, "kind", None) == WORD]


def read_commands(trees: list[Any]) -> list[list[str]]:
    """Every simple command in the body, in source order."""
    found: list[list[str]] = []
    for tree in trees:
        for node in walk(tree):
            if node.kind == COMMAND:
                argv = argv_of(node)
                if argv:
                    found.append(argv)
    return found


def read_pipelines(trees: list[Any]) -> list[list[str]]:
    """The leading command of each stage, for every pipeline in the body.

    THE LEADING COMMAND IS WHAT A RULE ASKS ABOUT: whether git feeds grep is a
    question about which programs are connected, not about their arguments.
    Order is preserved because `git | grep` and `grep | git` differ.
    """
    found: list[list[str]] = []
    for tree in trees:
        for node in walk(tree):
            if node.kind != PIPELINE:
                continue
            stages = [
                argv_of(part)[0]
                for part in node.parts
                if getattr(part, "kind", None) == COMMAND and argv_of(part)
            ]
            if stages:
                found.append(stages)
    return found


def parse_body(run: str) -> TaskBody:
    """Parse a task body, reporting failure rather than raising it."""
    executable = executable_lines(run)
    if not executable.strip():
        return TaskBody(run=run)

    try:
        trees = bashlex.parse(executable)
        commands = read_commands(trees)
        pipelines = read_pipelines(trees)
    except Exception as error:
        return TaskBody(run=run, parses=False, parse_error=f"{type(error).__name__}: {error}")

    return TaskBody(run=run, parses=True, commands=commands, pipelines=pipelines)


def commands_in(run: str) -> list[list[str]]:
    """Every command, or nothing when the body did not parse.

    NOTHING RATHER THAN A GUESS. Half-parsed structure is worse than none: a
    rule reading it would decide on a fragment of the truth and report the
    verdict with full confidence.
    """
    return parse_body(run).commands


def pipelines_in(run: str) -> list[list[str]]:
    return parse_body(run).pipelines
