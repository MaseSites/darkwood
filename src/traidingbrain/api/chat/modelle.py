"""Typen des Chats im Darkwood Terminal."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from traidingbrain.api.terminal import OrderWunsch
from traidingbrain.risk.limits import AccountState


class Vorschlag(BaseModel):
    """Ein Handelsvorschlag aus dem Chat; fehlende Angaben ergaenzt der Bot."""

    symbol: str
    side: Literal["long", "short"]
    margin_usd: float | None = None
    leverage: float | None = None
    sl: float | None = None
    tp: float | None = None

    @field_validator("symbol")
    @classmethod
    def _symbol_normalisieren(cls, v: str) -> str:
        v = v.strip().upper()
        return v if v.endswith("USDT") else v + "USDT"


class Setup(BaseModel):
    timeframe: str
    side: str
    entry: float
    stop: float
    target: float


class Regel(BaseModel):
    nr: int
    name: str
    status: Literal["erfuellt", "verletzt", "unbekannt"]
    wert: str
    grenze: str
    hinweis: str | None = None


class Urteil(BaseModel):
    angenommen: bool
    regeln: list[Regel]
    order: OrderWunsch | None
    stop_vom_bot: bool
    preis: float | None


class Regelwerte(BaseModel):
    require_agreement: bool
    timeframes: list[str]
    margin_share: float
    leverage: float
    risk_cap_share: float
    max_cost_fraction: float
    max_leverage: float
    kosten_roundtrip: float


class Lage(BaseModel):
    """Marktlage zum Vorschlag; None heisst unbekannt."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    symbol: str
    timeframe: str
    preis: float | None
    bild: Literal["long", "short", "neutral"] | None
    setups: list[Setup] | None
    folgt: bool
    konto: AccountState
    quellen: dict[str, str]
    kontext: dict
