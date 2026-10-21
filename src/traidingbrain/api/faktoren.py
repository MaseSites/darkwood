"""Jeder Faktor aufgeschlüsselt: woraus er besteht, und mit welchem Gewicht.

**Was hier NICHT passiert.** Es wird kein zweites Bewertungsmodell gebaut. Die
Gewichte kommen aus `score/engine.py` und `score/findings.py` — importiert, nicht
abgeschrieben. Eine Kopie der Tabellen hier würde nach der ersten Änderung an der
Engine eine Aufschlüsselung zeigen, die zum angezeigten Rating nicht mehr passt,
und das wäre schlimmer als keine Aufschlüsselung: ein erfundener Rechenweg, der
aussieht wie der echte.

**Der Rechenweg, den die Oberfläche nennen muss.** Eine Familie summiert ihre
Mitglieder *nicht*. Innerhalb einer Zeitebene entscheidet der **Median** der
vorzeichenbehafteten Stärken, über die Zeitebenen hinweg ein **gewichteter
Median**. Das heisst: ein Gewicht entscheidet hier nicht, wie viel ein Messwert
*beiträgt*, sondern wie schwer er wiegt, wenn ausgewählt wird, wer in der Mitte
liegt. Darum steht neben keinem Unterfaktor eine Beitragszahl — die gibt es
nicht, und sie zu erfinden wäre die naheliegendste Lüge dieses Bildschirms.

Was ein Unterfaktor stattdessen trägt, ist die vollständige Herkunft seines
Gewichts:

    Gewicht = Familie × Regime × Zeitebene × Unabhängigkeit × Frische

Jeder der fünf Teile steht einzeln da, mit dem Grund, warum er so gross ist.
Das ist die „situationsabhängige Bewertung“: dieselbe RSI-Messung wiegt im
Seitwärtsmarkt das Vierfache ihres Werts im Trend (Regime 1.40 gegen 0.35),
und ein Fair-Value-Gap, das seine Ursprungskerze nennt, zählt die Hälfte.

**Was weggelassen wird, und warum das dazugehört.** Nicht-direktionale Messwerte
(ADX, ATR, Choppiness, relatives Volumen) stimmen nicht mit ab. Sie haben eine
Grösse, aber keine Seite, und sie neutral mitstimmen zu lassen würde die
Abwesenheit einer Meinung in eine verwandeln. Sie stehen unter `kontext`, weil
„wird nicht gezählt“ und „wurde nicht gemessen“ verschiedene Dinge sind.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel

from traidingbrain.domain.enums import Bias, RegimeKind, Timeframe
from traidingbrain.score.engine import (
    DEFAULT_FAMILY_WEIGHTS,
    FRESHNESS_HALF_LIFE_BARS,
    MIN_AGREEMENT,
    REGIME_MODIFIERS,
)
from traidingbrain.score.findings import (
    TIMEFRAME_WEIGHTS,
    Family,
    Finding,
    independence_weights,
)
from traidingbrain.score.reading import ScoreReading
from traidingbrain.score.registry import SPECS

# --------------------------------------------------------------------------- #
# Lesbare Namen
# --------------------------------------------------------------------------- #

#: Was ein Indikator messen soll, in einem Satzteil. Nur die 42 registrierten.
#:
#: Die Namen stehen hier und nicht in der Registry, weil die Registry der
#: Entscheidungspfad ist: eine Beschriftung dort zu ändern würde den
#: Codestand-Stempel verschieben und damit die laufende Vorwärtsstichprobe
#: unterbrechen, für eine Textänderung auf einem Bildschirm.
NAMEN: dict[str, str] = {
    "sma_50": "SMA 50 — Abstand zum 50er-Mittel",
    "sma_200": "SMA 200 — Abstand zum 200er-Mittel",
    "ema_21": "EMA 21 — Abstand zum schnellen Mittel",
    "ema_55": "EMA 55 — Abstand zum mittleren Mittel",
    "macd_hist": "MACD-Histogramm",
    "adx_14": "ADX 14 — Trendstärke (ohne Richtung)",
    "dmi_14": "DMI 14 — Richtungsindex",
    "supertrend_10": "SuperTrend 10",
    "psar": "Parabolic SAR",
    "aroon_25": "Aroon 25",
    "vortex_14": "Vortex 14",
    "trix_15": "TRIX 15",
    "ppo": "PPO — prozentualer Oszillator",
    "hma_21": "Hull-Mittel 21",
    "kama_20": "KAMA 20 — adaptives Mittel",
    "rsi_14": "RSI 14",
    "stoch_14": "Stochastik 14",
    "stochrsi_14": "Stoch-RSI 14",
    "willr_14": "Williams %R 14",
    "cci_20": "CCI 20",
    "roc_12": "ROC 12 — Änderungsrate",
    "cmo_14": "CMO 14 — Chande-Momentum",
    "fisher_9": "Fisher-Transformation 9",
    "ultimate_osc": "Ultimate Oscillator",
    "atr_14": "ATR 14 — Spannweite (ohne Richtung)",
    "bb_width_20": "Bollinger-Breite 20 (ohne Richtung)",
    "bb_position_20": "Lage im Bollinger-Band",
    "keltner_pos_20": "Lage im Keltner-Kanal",
    "donchian_pos_20": "Lage im Donchian-Kanal",
    "hist_vol_30": "Historische Volatilität 30 (ohne Richtung)",
    "choppiness_14": "Choppiness 14 (ohne Richtung)",
    "rvol_20": "Relatives Volumen 20 (ohne Richtung)",
    "obv": "On-Balance-Volumen",
    "cmf_20": "Chaikin-Geldfluss 20",
    "mfi_14": "Money-Flow-Index 14",
    "force_index_13": "Force-Index 13",
    "accum_dist": "Akkumulation/Distribution",
    "vwap_session": "VWAP — Abstand zum Sitzungsmittel",
    "range_position_20": "Lage in der Spanne 20",
    "prev_day_position": "Lage zum Vortagesbereich",
    "prev_week_position": "Lage zur Vorwoche",
    "pivot_position": "Lage zum Pivot",
}

#: Beobachtungen aus der Struktur- und Liquiditätsanalyse. Keine Indikatoren —
#: sie beschreiben ein Ereignis und tragen darum eine Frische.
BEOBACHTUNG_NAMEN: dict[str, str] = {
    "structure_trend": "Strukturtrend (höhere Hochs/Tiefs)",
    "structure_bos": "Bruch der Struktur (BOS)",
    "structure_choch": "Richtungswechsel der Struktur (CHoCH)",
    "liquidity_sweep": "Liquiditäts-Sweep",
    "fvg_bullish": "Fair-Value-Gap aufwärts",
    "fvg_bearish": "Fair-Value-Gap abwärts",
    "equal_highs": "Gleiche Hochs",
    "equal_lows": "Gleiche Tiefs",
    "zone_demand": "Nachfragezone",
    "zone_supply": "Angebotszone",
}


#: Die Schwaechen der Registry auf Deutsch. Die Registry haelt sie auf
#: Englisch, weil sie im Entscheidungspfad liegt und eine Textaenderung dort
#: den Codestand-Stempel verschieben wuerde. Uebersetzt, nicht umformuliert:
#: jede Zeile sagt dasselbe wie das Original. Eine fehlende Uebersetzung
#: faellt auf das Original zurueck, statt die Zeile zu verschlucken.
SCHWAECHE_DE: dict[str, str] = {
    'DI cross alone taken as an entry':
        'Ein DI-Kreuz allein als Einstieg genommen',
    'a derivative of a derivative; noisier than either':
        'Ableitung einer Ableitung — rauschiger als beide',
    'a divergence can persist for a long time without resolving':
        'Eine Divergenz kann sehr lange bestehen, ohne sich aufzulösen',
    'a range must be chosen before the position means anything':
        'Erst mit einer gewählten Spanne bedeutet die Lage etwas',
    'adapts its own lag, so the lag field is an estimate':
        'Passt seine Verzögerung selbst an — die Lag-Angabe ist eine Schätzung',
    'an extreme is not a reversal guarantee':
        'Ein Extrem ist keine Garantie für eine Umkehr',
    'anchor and feed change the number':
        'Ankerpunkt und Datenquelle verändern die Zahl',
    "assigns a whole bar's volume to one direction":
        'Wirft das ganze Volumen einer Kerze auf eine Richtung',
    'close position is a proxy, not real order flow':
        'Die Schlusslage ist ein Stellvertreter, kein echter Orderfluss',
    'cross without regime context':
        'Kreuzung ohne das Regime daneben gelesen',
    'crossover read as a forecast':
        'Eine Kreuzung als Vorhersage gelesen',
    'describes the last 200 bars, not now':
        'Beschreibt die letzten 200 Kerzen, nicht jetzt',
    'describes trendiness, not which way':
        'Beschreibt, wie trendig es ist — nicht wohin',
    'dominated by outliers in the lookback':
        'Von Ausreissern im Rückblickfenster dominiert',
    'every flip traded in a flat range':
        'Jeder Umschlag in einer flachen Spanne wird gehandelt',
    'extremes persist in trends, like RSI':
        'Extreme halten im Trend lange, wie beim RSI',
    'fixed thresholds are market and lookback dependent':
        'Feste Schwellen hängen vom Markt und vom Fenster ab',
    'flips repeatedly in a sideways market':
        'Schlägt im Seitwärtsmarkt wiederholt um',
    'high ADX read as bullish -- it is strength, not direction':
        'Hoher ADX als bullisch gelesen — er misst Stärke, nicht Richtung',
    'histogram sign flips on noise':
        'Das Vorzeichen des Histogramms kippt auf Rauschen',
    'lags every turn by half the lookback':
        'Hinkt jeder Wende um die halbe Fensterlänge nach',
    'late, and fakeout-prone in a range':
        'Spät, und in einer Spanne anfällig für Fehlausbrüche',
    'loses relevance as distance grows':
        'Verliert an Bedeutung, je weiter der Preis weg ist',
    'many pivot formulas; no level is guaranteed':
        'Viele Pivot-Formeln — kein Niveau ist gesichert',
    'meaningless inside a range':
        'Innerhalb einer Spanne bedeutungslos',
    'measures time since an extreme, not size of move':
        'Misst die Zeit seit einem Extrem, nicht die Grösse der Bewegung',
    'mirrors Stochastic; not independent confirmation':
        'Spiegelt die Stochastik — keine unabhängige Bestätigung',
    'new smoothing is not a new information source':
        'Eine neue Glättung ist keine neue Informationsquelle',
    'no direct identification of institutional flow':
        'Keine direkte Erkennung institutionellen Flusses',
    'no direction; rises in selloffs too':
        'Keine Richtung — steigt auch im Ausverkauf',
    'overbought persists through a strong trend':
        'Überkauft bleibt durch einen starken Trend hindurch bestehen',
    'past dispersion does not price jump risk':
        'Vergangene Streuung bepreist kein Sprungrisiko',
    'price change times volume; dominated by gaps':
        'Preisänderung mal Volumen — von Lücken dominiert',
    'same family as RSI; agreement is not evidence':
        'Dieselbe Familie wie der RSI — Einigkeit ist kein Beleg',
    'same information as MACD, scaled':
        'Dieselbe Information wie der MACD, nur skaliert',
    'several EMAs counted as independent signals':
        'Mehrere EMAs als unabhängige Signale gezählt',
    'three lookbacks blended; no single timescale':
        'Drei Fenster vermischt — keine eine Zeitskala',
    'touching a band is not a reversal':
        'Ein Band zu berühren ist keine Umkehr',
    'transform exaggerates extremes by construction':
        'Die Transformation übertreibt Extreme von Bauart her',
    'triple smoothing makes it very late':
        'Dreifache Glättung macht ihn sehr spät',
    'volume is participation, never direction':
        'Volumen ist Beteiligung, nie Richtung',
    'whipsaws in flat markets':
        'Sägt in flachen Märkten hin und her',
    'whipsaws when the range contracts':
        'Sägt hin und her, wenn die Spanne sich zusammenzieht',
    'width is expansion, not direction':
        'Die Breite ist Ausdehnung, nicht Richtung',
}
FAMILIE_NAMEN: dict[Family, str] = {
    Family.TREND: "Trend",
    Family.MOMENTUM: "Momentum",
    Family.VOLATILITY: "Volatilität",
    Family.VOLUME: "Volumen",
    Family.STRUCTURE: "Struktur",
    Family.LOCATION: "Lage",
    Family.LIQUIDITY: "Liquidität",
    Family.TIME_NEWS: "Zeit & Nachrichten",
    Family.POSITIONING: "Positionierung",
    Family.HISTORY: "History",
}

REGIME_NAMEN: dict[RegimeKind, str] = {
    RegimeKind.TREND_UP: "Aufwärtstrend",
    RegimeKind.TREND_DOWN: "Abwärtstrend",
    RegimeKind.RANGE: "Seitwärts",
    RegimeKind.MANIPULATION: "Manipulation",
    RegimeKind.UNKNOWN: "unklar",
}

#: Welche Familien hinter welcher Karte des Bot-Panels stehen.
#:
#: Diese Zuordnung ist dieselbe wie in `terminal.score()`. Sie steht hier
#: zweitens, und das ist ein bekannter Preis: eine Karte, die dort anders
#: zusammengesetzt wird als hier, zeigte eine Aufschlüsselung, die ihre eigene
#: Zahl nicht erklärt. Darum prüft `tests/test_faktoren.py` beide gegeneinander.
KARTE_FAMILIEN: dict[str, tuple[Family, ...]] = {
    "chart": (Family.STRUCTURE, Family.LOCATION, Family.TREND),
    "liquiditaet": (Family.LIQUIDITY,),
    "volumen": (Family.VOLUME,),
    "priceaction": (Family.MOMENTUM, Family.VOLATILITY),
    "zonen": (Family.LOCATION,),
    "chartpattern": (Family.STRUCTURE,),
    "candles": (Family.MOMENTUM, Family.VOLATILITY),
    "trend": (Family.TREND,),
    "indikatoren": tuple(Family),
}

#: Karten, deren Unterfaktoren nicht aus dem Messwerk kommen.
EIGENE_QUELLE = ("kalender", "orderbuch", "entry", "history")


# --------------------------------------------------------------------------- #
# Modelle
# --------------------------------------------------------------------------- #


class Gewichtsteil(BaseModel):
    name: str
    wert: float
    grund: str


class Unterfaktor(BaseModel):
    key: str
    label: str
    familie: str
    zeitebene: str
    richtung: str
    staerke: float
    """0..1. Wie emphatisch, nicht wie wahrscheinlich."""

    sterne: int
    gewicht: float
    """Produkt aller Teile unten. Kein Beitrag — siehe Modul-Docstring."""

    teile: list[Gewichtsteil]
    wert: str
    quelle: str
    schwaechen: list[str]
    frische_kerzen: int | None
    abstand_atr: float | None
    zaehlt: bool
    """Falsch, wenn die Familie zerfallen ist oder der Messwert neutral steht."""

    grund_nicht: str


class FamilieZeile(BaseModel):
    familie: str
    richtung: str
    staerke: float
    einigkeit: float
    ebenen_einigkeit: float
    mitglieder: int
    grundgewicht: float
    regime_faktor: float
    beitrag: float
    zerfallen: bool
    grund: str


class Kontextwert(BaseModel):
    label: str
    wert: str
    zeitebene: str
    grund: str


class FaktorDetail(BaseModel):
    key: str
    label: str
    erklaerung: str
    rechenweg: str
    regime: str
    unterfaktoren: list[Unterfaktor]
    familien: list[FamilieZeile]
    kontext: list[Kontextwert]
    hinweis: str
    gemessen: bool


# --------------------------------------------------------------------------- #
# Hilfen
# --------------------------------------------------------------------------- #


def _sterne(x: float) -> int:
    return max(0, min(5, round(max(0.0, min(1.0, x)) * 5)))


def _richtungswort(b: Bias | str) -> str:
    s = b.value if isinstance(b, Bias) else str(b)
    return {"bullish": "long", "bearish": "short", "neutral": "neutral"}.get(s, s)


def _frische_faktor(bars: int | None) -> float:
    """Dieselbe Rechnung wie `engine._freshness_factor`.

    Nachgebaut statt importiert, weil die Engine-Funktion privat ist. Die
    Halbwertszeit kommt aus derselben Konstante, also wandert sie mit.
    """
    if bars is None or bars <= 0:
        return 1.0
    return float(0.5 ** (bars / FRESHNESS_HALF_LIFE_BARS))


def _stamm(key: str) -> str:
    """Der Spec-Name in einem Finding-Schlüssel `name_zeitebene`."""
    for name in SPECS:
        if key == f"{name}_{key.rsplit('_', 1)[-1]}":
            return name
    return ""


def _label_fuer(f: Finding) -> tuple[str, bool]:
    """Lesbarer Name, und ob das Finding ein registrierter Indikator ist."""
    stamm = _stamm(f.key)
    if stamm:
        return NAMEN.get(stamm, stamm), True
    for praefix, name in BEOBACHTUNG_NAMEN.items():
        if f.key.startswith(praefix):
            return name, False
    return f.label or f.key, False


def _wertext(f: Finding) -> str:
    """Der gemessene Wert, so wie das Finding ihn trägt."""
    stamm = _stamm(f.key)
    if stamm and f.label.startswith(stamm):
        return f.label[len(stamm):].strip() or "—"
    return f.label or "—"


def _unterfaktor(
    f: Finding,
    *,
    regime: RegimeKind,
    unabh: dict[str, float],
    zerfallen: set[Family],
) -> Unterfaktor:
    fam_gewicht = DEFAULT_FAMILY_WEIGHTS.get(f.family, 0.0)
    regime_faktor = REGIME_MODIFIERS.get(regime, {}).get(f.family, 1.0)
    tf_gewicht = TIMEFRAME_WEIGHTS.get(f.timeframe, 1.0)
    u = unabh.get(f.key, 1.0)
    fr = _frische_faktor(f.freshness_bars)

    stamm = _stamm(f.key)
    spec = SPECS.get(stamm) if stamm else None
    label, _ = _label_fuer(f)

    teile = [
        Gewichtsteil(
            name="Familie",
            wert=round(fam_gewicht, 3),
            grund=(
                f"{FAMILIE_NAMEN.get(f.family, f.family.value)} steht in der "
                f"Engine auf {fam_gewicht:.2f} — ein Startwert aus den Quellen, "
                f"der gegen Ergebnisse gemessen wird, nicht gegen Argumente."
            ),
        ),
        Gewichtsteil(
            name="Regime",
            wert=round(regime_faktor, 3),
            grund=(
                f"Im Regime {REGIME_NAMEN.get(regime, regime.value)} "
                + (
                    f"wiegt diese Familie das {regime_faktor:.2f}-fache."
                    if regime_faktor != 1.0
                    else "ändert das Regime an dieser Familie nichts."
                )
            ),
        ),
        Gewichtsteil(
            name="Zeitebene",
            wert=round(tf_gewicht, 3),
            grund=(
                f"{f.timeframe.value} wiegt {tf_gewicht:.2f} bei der Richtung. "
                f"Die Wochen- und Tagesebene setzen den Rahmen; M15 ist zum "
                f"Timing da und hat über die Richtung nicht mitzureden."
            ),
        ),
        Gewichtsteil(
            name="Unabhängigkeit",
            wert=round(u, 3),
            grund=(
                "Eigenständig — nennt keine andere Messung als Ursache."
                if u >= 1.0
                else (
                    f"Geteilt durch 1 + {round(1 / u - 1)} genannte Ursache(n): "
                    f"{', '.join(f.depends_on) or '—'}. Dasselbe Ereignis zweimal "
                    f"gezählt wäre zwei Belege, wo einer ist."
                )
            ),
        ),
        Gewichtsteil(
            name="Frische",
            wert=round(fr, 3),
            grund=(
                "Eine Indikatorlesung ist über jetzt und hat kein Alter."
                if f.freshness_bars is None
                else (
                    f"{f.freshness_bars} Kerzen alt, Halbwertszeit "
                    f"{FRESHNESS_HALF_LIFE_BARS:.0f} Kerzen."
                )
            ),
        ),
    ]

    neutral = f.direction is Bias.NEUTRAL
    fam_zerfallen = f.family in zerfallen
    if neutral:
        grund_nicht = (
            "Steht neutral. Eine Lesung ohne Seite trägt kein Gewicht — sie "
            "neutral mitstimmen zu lassen würde die Abwesenheit einer Meinung "
            "in eine verwandeln."
        )
    elif fam_zerfallen:
        grund_nicht = (
            f"Die Familie {FAMILIE_NAMEN.get(f.family, f.family.value)} ist "
            f"zerfallen (Einigkeit unter {MIN_AGREEMENT:.2f}) und schweigt "
            f"ganz. Diese Messung wird gemessen, aber nicht gewertet."
        )
    else:
        grund_nicht = ""

    return Unterfaktor(
        key=f.key,
        label=label,
        familie=FAMILIE_NAMEN.get(f.family, f.family.value),
        zeitebene=f.timeframe.value,
        richtung=_richtungswort(f.direction),
        staerke=round(f.strength, 4),
        sterne=_sterne(f.strength),
        gewicht=round(fam_gewicht * regime_faktor * tf_gewicht * u * fr, 4),
        teile=teile,
        wert=_wertext(f),
        quelle=f.source,
        schwaechen=[SCHWAECHE_DE.get(m, m) for m in spec.failure_modes] if spec else [],
        frische_kerzen=f.freshness_bars,
        abstand_atr=round(f.distance_atr, 3) if f.distance_atr is not None else None,
        zaehlt=not (neutral or fam_zerfallen),
        grund_nicht=grund_nicht,
    )


RECHENWEG = (
    "Eine Familie summiert ihre Mitglieder nicht. Innerhalb einer Zeitebene "
    "entscheidet der Median der vorzeichenbehafteten Stärken, über die Ebenen "
    "hinweg ein gewichteter Median. Ein Gewicht sagt darum nicht, wie viel ein "
    "Messwert beiträgt, sondern wie schwer er wiegt, wenn ausgewählt wird, wer "
    "in der Mitte liegt. Darum steht neben keiner Zeile eine Beitragszahl — die "
    "gibt es nicht."
)


# --------------------------------------------------------------------------- #
# Die Aufschlüsselung
# --------------------------------------------------------------------------- #


def aus_messwerk(
    key: str,
    label: str,
    erklaerung: str,
    reading: ScoreReading,
    *,
    nur_indikatoren: bool = False,
) -> FaktorDetail:
    """Die Unterfaktoren eines Faktors, der aus dem Messwerk kommt."""
    familien = KARTE_FAMILIEN.get(key, tuple(Family))
    findings = [f for f in reading.evidence.findings if f.family in familien]
    if nur_indikatoren:
        findings = [f for f in findings if _stamm(f.key)]

    unabh = independence_weights(reading.evidence.findings)
    zerfallen = {
        sf.verdict.family for sf in reading.score.families if sf.split
    }

    unter = [
        _unterfaktor(f, regime=reading.regime, unabh=unabh, zerfallen=zerfallen)
        for f in findings
    ]
    # Schwerstes Gewicht zuerst, dann stärkste Lesung. Nicht alphabetisch:
    # wer die Mitte entscheidet, gehört nach oben.
    unter.sort(key=lambda u: (-u.gewicht, -u.staerke))

    zeilen = [
        FamilieZeile(
            familie=FAMILIE_NAMEN.get(sf.verdict.family, sf.verdict.family.value),
            richtung=_richtungswort(sf.verdict.direction),
            staerke=round(sf.verdict.strength, 4),
            einigkeit=round(sf.verdict.agreement, 3),
            ebenen_einigkeit=round(sf.verdict.timeframe_agreement, 3),
            mitglieder=len(sf.verdict.members),
            grundgewicht=round(sf.base_weight, 3),
            regime_faktor=round(sf.regime_modifier, 3),
            beitrag=round(sf.contribution, 4),
            zerfallen=sf.split,
            grund=(
                _zerfall_grund(sf)
                if sf.split
                else (
                    f"{len(sf.verdict.members)} Mitglieder, Einigkeit "
                    f"{sf.verdict.agreement:.0%}, Ebenen-Einigkeit "
                    f"{sf.verdict.timeframe_agreement:.0%}."
                )
            ),
        )
        for sf in reading.score.families
        if sf.verdict.family in familien
    ]
    zeilen.sort(key=lambda z: -abs(z.beitrag))

    kontext = _kontextwerte(reading, familien)

    return FaktorDetail(
        key=key,
        label=label,
        erklaerung=erklaerung,
        rechenweg=RECHENWEG,
        regime=REGIME_NAMEN.get(reading.regime, reading.regime.value),
        unterfaktoren=unter,
        familien=zeilen,
        kontext=kontext,
        hinweis=(
            f"{len(unter)} Messungen aus {len(zeilen)} Familien über "
            f"{len({u.zeitebene for u in unter})} Zeitebenen. "
            f"{sum(1 for u in unter if not u.zaehlt)} davon zählen hier nicht mit "
            f"und sagen in ihrer Zeile, warum."
        ),
        gemessen=bool(unter),
    )


def _zerfall_grund(sf: Any) -> str:
    v = sf.verdict
    if v.direction is Bias.NEUTRAL:
        return "Die Mitglieder stehen in Summe neutral — keine Seite."
    if v.agreement < MIN_AGREEMENT:
        return (
            f"Die Mitglieder sind sich zu uneinig ({v.agreement:.0%} unter "
            f"{MIN_AGREEMENT:.0%}). Das ist eine ehrliche Antwort und kein "
            f"schwaches Ja."
        )
    return (
        f"Die Zeitebenen widersprechen sich ({v.timeframe_agreement:.0%} unter "
        f"{MIN_AGREEMENT:.0%}). Jede Ebene kann für sich einig sein und trotzdem "
        f"in die andere Richtung zeigen — dann ist der Median eine Auswahl, "
        f"nicht ein Ergebnis."
    )


#: Was ein nicht-direktionaler Messwert über die Lage sagt.
KONTEXT_GRUND: dict[str, str] = {
    "atr_14": "Wie weit sich der Preis je Kerze bewegt. Setzt Stop und Grösse.",
    "adx_14": "Wie stark ein Trend ist — nicht, in welche Richtung.",
    "choppiness_14": "Wie zerhackt die Bewegung ist. Hoch heisst: Trendsignale lügen öfter.",
    "bb_width_20": "Wie weit die Bänder stehen. Eng geht oft einem Ausbruch voraus.",
    "hist_vol_30": "Wie volatil die letzten 30 Kerzen waren.",
    "rvol_20": "Wie viel Volumen gegenüber dem Üblichen läuft.",
}


def _kontextwerte(reading: ScoreReading, familien: tuple[Family, ...]) -> list[Kontextwert]:
    raus: list[Kontextwert] = []
    for tf in (Timeframe.H1, Timeframe.H4, Timeframe.D1):
        werte = reading.context.get(tf)
        if not werte:
            continue
        for name, wert in sorted(werte.items()):
            spec = SPECS.get(name)
            if spec is None or spec.family not in familien:
                continue
            raus.append(
                Kontextwert(
                    label=NAMEN.get(name, name),
                    wert=f"{wert:.4g}",
                    zeitebene=tf.value,
                    grund=KONTEXT_GRUND.get(
                        name, "Hat eine Grösse, aber keine Seite — stimmt nicht mit ab."
                    ),
                )
            )
        break
    return raus


# --------------------------------------------------------------------------- #
# Die vier Faktoren mit eigener Quelle
# --------------------------------------------------------------------------- #


def _leer(key: str, label: str, erklaerung: str, hinweis: str) -> FaktorDetail:
    return FaktorDetail(
        key=key, label=label, erklaerung=erklaerung, rechenweg="", regime="",
        unterfaktoren=[], familien=[], kontext=[], hinweis=hinweis, gemessen=False,
    )


def _teil(name: str, wert: float, grund: str) -> Gewichtsteil:
    return Gewichtsteil(name=name, wert=round(wert, 3), grund=grund)


def aus_kalender(kal: Any) -> FaktorDetail:
    """Jeder Termin einzeln, mit seinem Gewicht nach Schwere und Nähe."""
    if kal is None:
        return _leer(
            "kalender", "Wirtschaftskalender",
            "Termine, die eine Bewegung auslösen können.",
            "Kalender nicht erreichbar — keine Aussage, nicht „keine Termine“.",
        )

    from traidingbrain.api.terminal import IMPACT_GEWICHT

    unter: list[Unterfaktor] = []
    for e in kal.events:
        schwere = IMPACT_GEWICHT.get(e.impact, 0.2)
        # Nähe: ein Termin in einer Stunde ist das Problem, einer in drei Tagen
        # nicht. Linear über 24 h abfallend, wie in `terminal.kalender`.
        naehe = max(0.0, 1.0 - max(0.0, e.hours_away) / 24.0)
        unter.append(Unterfaktor(
            key=f"kal_{e.ts}",
            label=f"{e.country} · {e.title}",
            familie="Zeit & Nachrichten",
            zeitebene="Termin",
            richtung="neutral",
            staerke=round(schwere * naehe, 4),
            sterne=_sterne(schwere * naehe),
            gewicht=round(schwere * naehe, 4),
            teile=[
                _teil("Schwere", schwere, f"Einstufung „{e.impact}“ der Quelle."),
                _teil("Nähe", naehe, (
                    f"{e.hours_away:.1f} h entfernt. Linear über 24 h abfallend — "
                    f"ein Termin in drei Tagen bewegt diese Kerze nicht."
                )),
            ],
            wert=(f"Prognose {e.forecast or '—'} · vorher {e.previous or '—'}"
                  + (f" · tatsächlich {e.actual}" if e.actual else "")),
            quelle="Wirtschaftskalender",
            schwaechen=[
                "Richtung unbekannt: ein Termin sagt, dass es sich bewegt, nicht wohin",
                "die Einstufung der Schwere ist fremd und wird hier nicht geprüft",
            ],
            frische_kerzen=None,
            abstand_atr=None,
            zaehlt=e.hours_away >= 0,
            grund_nicht="" if e.hours_away >= 0 else "Liegt in der Vergangenheit.",
        ))
    unter.sort(key=lambda u: -u.gewicht)

    return FaktorDetail(
        key="kalender", label="Wirtschaftskalender",
        erklaerung=(
            "Termine, die eine Bewegung auslösen können. Dieser Faktor zeigt nie "
            "eine Richtung, nur ein Risiko — und drückt darum das Rating, egal "
            "wohin der Rest zeigt."
        ),
        rechenweg=(
            "Gewicht = Schwere × Nähe. Das Maximum über alle Termine wird zum "
            "Risiko des Faktors; es wird nicht summiert, weil zwei Termine in "
            "derselben Stunde nicht doppelt so gefährlich sind."
        ),
        regime="", unterfaktoren=unter, familien=[], kontext=[],
        hinweis=(f"{kal.high_within_24h} schwere Termine in 24 h · "
                 f"Risiko {kal.risk_pct:.0f} %. {kal.note}"),
        gemessen=True,
    )


def aus_orderbuch(buch: Any) -> FaktorDetail:
    """Jede Preisstufe einzeln, mit ihrem Anteil am sichtbaren Buch."""
    if buch is None:
        return _leer(
            "orderbuch", "Orderbuch",
            "Was an Geboten und Angeboten sichtbar daliegt.",
            "Nicht erreichbar — keine Aussage.",
        )

    gesamt = (buch.bid_total + buch.ask_total) or 1.0
    unter: list[Unterfaktor] = []
    for seite, zeilen, richtung in (("Gebot", buch.bids, "long"), ("Angebot", buch.asks, "short")):
        for preis, menge in zeilen:
            anteil = (preis * menge) / gesamt if gesamt else 0.0
            abstand_bp = abs(preis - (buch.bids[0][0] if buch.bids else preis)) / max(preis, 1e-9) * 10_000
            unter.append(Unterfaktor(
                key=f"ob_{seite}_{preis}",
                label=f"{seite} bei {preis:,.4g}".replace(",", "'"),
                familie="Liquidität",
                zeitebene="jetzt",
                richtung=richtung,
                staerke=round(min(1.0, anteil * len(zeilen) * 2), 4),
                sterne=_sterne(min(1.0, anteil * len(zeilen) * 2)),
                gewicht=round(anteil, 4),
                teile=[
                    _teil("Anteil am Buch", anteil, (
                        f"{anteil:.1%} des sichtbaren Nominals in dieser Tiefe."
                    )),
                    _teil("Abstand", 1.0, f"{abstand_bp:.1f} bp vom besten Gebot."),
                ],
                wert=f"{menge:,.4g} zu {preis:,.4g}".replace(",", "'"),
                quelle="Binance-Tiefe",
                schwaechen=[
                    "anonym: institutionell und privat sind hier nicht zu trennen",
                    "eine ruhende Order verschwindet, bevor der Preis sie erreicht — "
                    "bis zu 49 % je 17 s gemessen",
                ],
                frische_kerzen=None,
                abstand_atr=None,
                zaehlt=True,
                grund_nicht="",
            ))
    unter.sort(key=lambda u: -u.gewicht)

    return FaktorDetail(
        key="orderbuch", label="Orderbuch",
        erklaerung=(
            "Was an Geboten und Angeboten sichtbar daliegt, in den obersten "
            "Preisstufen. Kein Beleg über Absicht: ruhende Orders werden "
            "zurückgezogen, und dieses Buch kann keinen Fill beweisen."
        ),
        rechenweg=(
            "Gewicht = Nominal dieser Stufe geteilt durch das sichtbare Nominal "
            "insgesamt. Die Kartenzahl ist der Gebotsanteil, auf -100..100 "
            "gestreckt — nicht die Summe der Zeilen."
        ),
        regime="", unterfaktoren=unter, familien=[], kontext=[],
        hinweis=(f"{buch.bid_share_pct:.0f} % Gebote, Spread {buch.spread_bp:.2f} bp, "
                 f"{len(unter)} Stufen sichtbar."),
        gemessen=True,
    )


def aus_entry(chart: dict) -> FaktorDetail:
    """Die Bedingungen des Setups, einzeln, und was das Tor dazu sagt."""
    setups = chart.get("setups") or []
    gate = chart.get("gate") or {}
    if not setups:
        return _leer(
            "entry", "Entry-Signal",
            "Ob auf dieser Kerze ein Setup vorliegt.",
            "Kein Setup auf dieser Kerze. Das ist der Normalfall: 93 % der "
            "Kerzen haben keine Zone in Reichweite.",
        )

    s0 = setups[0]
    crv = float(s0.get("reward_risk", 0) or 0)
    unter: list[Unterfaktor] = []

    def zeile(key: str, label: str, staerke: float, wert: str, grund: str,
              schwaechen: list[str], zaehlt: bool = True, nicht: str = "") -> None:
        unter.append(Unterfaktor(
            key=key, label=label, familie="Entry", zeitebene="Signalebene",
            richtung="long" if str(s0.get("side", "")).lower().startswith("l") else "short",
            staerke=round(max(0.0, min(1.0, staerke)), 4),
            sterne=_sterne(staerke), gewicht=round(max(0.0, min(1.0, staerke)), 4),
            teile=[_teil("Bedingung", 1.0, grund)], wert=wert, quelle="Setup-Regel",
            schwaechen=schwaechen, frische_kerzen=None, abstand_atr=None,
            zaehlt=zaehlt, grund_nicht=nicht,
        ))

    zeile("entry_crv", "Chance-Risiko-Verhältnis", min(1.0, crv / 4.0), f"{crv:.2f}",
          "Abstand zum Ziel geteilt durch Abstand zum Stop. Vier und mehr gilt "
          "hier als volle Stärke.",
          ["ein hohes CRV heisst nicht, dass das Ziel erreicht wird — 62.9 % der "
           "Trades berühren ihr Ziel nie"])

    for name, feld, grund in (
        ("Einstieg", "entry", "Der Preis, an dem die Order liegen würde."),
        ("Stop", "stop", "Wo die Hypothese widerlegt ist."),
        ("Ziel", "target", "Wohin die Regel zeigt."),
    ):
        wert = s0.get(feld.lower()) or s0.get(feld)
        if wert is not None:
            zeile(f"entry_{feld}", name, 0.0, f"{float(wert):,.6g}".replace(",", "'"),
                  grund, [])

    for schluessel, name in (("would_ask", "Tor würde fragen"), ("blocking", "Tor blockiert")):
        if schluessel in gate:
            w = gate.get(schluessel)
            zeile(f"gate_{schluessel}", name, 1.0 if w else 0.0,
                  str(w) if w else "nein",
                  "Das Tor entscheidet vor jeder Order neu; eine Regel, die hier "
                  "greift, verhindert den Trade unabhängig vom Rating.",
                  [], zaehlt=bool(w),
                  nicht="" if w else "Greift auf dieser Kerze nicht.")

    return FaktorDetail(
        key="entry", label="Entry-Signal",
        erklaerung=(
            f"Setup {s0.get('key')} liegt vor. Dieser Faktor ist nicht graduell: "
            f"es gibt ein Signal oder keines, und die Karte zeigt darum ±100."
        ),
        rechenweg=(
            "Die Bedingungen sind Teil einer Regel, nicht Stimmen in einer "
            "Abstimmung. Alle müssen gelten; eine gewichtete Summe gibt es hier "
            "nicht, und eine zu zeigen würde eine Regel in eine Meinung verwandeln."
        ),
        regime="", unterfaktoren=unter, familien=[], kontext=[],
        hinweis=(f"Setup {s0.get('key')} · CRV {crv:.2f}"
                 + (f" · Tor: {gate.get('blocking')}" if gate.get("blocking") else "")),
        gemessen=True,
    )


def aus_history(symbol: str, rows: list[dict]) -> FaktorDetail:
    """Die eigenen geschlossenen Trades auf diesem Markt, einzeln."""
    eigene = [r for r in rows if r.get("symbol") == symbol]
    if not eigene:
        return _leer(
            "history", "History",
            "Was dieses System auf diesem Markt tatsächlich verdient hat.",
            f"Noch kein geschlossener Trade auf {symbol}. Keine Aussage — und "
            f"besonders keine gute.",
        )

    unter: list[Unterfaktor] = []
    for i, r in enumerate(eigene):
        r_wert = float(r.get("r_multiple", 0) or 0)
        gewann = r_wert > 0
        unter.append(Unterfaktor(
            key=f"hist_{i}",
            label=f"{r.get('setup') or '?'} {'Gewinn' if gewann else 'Verlust'}",
            familie="History", zeitebene="abgeschlossen",
            richtung="long" if gewann else "short",
            staerke=round(min(1.0, abs(r_wert) / 2.0), 4),
            sterne=_sterne(min(1.0, abs(r_wert) / 2.0)),
            gewicht=round(1.0 / len(eigene), 4),
            teile=[_teil("Anteil", 1.0 / len(eigene), (
                f"Einer von {len(eigene)} Trades. Jeder zählt gleich — eine "
                f"Gewichtung nach Ergebnis würde die Gewinner lauter machen, "
                f"und genau das soll diese Zeile nicht tun."
            ))],
            wert=f"{r_wert:+.2f} R",
            quelle="eigenes Journal",
            schwaechen=[
                f"{len(eigene)} Trades sind weit von einer Aussage entfernt — "
                f"das Projekt braucht gemessen rund 100 je Frage",
            ],
            frische_kerzen=None, abstand_atr=None, zaehlt=True, grund_nicht="",
        ))

    treffer = sum(1 for u in unter if u.richtung == "long") / len(unter)
    summe = sum(float(r.get("r_multiple", 0) or 0) for r in eigene)
    return FaktorDetail(
        key="history", label="History",
        erklaerung=(
            "Was dieses System auf diesem Markt tatsächlich verdient hat. Die "
            "einzige Zeile im Panel, die aus Ergebnissen kommt und nicht aus "
            "einer Messung des Charts."
        ),
        rechenweg=(
            "Trefferquote minus 50 %, auf -100..100 gestreckt. Die Sterne der "
            "Karte stehen für die ANZAHL, nicht für das Ergebnis: zwanzig Trades "
            "geben fünf Sterne, zwei geben einen — unabhängig davon, wie sie "
            "ausgingen."
        ),
        regime="", unterfaktoren=unter, familien=[], kontext=[],
        hinweis=(f"{len(unter)} Trades · {treffer:.0%} Treffer · {summe:+.2f} R. "
                 f"Die gemessene Erwartung des Systems liegt zwischen -0.087 und "
                 f"+0.059 R je Trade — diese Zeile kann das nicht widerlegen."),
        gemessen=True,
    )


# --------------------------------------------------------------------------- #
# Einstieg
# --------------------------------------------------------------------------- #

ERKLAERUNG: dict[str, tuple[str, str]] = {
    "chart": ("Chart", "Struktur, Lage und Trend zusammen — die drei Familien, "
                       "die beschreiben, wo der Preis steht und woher er kommt."),
    "liquiditaet": ("Liquidität", "Sweeps, Fair-Value-Gaps und Pools: Stellen, an "
                                  "denen Orders liegen oder gelegen haben."),
    "volumen": ("Volumen", "Wie viel gehandelt wurde und in welche Richtung der "
                           "Fluss zeigt, relativ zum Üblichen."),
    "priceaction": ("Price-Action", "Momentum und Volatilität — wie schnell und "
                                    "wie heftig sich der Preis bewegt."),
    "zonen": ("Zonen", "Jede Zone im Bild einzeln bewertet: wie weit weg, wie "
                       "oft gehalten, auf welcher Zeitebene entstanden."),
    "chartpattern": ("Chart-Pattern", "Brüche und Richtungswechsel der Struktur: "
                                      "BOS und CHoCH, je Zeitebene."),
    "candles": ("Candlestick-Pattern", "Einzelne Kerzenereignisse — aus Momentum "
                                       "und Volatilität, nicht aus Mustererkennung."),
    "trend": ("Trend", "Die Trendfamilie über fünf Zeitebenen, mit dem Gewicht "
                       "jeder Ebene."),
    "indikatoren": ("Indikatoren", "Alle registrierten Indikatoren über alle "
                                   "Zeitebenen, einzeln. Vier Momentum-Oszillatoren "
                                   "sind EINE Information — darum steht neben jedem "
                                   "seine Familie."),
}


def faktor(
    key: str,
    symbol: str,
    *,
    reading: ScoreReading | None = None,
    chart: dict | None = None,
    buch: Any = None,
    kal: Any = None,
    history_rows: list[dict] | None = None,
) -> FaktorDetail:
    """Die Aufschlüsselung eines Faktors, oder eine ehrliche Absage."""
    if key == "kalender":
        return aus_kalender(kal)
    if key == "orderbuch":
        return aus_orderbuch(buch)
    if key == "entry":
        return aus_entry(chart or {})
    if key == "history":
        return aus_history(symbol, history_rows or [])

    label, erklaerung = ERKLAERUNG.get(key, (key, ""))
    if reading is None:
        return _leer(key, label, erklaerung,
                     "Die Zeitebenen wärmen auf dieser Kerze noch auf.")
    return aus_messwerk(key, label, erklaerung, reading,
                        nur_indikatoren=(key == "indikatoren"))


def alle_schluessel() -> list[str]:
    """Jeder Faktor, für den es eine Aufschlüsselung gibt."""
    return [*KARTE_FAMILIEN, *EIGENE_QUELLE]


def zeitstempel() -> int:
    return int(time.time() * 1000)
