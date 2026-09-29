"""The same brain, asked through a Claude subscription instead of an API key.

The decision layer does not care how the question reaches a model. What changes
between this module and `client.py` is only the transport -- so everything that
makes an answer trustworthy is inherited rather than rewritten: the same prompt,
the same schema, the same guard, the same scoring, the same content-addressed
cache. A bug fixed in one path is fixed in both, which is the entire reason this
is a subclass and not a second implementation.

Three things the API gives us are not available here, and pretending otherwise
would be the dangerous kind of convenience:

**No structured outputs.** `messages.parse` enforces the schema server-side. Here
the schema is text in the prompt and the answer is parsed locally, so a malformed
reply is a real and recurring event rather than an impossibility. It is handled as
one: parse, and on failure ask once more with the validation error quoted back.

**No batch API.** Every call is a synchronous subprocess, a second or two of
latency each. A few dozen calls is nothing; twenty thousand is days. That is the
line between what belongs here and what belongs on the API.

**No prompt cache control.** The system prompt is sent from a file each time and
the CLI caches what it caches. Nothing breaks -- but the cache-hit figure that
`client.py` watches so carefully is no longer ours to measure.

What is gained is worth the trade for live use: no API key, no per-call bill, and
the account already exists.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from traidingbrain.brain import prompt as prompts
from traidingbrain.brain.client import AnthropicBrain, CacheLike, _Refusal
from traidingbrain.config.settings import AppConfig
from traidingbrain.domain.snapshot import BrainInput
from traidingbrain.domain.verdict import BrainVerdict

#: How long one call may take before it is treated as a failure. The CLI starts a
#: Node process, authenticates and streams a reply; a few seconds is normal, and a
#: minute means something is wrong rather than that patience would help.
CALL_TIMEOUT_S = 180

#: One retry, with the validation error quoted back. A second failure is answered
#: with NO TRADE rather than a third attempt: without server-side schema
#: enforcement, a model that has produced malformed output twice is not one more
#: retry away from correctness, and a backtest must not stall on a single bar.
MAX_ATTEMPTS = 2


class SubscriptionUnavailableError(RuntimeError):
    """The CLI is missing, or the account is not signed in.

    Raised rather than degraded to NO TRADE, because a whole run of NO TRADE
    decisions caused by a login problem looks exactly like a whole run of
    legitimately cautious ones.
    """


@dataclass
class _CliUsage:
    """Token counts from the CLI envelope, shaped like the SDK's usage object."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


class SubscriptionBrain(AnthropicBrain):
    """Asks Claude through the signed-in CLI. No API key, no per-call bill."""

    def __init__(
        self,
        config: AppConfig,
        cache: CacheLike | None = None,
        *,
        model: str | None = None,
        cli: str = "claude",
    ) -> None:
        # budget_usd=0 disables the budget stop: a subscription has no per-call
        # bill to stop against. The dollar figure this still reports is what the
        # same run *would* have cost on the API -- worth knowing, and not a charge.
        super().__init__(config, cache, client=_NoApiClient(), model=model, budget_usd=0.0)
        self.cli = cli
        self._resolved: str | None = None
        self._workspace = tempfile.mkdtemp(prefix="traidingbrain-brain-")
        self._system_file = Path(self._workspace) / "system.md"
        self._system_file.write_text(
            "".join(str(block["text"]) for block in prompts.system_blocks()),
            encoding="utf-8",
        )
        self._schema_text = json.dumps(BrainVerdict.model_json_schema(), indent=2)

    # -- transport ---------------------------------------------------------- #

    def _ask(self, payload: BrainInput) -> tuple[BrainVerdict | _Refusal, str | None, str]:
        """One CLI round trip, parsed and validated locally."""
        content = self._request_text(payload)
        last_error = ""

        for attempt in range(MAX_ATTEMPTS):
            raw, session_id = self._run(content)
            if raw is None:
                self.usage.errors += 1
                return (
                    _Refusal(category="no_output", explanation="the CLI returned nothing"),
                    session_id,
                    "",
                )
            try:
                verdict = BrainVerdict.model_validate_json(_extract_json(raw))
            except (ValidationError, ValueError) as error:
                last_error = str(error)
                if attempt + 1 < MAX_ATTEMPTS:
                    content = self._correction_text(payload, raw, last_error)
                continue
            return verdict, session_id, raw

        self.usage.errors += 1
        return (
            _Refusal(category="unparsed", explanation=f"malformed after {MAX_ATTEMPTS} attempts"),
            None,
            last_error,
        )

    def _executable(self) -> str:
        """The CLI's full path, resolved once.

        On Windows the CLI is `claude.CMD`, and `subprocess` does not consult
        PATHEXT the way a shell does -- so passing the bare name fails with a
        missing-file error on the one platform this runs on. `shutil.which` does
        consult it, which turns a confusing failure into a resolved path.
        """
        if self._resolved is None:
            found = shutil.which(self.cli)
            if found is None:
                raise SubscriptionUnavailableError(
                    f"{self.cli!r} is not on PATH. Install Claude Code "
                    "(npm install -g @anthropic-ai/claude-code), or pass cli=<full path>."
                )
            self._resolved = found
        return self._resolved

    def _run(self, content: str) -> tuple[str | None, str | None]:
        """Invoke the CLI once, in an empty directory with no tools.

        Each flag removes a way for the answer to stop being a function of the
        snapshot alone: an empty working directory so no CLAUDE.md or project
        settings are read, no tools so nothing can be looked up, no MCP servers,
        and no session on disk -- a long backtest would otherwise leave a
        transcript behind for every bar.
        """
        command = [
            self._executable(),
            "--print",
            "--output-format",
            "json",
            "--model",
            self.model,
            "--system-prompt-file",
            str(self._system_file),
            "--tools",
            "",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--settings",
            "{}",
            "--max-turns",
            "1",
            "--no-session-persistence",
        ]
        try:
            completed = subprocess.run(
                command,
                input=content,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=CALL_TIMEOUT_S,
                cwd=self._workspace,
                check=False,
            )
        except FileNotFoundError as error:
            raise SubscriptionUnavailableError(
                f"{self.cli!r} is not on PATH. Install Claude Code, or pass cli=<full path>."
            ) from error
        except subprocess.TimeoutExpired:
            self.usage.errors += 1
            return None, None

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            if _is_auth_failure(detail):
                raise SubscriptionUnavailableError(
                    "the CLI is not signed in to a Claude subscription. Run "
                    "`claude setup-token`, or `claude` and sign in, then retry.\n"
                    f"{detail[:400]}"
                )
            self.usage.errors += 1
            return None, None

        return self._unwrap(completed.stdout)

    def _unwrap(self, stdout: str) -> tuple[str | None, str | None]:
        """Pull the answer and the token counts out of the CLI envelope."""
        try:
            envelope = json.loads(stdout)
        except json.JSONDecodeError:
            # Not the documented shape; the text may still be usable.
            return (stdout or None), None
        if not isinstance(envelope, dict):
            return (stdout or None), None

        usage = envelope.get("usage") or {}
        self.usage.add(
            _CliUsage(
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                cache_read_input_tokens=int(usage.get("cache_read_input_tokens") or 0),
                cache_creation_input_tokens=int(usage.get("cache_creation_input_tokens") or 0),
            )
        )
        session_id = envelope.get("session_id")
        result = envelope.get("result")
        if envelope.get("is_error"):
            # An expired login arrives here, not on a non-zero exit code: the CLI
            # ran fine and reports the failure inside the envelope. Without this
            # check a lapsed subscription would turn a whole run into NO TRADE
            # decisions that look exactly like caution.
            detail = str(result or "")
            if _is_auth_failure(detail):
                raise SubscriptionUnavailableError(
                    "the CLI is not signed in to a Claude subscription. Run "
                    "`claude setup-token`, or `claude` and sign in, then retry.\n"
                    f"{detail[:400]}"
                )
            return None, session_id
        return (str(result) if result is not None else None), session_id

    # -- prompt assembly ---------------------------------------------------- #

    def _request_text(self, payload: BrainInput) -> str:
        """The user turn, plus the schema the API would otherwise enforce."""
        return (
            f"{prompts.user_content(payload)}\n\n"
            "Reply with a single JSON object and nothing else -- no prose before or "
            "after it, no markdown fence. It must validate against this schema:\n\n"
            f"{self._schema_text}"
        )

    def _correction_text(self, payload: BrainInput, raw: str, error: str) -> str:
        """The retry, with the actual failure quoted rather than described.

        A generic "that was invalid, try again" throws away the one piece of
        information that would make the second attempt better than the first.
        """
        return (
            f"{self._request_text(payload)}\n\n"
            "A previous answer to this exact request failed validation. Here it is, "
            "followed by the error:\n\n"
            f"{raw[:2000]}\n\n{error[:1000]}\n\n"
            "Return only the corrected JSON object."
        )


class _NoApiClient:
    """Stands where the Anthropic client would, and refuses.

    `AnthropicBrain.estimate` counts tokens through the API. On this path there is
    no API and no bill to estimate, so the honest response is to say so rather than
    to return a plausible zero.
    """

    def __getattr__(self, name: str) -> Any:
        raise SubscriptionUnavailableError(
            f"{name!r} needs the Anthropic API. This brain runs through the CLI "
            "subscription, which has no token-counting or batch endpoint."
        )


def _extract_json(text: str) -> str:
    """The JSON object in a reply that may also contain prose or a fence.

    The schema instruction asks for bare JSON and usually gets it. This exists for
    the times it does not, which without server-side enforcement is a normal
    outcome rather than an anomaly.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        body = stripped[3:]
        stripped = body.split("```")[0] if "```" in body else body
        if stripped.startswith("json"):
            stripped = stripped[4:]
        stripped = stripped.strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"no JSON object in the reply: {text[:200]!r}")
    return stripped[start : end + 1]


def _is_auth_failure(detail: str) -> bool:
    lowered = detail.lower()
    return any(
        marker in lowered
        for marker in ("login", "log in", "sign in", "authenticat", "unauthor", "oauth", "api key")
    )
