"""Writing closed trades into the Obsidian vault.

The vault is where a trade stops being a row and becomes something you can argue
with six months later. So what goes in is not the fill -- the fill is already in
the database and nobody rereads a database -- but the *claim* the system made and
what the market did about it.

Three rules shape this, and the first two are about not corrupting a notebook you
also write in by hand:

**One file per trade, named by what it is.** A note per trade can be linked,
tagged, moved and edited without a sync job disagreeing with you. One rolling
"trades.md" would be rewritten wholesale on every update and would lose anything
you added.

**Anything below the marker is yours.** The generated part ends at a line this
module owns; whatever follows survives every rewrite. That is the whole point of
putting trades in a notebook rather than a report: the value is in what you add.

**Frontmatter that Obsidian can actually query.** Dataview reads the fields, so
`r_multiple`, `outcome` and `symbol` are typed values rather than prose, and the
prose goes in the body where it belongs.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from traidingbrain.domain.proposal import TradeProposal
from traidingbrain.sim.broker import Fill

#: Everything after this line belongs to the person, not to this module.
HANDOFF = "<!-- Alles ab hier bleibt beim Neuschreiben erhalten. -->"

#: Where trade notes live inside the vault.
TRADES_DIR = "Business/traidingBrain/Trades"

#: Frontmatter key holding the generated body's fingerprint, so an unchanged
#: trade is not rewritten and its file modification time stays meaningful.
STAMP = "generiert_aus"


@dataclass(frozen=True)
class WriteResult:
    path: Path
    created: bool
    skipped: bool

    def describe(self) -> str:
        if self.skipped:
            return f"unveraendert: {self.path.name}"
        return f"{'neu' if self.created else 'aktualisiert'}: {self.path.name}"


def note_name(fill: Fill, symbol: str) -> str:
    """`2026-09-30 1412 BTCUSDT long +1.82R.md`.

    Sortable by name, and the outcome is visible in a file listing -- which is how
    anyone actually browses a folder of trades.
    """
    closed = datetime.fromtimestamp(fill.closed_ts / 1000, tz=UTC)
    sign = "+" if fill.r_multiple >= 0 else ""
    safe = re.sub(r"[^\w.+-]", "_", f"{symbol} {fill.side.value} {sign}{fill.r_multiple:.2f}R")
    return f"{closed:%Y-%m-%d %H%M} {safe}.md"


def write_trade(
    vault_root: Path,
    fill: Fill,
    proposal: TradeProposal | None = None,
    *,
    subdir: str = TRADES_DIR,
) -> WriteResult:
    """Write or update one trade note, preserving anything hand-written.

    `proposal` carries the reasoning and the factor breakdown. It is optional
    because a fill can outlive the proposal that produced it, and a note with the
    numbers and no argument is still worth more than no note.
    """
    directory = vault_root / subdir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / note_name(fill, proposal.symbol if proposal else "unknown")

    body = _render(fill, proposal)
    # sha256, deliberately not Python's hash(): that is salted per process, so a
    # fingerprint built on it differs on every run and "unchanged" never matches.
    # The note would be rewritten each time and its modification date would stop
    # meaning anything.
    fingerprint = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]

    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing and f"{STAMP}: {fingerprint}" in existing:
        return WriteResult(path, created=False, skipped=True)

    kept = _hand_written_part(existing)
    path.write_text(
        _frontmatter(fill, proposal, fingerprint) + body + kept,
        encoding="utf-8",
    )
    return WriteResult(path, created=not existing, skipped=False)


def _hand_written_part(existing: str) -> str:
    """Everything the person added below the marker, or an empty section."""
    if HANDOFF in existing:
        return existing[existing.index(HANDOFF) :]
    return f"{HANDOFF}\n\n## Eigene Notizen\n\n"


def _frontmatter(fill: Fill, proposal: TradeProposal | None, fingerprint: str) -> str:
    """Typed fields, because Dataview queries them and prose cannot be queried."""
    opened = datetime.fromtimestamp(fill.opened_ts / 1000, tz=UTC)
    closed = datetime.fromtimestamp(fill.closed_ts / 1000, tz=UTC)
    symbol = proposal.symbol if proposal else "unknown"
    won = fill.r_multiple > 0
    lines = [
        "---",
        "typ: trade",
        f"symbol: {symbol}",
        f"richtung: {fill.side.value}",
        f"ergebnis: {'gewinn' if won else 'verlust'}",
        f"r_multiple: {fill.r_multiple:.3f}",
        f"netto: {fill.net_pnl:.2f}",
        f"hebel: {fill.leverage:g}",
        f"ausstieg: {fill.reason.value}",
        f"eroeffnet: {opened:%Y-%m-%d %H:%M}",
        f"geschlossen: {closed:%Y-%m-%d %H:%M}",
        f"gehalten_stunden: {(fill.closed_ts - fill.opened_ts) / 3_600_000:.1f}",
    ]
    if proposal is not None:
        lines.append(f"confidence: {proposal.confidence:.0f}")
        lines.append(f"bias: {proposal.bias.value}")
    lines.append(f"{STAMP}: {fingerprint}")
    lines.append(f"aktualisiert: {datetime.now(tz=UTC):%Y-%m-%d}")
    lines.append("tags: [trade, traidingbrain]")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def _render(fill: Fill, proposal: TradeProposal | None) -> str:
    """The generated body: what was claimed, and what happened."""
    symbol = proposal.symbol if proposal else "unknown"
    direction = fill.side.value.upper()
    verdict = "Gewinn" if fill.r_multiple > 0 else "Verlust"

    parts = [
        f"# {direction} {symbol} — {fill.r_multiple:+.2f}R",
        "",
        f"**{verdict}** von {fill.net_pnl:+,.2f}, geschlossen durch "
        f"`{fill.reason.value}` nach "
        f"{(fill.closed_ts - fill.opened_ts) / 3_600_000:.1f} Stunden.",
        "",
        "## Zahlen",
        "",
        "| | |",
        "|---|---|",
        f"| Einstieg | {fill.entry_price:,.2f} |",
        f"| Ausstieg | {fill.exit_price:,.2f} |",
        f"| Menge | {fill.qty:g} bei {fill.leverage:g}x |",
        f"| Riskiert | {fill.risk_amount:,.2f} |",
        f"| Brutto | {fill.gross_pnl:+,.2f} |",
        f"| Gebühren | {fill.fees:,.2f} |",
        f"| Funding | {fill.funding:+,.2f} |",
        f"| **Netto** | **{fill.net_pnl:+,.2f}** |",
        "",
    ]

    if proposal is not None:
        parts += _argument_section(proposal)

    parts += [
        "## Was das Ergebnis nicht sagt",
        "",
        "Ein einzelner Trade beweist nichts über die Strategie — weder ein Gewinn",
        "noch ein Verlust. Was hier zählt: War die *Begründung* tragfähig, und ist",
        "sie es rückblickend immer noch?",
        "",
    ]
    return "\n".join(parts)


def _argument_section(proposal: TradeProposal) -> list[str]:
    """The claim the system made, so it can be judged against the outcome."""
    parts = [
        "## Die Begründung von damals",
        "",
        f"Confidence **{proposal.confidence:.0f}**, Bias {proposal.bias.value}, "
        f"Risiko {proposal.risk_level.value}.",
        "",
    ]
    if proposal.confidence_cap_reason:
        parts += [
            f"> Gedeckelt von {proposal.confidence_raw:.1f} auf "
            f"{proposal.confidence:.0f} — {proposal.confidence_cap_reason}",
            "",
        ]
    if proposal.factors:
        parts += ["| Faktor | Punkte | Gewicht | Lesart |", "|---|---:|---:|---|"]
        parts += [
            f"| {f.factor.value} | {f.contribution:+.1f} | {f.weight:.0%} | {f.reasoning} |"
            for f in proposal.factors
        ]
        parts.append("")
    if proposal.reasoning:
        parts += ["**Begründung:**", ""] + [f"- {line}" for line in proposal.reasoning] + [""]
    if proposal.invalidation_note:
        parts += [f"**Falsch, wenn:** {proposal.invalidation_note}", ""]
    return parts
