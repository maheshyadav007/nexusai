"""Swaps sensitive values for tokens before text reaches a model, and back in whatever returns.

Local data keeps its real values. Masking happens only at the model gateway.
"""

import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from nexusai.contracts.agent import GuardFinding, GuardRule, GuardRules, GuardTestResult
from nexusai.kernel.database import Database, Migration

MIGRATION = Migration(
    "agent_guard_001",
    """
CREATE TABLE guard_tokens (value TEXT PRIMARY KEY, token TEXT NOT NULL UNIQUE, kind TEXT NOT NULL);
""",
)
TOKEN = re.compile(r"<([A-Z][A-Z_]*)_(\d+)>")
# A token cut off at the end of a stream chunk: the next chunk may finish it.
PARTIAL_TOKEN = re.compile(r"<[A-Z_0-9]*$")
MAX_TOKEN_LENGTH = 48
FILE_NAME = "guard-rules.json"


class GuardBlocked(Exception):
    """Text matched a rule set to Block, so it can't be sent. The message names the rule."""


class DamagedToken(Exception):
    """A model returned a token we don't recognize. It's never guessed."""


def default_rules() -> GuardRules:
    text = resources.files(__package__).joinpath("default-guard-rules.json").read_text("utf-8")
    return GuardRules.model_validate(json.loads(text))


def load_rules(home: Path) -> GuardRules:
    path = home / "system" / FILE_NAME
    if not path.exists():
        rules = default_rules()
        save_rules(home, rules)
        return rules
    return GuardRules.model_validate(json.loads(path.read_text()))


def save_rules(home: Path, rules: GuardRules) -> None:
    path = home / "system" / FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(rules.model_dump_json(indent=2))
    temporary.replace(path)


def rule_errors(rules: GuardRules) -> list[str]:
    errors = []
    for rule in rules.rules:
        try:
            re.compile(rule.pattern)
        except re.error as error:
            errors.append(f"{rule.name}: {error}")
    return errors


@dataclass(frozen=True)
class _Compiled:
    rule: GuardRule
    pattern: re.Pattern[str]


class DataGuard:
    def __init__(self, db: Database, rules: GuardRules) -> None:
        self.db = db
        self.rules = [
            _Compiled(rule, re.compile(rule.pattern)) for rule in rules.rules if rule.enabled
        ]

    def _token_for(self, value: str, kind: str, tx: sqlite3.Connection) -> str:
        row = tx.execute("SELECT token FROM guard_tokens WHERE value = ?", (value,)).fetchone()
        if row:
            return str(row[0])
        number = tx.execute("SELECT COUNT(*) FROM guard_tokens").fetchone()[0] + 1
        token = f"<{kind}_{number}>"
        tx.execute(
            "INSERT INTO guard_tokens (value, token, kind) VALUES (?, ?, ?)", (value, token, kind)
        )
        return token

    def mask(self, text: str) -> str:
        """The same value always gets the same token, across runs."""
        if not text:
            return text
        for compiled in self.rules:
            if compiled.rule.action == "block" and compiled.pattern.search(text):
                raise GuardBlocked(
                    f"This matches your “{compiled.rule.name}” rule, so it wasn't sent."
                )
        with self.db.transaction() as tx:

            def apply(compiled: _Compiled) -> Callable[[re.Match[str]], str]:
                def replace(match: re.Match[str]) -> str:
                    return self._token_for(match.group(0), compiled.rule.kind, tx)

                return replace

            for compiled in self.rules:
                if compiled.rule.action == "mask":
                    text = compiled.pattern.sub(apply(compiled), text)
        return text

    def mask_value(self, value: Any) -> Any:
        """Masks every string inside structured data, keys included."""
        if isinstance(value, str):
            return self.mask(value)
        if isinstance(value, list):
            return [self.mask_value(item) for item in value]
        if isinstance(value, dict):
            return {self.mask(str(k)): self.mask_value(v) for k, v in value.items()}
        return value

    def _lookup(self, tokens: set[str]) -> dict[str, str]:
        if not tokens:
            return {}
        marks = ",".join("?" * len(tokens))
        rows = self.db.fetch_all(
            f"SELECT token, value FROM guard_tokens WHERE token IN ({marks})",  # noqa: S608
            tuple(tokens),
        )
        return {row["token"]: row["value"] for row in rows}

    def restore(self, text: str) -> str:
        """For text shown to people: an unknown token stays visible rather than being guessed."""
        found = {match.group(0) for match in TOKEN.finditer(text)}
        known = self._lookup(found)
        return TOKEN.sub(lambda match: known.get(match.group(0), match.group(0)), text)

    def damaged_tokens(self, text: str) -> list[str]:
        """Things shaped like one of our tokens that we never issued."""
        found = {match.group(0) for match in TOKEN.finditer(text)}
        if not found:
            return []
        kinds = {compiled.rule.kind for compiled in self.rules}
        known = self._lookup(found)
        return sorted(
            token for token in found if token not in known and token[1:].rpartition("_")[0] in kinds
        )

    def restore_strict(self, text: str) -> str:
        """For sends and tool arguments: a damaged token stops the action."""
        damaged = self.damaged_tokens(text)
        if damaged:
            raise DamagedToken(f"The model returned a value it wasn't given: {', '.join(damaged)}.")
        return self.restore(text)

    def restore_arguments(self, value: Any) -> Any:
        """Real values, before a tool runs. A tool never sees a token."""
        if isinstance(value, str):
            return self.restore_strict(value)
        if isinstance(value, list):
            return [self.restore_arguments(item) for item in value]
        if isinstance(value, dict):
            return {
                self.restore_strict(str(k)): self.restore_arguments(v) for k, v in value.items()
            }
        return value

    def stream_restorer(self) -> "StreamRestorer":
        return StreamRestorer(self)


class StreamRestorer:
    """Restores tokens in streamed text, even when a token is split across chunks."""

    def __init__(self, guard: DataGuard) -> None:
        self.guard = guard
        self.pending = ""

    def feed(self, chunk: str) -> str:
        text = self.pending + chunk
        self.pending = ""
        partial = PARTIAL_TOKEN.search(text)
        if partial and len(text) - partial.start() <= MAX_TOKEN_LENGTH:
            self.pending = text[partial.start() :]
            text = text[: partial.start()]
        return self.guard.restore(text)

    def finish(self) -> str:
        text, self.pending = self.pending, ""
        return self.guard.restore(text)


def test_rules(rules: GuardRules, sample: str) -> GuardTestResult:
    """Tries rules on sample text without saving anything or issuing real tokens."""
    errors = rule_errors(rules)
    if errors:
        return GuardTestResult(masked=sample, findings=[], errors=errors)
    findings: list[GuardFinding] = []
    masked = sample
    numbers: dict[str, str] = {}
    for rule in rules.rules:
        if not rule.enabled:
            continue
        pattern = re.compile(rule.pattern)
        for match in pattern.finditer(masked):
            if not TOKEN.fullmatch(match.group(0)):
                findings.append(
                    GuardFinding(rule=rule.name, value=match.group(0), action=rule.action)
                )

        def replace(match: re.Match[str], kind: str = rule.kind) -> str:
            value = match.group(0)
            return numbers.setdefault(value, f"<{kind}_{len(numbers) + 1}>")

        masked = pattern.sub(replace, masked)
    return GuardTestResult(masked=masked, findings=findings, errors=[])
