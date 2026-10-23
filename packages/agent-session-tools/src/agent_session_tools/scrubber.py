"""Secrets detection and format-preserving redaction for session data.

Uses gitleaks-derived regex patterns for known secret formats.

Architecture: scrub on data egress (sync, LAN serve, exported context).
Local DB stays unscrubbed for full-fidelity local queries.
"""

from __future__ import annotations

import logging
import re
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Gitleaks-derived patterns — no external dependency needed.
# Each pattern targets a specific, well-known secret format.
SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "aws_access_key": re.compile(
        r"\b((?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16})\b"
    ),
    "aws_secret_key": re.compile(
        # Quotes optional: the common .env/CLI shape is unquoted
        # (aws_secret_access_key = wJalr…). The 40-char base64 run and a
        # word boundary keep it specific enough to avoid false positives.
        r"(?i)aws.{0,20}(?:secret|key).{0,20}['\"]?[0-9a-zA-Z/+]{40}['\"]?\b"
    ),
    # Classic PATs (ghp_) and OAuth access tokens (gho_): 36 alphanumerics
    # after the prefix today, but GitHub's token-format changelog (2021-03)
    # tells integrators to support tokens up to 255 characters, so an exact
    # {36} gave zero findings on a longer one (the F-AST-07 shape).
    "github_pat": re.compile(r"\bghp_[0-9a-zA-Z]{36,255}\b"),
    "github_fine_grained": re.compile(r"\bgithub_pat_\w{82}\b"),
    "github_oauth": re.compile(r"\bgho_[0-9a-zA-Z]{36,255}\b"),
    # GitHub App tokens: ghu_ (user-to-server) and ghs_ (installation, which
    # includes Actions' GITHUB_TOKEN). A classic one is 36 alphanumerics after
    # the prefix. Installation tokens are now stateless, ghs_<app id>_<JWT>:
    # about 520 characters with two dots and "-"/"_" inside, and GitHub says
    # the length varies. The match runs over the whole token (alphanumerics,
    # "-", "_" and dot-joined segments) with no upper bound, so no tail is left
    # behind (the F-AST-07 failure mode), and once it starts it never fails,
    # so a long crafted run costs one pass. The lookahead keeps a short
    # "ghs_..." word in prose out; a full stop after a token is not a segment.
    # This entry sits before "jwt" so the JWT inside a stateless token is
    # never matched on its own.
    "github_app_token": re.compile(
        r"\bgh[su]_(?=[A-Za-z0-9_.-]{36})[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*"
    ),
    # GitHub refresh tokens: 36 or more alphanumerics; GitHub documents no
    # fixed length, so the body runs to the end of the token.
    "github_refresh_token": re.compile(r"\bghr_[A-Za-z0-9]{36,}"),
    # OpenAI: sk-proj-/sk-svcacct-/sk-admin- plus 120-160 characters that can
    # include "-" and "_", or legacy sk- plus 48 alphanumerics with
    # "T3BlbkFJ" (base64 "OpenAI") at offset 20. Anthropic: sk-ant-api03- or
    # sk-ant-admin01- plus 95 characters. A modern key's body runs to the end
    # of the key-character run, with no upper bound and no trailing \b: the
    # old {20,80} / {80,100} bounds were shorter than real keys, and a \b
    # that can only fall beside an inner "-" redacted a prefix and left the
    # tail in the text (F-AST-07).
    "openai_key": re.compile(
        r"\bsk-(?:proj|svcacct|admin)-[A-Za-z0-9_-]{20,}"
        r"|\bsk-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20}\b"
    ),
    "anthropic_key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{80,}"),
    "jwt": re.compile(
        r"\bey[a-zA-Z0-9]{17,}\.ey[a-zA-Z0-9/\\_-]{17,}\.[a-zA-Z0-9/\\_-]{10,}\b"
    ),
    "connection_string": re.compile(
        r"(?i)(?:postgres|mysql|mongodb|redis)://[^:\s]+:[^@\s]+@[^\s\"']+",
    ),
    "gcp_api_key": re.compile(r"\bAIza[\w-]{35}\b"),
    "stripe_key": re.compile(r"\b(?:sk|rk)_(?:test|live|prod)_[a-zA-Z0-9]{10,99}\b"),
    "slack_bot_token": re.compile(r"\bxoxb-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9-]*\b"),
    # Slack user (xoxp-) and legacy workspace-app (xoxa-) OAuth tokens: a
    # dash-separated run that starts with a digit (xoxp-<team>-<user>-<id>-
    # <hex>, xoxa-2-...). The match takes the whole run, ending on its last
    # alphanumeric; ten or more characters keep "xoxp-1234" in prose out.
    "slack_user_token": re.compile(
        r"\bxoxp-(?=\d[0-9A-Za-z-]{9})[0-9A-Za-z-]*[0-9A-Za-z]"
    ),
    "slack_workspace_token": re.compile(
        r"\bxoxa-(?=\d[0-9A-Za-z-]{9})[0-9A-Za-z-]*[0-9A-Za-z]"
    ),
    "generic_secret": re.compile(
        r"(?i)(?:password|secret|token|api_key|apikey|api-key)"
        r"\s*[=:]\s*['\"][^\s'\"]{8,}['\"]"
    ),
}

# PEM-armoured private keys. The secret is the base64 BODY, so a match is
# the whole block, never just its BEGIN line (F-AST-01). The body class is
# what a PEM body can hold: base64, whitespace, a line break written out as
# "\n" (JSON, a SQL dump) and the "Proc-Type: 4,ENCRYPTED" / "DEK-Info:
# AES-128-CBC,<iv>" lines of a legacy encrypted key. It holds no quote
# character, so a span never crosses the end of the SQL or JSON string that
# contains it, and it stops at "-----", so it never runs through the next
# armour line.
_PEM_LABEL = r"[ A-Z0-9_-]{0,100}PRIVATE KEY(?: BLOCK)?"
_PEM_BODY_CHAR = re.compile(r"[A-Za-z0-9+/=,:\\ \t\r\n\f\v-]")
_PEM_BODY = rf"(?:(?!-----){_PEM_BODY_CHAR.pattern})*+"
# Armour headers: "Name: value" lines straight after the BEGIN line. An
# armoured PGP private key ("... PGP PRIVATE KEY BLOCK" armour, RFC 4880 §6.2)
# may carry Version:/Comment: headers whose values hold ".", "(", "@" and the
# like, which are not body characters, so without this the whole-block match
# failed on them and a block cut off before its END kept its body. A value
# stops at a line break (real or written "\n"), a backslash, a quote or an
# armour run of five dashes, so it never leaves its line or the SQL/JSON
# string around it and never swallows an END line. PEM's own
# Proc-Type:/DEK-Info: lines have the same shape.
_ARMOUR_HEADERS = (
    r"(?:(?:\r?\n|(?:\\r)?\\n)[A-Za-z][A-Za-z0-9-]*: (?:(?!-----)[^\r\n\\'\"])*+)*+"
)
# A base64 run of body length after whitespace. No word of prose is 20
# base64 characters, so "----- and nothing follows" stays prose while a
# flattened body line (64 characters) does not.
_INLINE_BODY_RUN = r"[ \t]++(?=[A-Za-z0-9+/=]{20})[A-Za-z0-9+/=]*+"
# The same armour headers when the block was flattened onto ONE line, so
# "Version: GnuPG v2.0.22 (GNU/Linux)" or "Version: X.Y [comment]" sits
# between the BEGIN armour and the body with spaces for line breaks (D#5).
# Its "(", ")", "[", "]" and "." are not body characters, so without this
# the whole-block match stopped on them and the inline rule, which wants
# base64 straight after the armour, left the body in the text. The run is
# admitted only when a body run follows it: a header followed by words is
# prose. The value takes the longest stretch (at most 200 characters, never
# a line break, backslash, quote or armour) that a body run still follows,
# so a header holding a long word is not mistaken for the end of the
# headers; a body run swallowed into the value is still inside the span.
# The value ends on a non-blank character, so while the engine tries
# shorter values the body-run lookahead walks a whitespace run once rather
# than once per candidate (a megabyte of spaces after a header cost 0.5 s
# without this).
_INLINE_ARMOUR_HEADERS = (
    r"(?:[ \t]++[A-Za-z][A-Za-z0-9-]*+: "
    r"(?:(?:(?!-----)[^\r\n\\'\"]){0,199}(?!-----)[^\r\n\\'\" \t])?"
    rf"(?={_INLINE_BODY_RUN}))?"
)
_PEM_BLOCK = re.compile(
    rf"-----BEGIN{_PEM_LABEL}-----{_ARMOUR_HEADERS}{_INLINE_ARMOUR_HEADERS}"
    rf"{_PEM_BODY}-----END{_PEM_LABEL}-----"
)
# A BEGIN line whose END line never arrived (output cut off mid-key): the
# header plus the body that followed it on the next line -- or, for a key
# pasted flat on one line, the base64 run glued straight onto the armour
# (council pass 2: that run used to survive with only its header redacted).
# The inline form stops at whitespace, so prose after a bare armour line
# ("...PRIVATE KEY----- and nothing follows") is never treated as a body.
# A flattened paste may also carry the collapsed newline as a space or tab
# (the BEGIN armour, one space, then "MIIE..."), and its later line breaks
# too, so the body is every whitespace-separated run of body length that
# follows (D#5: the rule used to take only the first run), after any
# armour headers flattened onto the same line.
_PEM_INLINE_BODY = (
    rf"(?:(?=[A-Za-z0-9+/])[A-Za-z0-9+/=]*+(?:{_INLINE_BODY_RUN})*+"
    rf"|{_INLINE_ARMOUR_HEADERS}(?:{_INLINE_BODY_RUN})++)"
)
_PEM_HEAD = re.compile(
    rf"-----BEGIN{_PEM_LABEL}-----{_ARMOUR_HEADERS}"
    rf"(?:(?=\r?\n|\\[rn]){_PEM_BODY}|{_PEM_INLINE_BODY})?"
)
_PEM_FOOT = re.compile(rf"-----END{_PEM_LABEL}-----")
# One run of a flattened body: the characters _INLINE_BODY_RUN admits, as a
# set, for the backwards walk from an END armour (no "-", so the walk stops
# at the previous armour; no NUL, so it stops at an earlier pass's mask).
# Built from the stdlib constants: the alphabet written out is 65 base64
# characters, which the commit-time entropy scanner reads as a secret.
_INLINE_RUN_CHARS = frozenset(string.ascii_letters + string.digits + "+/=")
_INLINE_RUN_LENGTH = 20  # the body-length lookahead in _INLINE_BODY_RUN


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    """Overwrite each span with NULs of the same length, in one pass.

    ``spans`` are one ``finditer`` pass's matches: sorted and disjoint. The
    length is unchanged, so every offset found so far still holds.
    """
    pieces: list[str] = []
    cursor = 0
    for start, end in spans:
        pieces += [text[cursor:start], "\0" * (end - start)]
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def _flattened_tail_start(text: str, armour: int) -> int:
    """Start of the flattened body before the END armour at ``armour``.

    Mirror of the flattened BEGIN rule, walked backwards: from the armour,
    take whitespace-separated runs of body length (``_INLINE_BODY_RUN``'s
    20-character floor, so ``see page 12 of the notes`` before an END armour
    stays prose) until a shorter word, a line break, another armour or an
    earlier pass's mask. Two shapes a key's last line takes are admitted as
    the run nearest the armour only: a run glued straight onto it (a paste
    that dropped its newlines; prose never glues onto an armour, the same
    reading the BEGIN rule makes), and a PGP CRC line ``=XXXX``. Each step
    moves strictly left, so a line of many END armours costs one walk per
    armour over its own runs, never a rescan.
    """
    start = armour
    nearest = True
    while True:
        gap = start
        while gap > 0 and text[gap - 1] in " \t":
            gap -= 1
        run = gap
        while run > 0 and text[run - 1] in _INLINE_RUN_CHARS:
            run -= 1
        length = gap - run
        if length == 0:
            return start
        if length < _INLINE_RUN_LENGTH and not (
            nearest and (gap == armour or (text[run] == "=" and 2 <= length <= 5))
        ):
            return start
        start = run
        nearest = False


def _private_key_spans(text: str) -> list[tuple[int, int]]:
    """Return the sorted, disjoint spans of PEM private-key material in text.

    Whole blocks first. Then, for a block cut off at the end, its BEGIN line
    and the body that followed; for a block cut off at the front, its END
    line and the body before it. Truncated key material is still key
    material, so a cut-off block is redacted as far as it goes.
    """
    if "PRIVATE KEY-----" not in text and "PRIVATE KEY BLOCK-----" not in text:
        return []
    spans: list[tuple[int, int]] = []
    # Each pass runs over the text with every earlier pass's spans overwritten
    # with NULs (same length, so offsets hold); NUL is not a body character,
    # so later passes stop at it. A pass's own matches come from one
    # ``finditer`` over the string as it stood before the pass, so they are
    # masked together afterwards, once: masking inside the loop would rebuild
    # the whole string per span and cost quadratic time in the number of
    # armour lines (D#1) without changing a single match.
    masked = text
    for pattern in (_PEM_BLOCK, _PEM_HEAD):
        found = [match.span() for match in pattern.finditer(masked)]
        if found:
            spans += found
            masked = _mask(masked, found)
    for match in _PEM_FOOT.finditer(masked):
        start = match.start()
        if masked.endswith(("\n", "\\n"), 0, start):
            while (
                start > 0
                and _PEM_BODY_CHAR.fullmatch(masked[start - 1])
                and not masked.endswith("-----", 0, start)
            ):
                start -= 1
        else:
            # Cut off at the front AND flattened onto one line: the body runs
            # sit before END with spaces for line breaks (plan 5, F).
            start = _flattened_tail_start(masked, start)
        spans.append((start, match.end()))
    return sorted(spans)


@dataclass
class ScrubResult:
    """Result of a scrub operation."""

    text: str
    findings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def scrubbed(self) -> bool:
        return len(self.findings) > 0


@dataclass
class ScrubReport:
    """Aggregate report for a batch scrub operation."""

    messages_scanned: int = 0
    messages_with_secrets: int = 0
    total_findings: int = 0
    findings_by_type: dict[str, int] = field(default_factory=dict)

    def add(self, result: ScrubResult) -> None:
        self.messages_scanned += 1
        if result.scrubbed:
            self.messages_with_secrets += 1
            self.total_findings += len(result.findings)
            for finding in result.findings:
                entity_type = finding["type"]
                self.findings_by_type[entity_type] = (
                    self.findings_by_type.get(entity_type, 0) + 1
                )


class Scrubber:
    """Secrets detection and format-preserving redaction.

    Same secret within a Scrubber instance always maps to the same placeholder,
    preserving referential integrity across messages in a session.

    Usage:
        scrubber = Scrubber()
        result = scrubber.scrub(text)
        # result.text has secrets replaced with [TYPE-NNN] placeholders
        # result.findings lists what was found (type + placeholder, never the original)
    """

    def __init__(
        self,
        allowlist_patterns: list[str] | None = None,
        allowlist_values: list[str] | None = None,
    ):
        self._mapping: dict[str, str] = {}
        self._counters: dict[str, int] = {}
        self._allowlist_patterns = [re.compile(p) for p in (allowlist_patterns or [])]
        self._allowlist_values = set(allowlist_values or [])

    def _placeholder(self, entity_type: str, value: str) -> str:
        """Generate a deterministic, format-hinting placeholder."""
        if value in self._mapping:
            return self._mapping[value]

        count = self._counters.get(entity_type, 0) + 1
        self._counters[entity_type] = count

        placeholder = f"[{entity_type.upper()}-{count:03d}]"
        self._mapping[value] = placeholder
        return placeholder

    def _is_allowlisted(self, value: str) -> bool:
        """Check if a value is in the allowlist."""
        if value in self._allowlist_values:
            return True
        return any(pattern.search(value) for pattern in self._allowlist_patterns)

    def _scrub_private_keys(self, text: str, findings: list[dict[str, Any]]) -> str:
        """Replace each PEM private-key span with its placeholder.

        Runs before SECRET_PATTERNS so no other detector can split a block
        first (a base64 body line can look like an AWS key id), which would
        leave the rest of the body unmatched.
        """
        pieces: list[str] = []
        cursor = 0
        for start, end in _private_key_spans(text):
            original = text[start:end]
            if self._is_allowlisted(original):
                continue
            placeholder = self._placeholder("private_key", original)
            findings.append(
                {
                    "type": "private_key",
                    "placeholder": placeholder,
                    "length": len(original),
                }
            )
            pieces += [text[cursor:start], placeholder]
            cursor = end
        pieces.append(text[cursor:])
        return "".join(pieces)

    def scrub(self, text: str) -> ScrubResult:
        """Scrub secrets from text, returning the cleaned text and findings.

        Findings contain type and placeholder only — never the original value.
        """
        if not text:
            return ScrubResult(text=text)

        findings: list[dict[str, Any]] = []
        result = self._scrub_private_keys(text, findings)

        for entity_type, pattern in SECRET_PATTERNS.items():
            for match in pattern.finditer(result):
                original = match.group()
                if self._is_allowlisted(original):
                    continue
                placeholder = self._placeholder(entity_type, original)
                findings.append(
                    {
                        "type": entity_type,
                        "placeholder": placeholder,
                        "length": len(original),
                    }
                )
                result = result.replace(original, placeholder)

        return ScrubResult(text=result, findings=findings)

    def scrub_sql(self, sql: str) -> tuple[str, ScrubReport]:
        """Scrub secrets from a SQL dump string.

        Used for sync egress — secrets in INSERT VALUES clauses are replaced.
        Returns (scrubbed_sql, report).
        """
        report = ScrubReport()
        result = self.scrub(sql)
        report.messages_scanned = 1
        if result.scrubbed:
            report.messages_with_secrets = 1
            report.total_findings = len(result.findings)
            for f in result.findings:
                report.findings_by_type[f["type"]] = (
                    report.findings_by_type.get(f["type"], 0) + 1
                )
        return result.text, report

    @property
    def stats(self) -> dict[str, int]:
        """Return counts of secrets found by type."""
        return dict(self._counters)


def load_scrub_config(config_dir: Path | None = None) -> dict[str, Any]:
    """Load scrub configuration from scrub-config.toml.

    Returns dict with keys: allowlist_patterns, allowlist_values.
    """
    if config_dir is None:
        from agent_session_tools.config_loader import CONFIG_DIR

        config_dir = CONFIG_DIR

    config_path = config_dir / "scrub-config.toml"
    if not config_path.exists():
        return {"allowlist": {"patterns": [], "values": []}}

    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            logger.warning("No TOML parser available — scrub config not loaded")
            return {"allowlist": {"patterns": [], "values": []}}

    with open(config_path, "rb") as f:
        return tomllib.load(f)


def create_scrubber(config_dir: Path | None = None) -> Scrubber:
    """Create a Scrubber instance with config from scrub-config.toml."""
    scrub_config = load_scrub_config(config_dir)
    allowlist = scrub_config.get("allowlist", {})
    return Scrubber(
        allowlist_patterns=allowlist.get("patterns", []),
        allowlist_values=allowlist.get("values", []),
    )
