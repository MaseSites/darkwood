"""E24 -- Der Takt der Balken: Volumen- und Dollar-Balken statt Zeitbalken.

    python scripts/study_e24_takt.py --bauen                 # Balken erzeugen (Cache)
    python scripts/study_e24_takt.py --strang 0/3            # ein Drittel der Laeufe
    python scripts/study_e24_takt.py --auswerten             # Tore pruefen, Bericht
    python scripts/study_e24_takt.py --symbols BTCUSDT --arme volumen --max-bars 3000  # Rauchtest

===========================================================================
VORREGISTRIERT in audit/EXPERIMENTS_NEXT.yaml als E24 am 21.10.2026, BEVOR
eine Zahl existierte. Gebaut auf Anweisung des Eigentuemers am selben Tag,
mit der dort notierten Erwartung des Pruefers: "unentschieden innerhalb
+-0.077 R". Dieser Arm ist eine Falsifikation, keine Rettung.
===========================================================================

**Was gleich bleibt.** Dieselben Setups (A, B, E, F, G), dieselben Detektoren
und Konstanten, dieselbe Risikoschicht, dieselbe Fuellregel auf Minuten,
derselbe Kostendeckel 0.08. Der Motor ist `BacktestEngine`, unveraendert bis
auf eine Sache: wo er bisher `ts + timeframe_ms` als Schlusszeit rechnete,
liest er jetzt die Spalte `close_ts`, wenn sie da ist (`data/takt.py`). Ohne
die Spalte ist jeder Lauf byte-gleich, das friert `tests/test_backtest.py` ein.

**Was wechselt.** Der Balkenbegriff. `data/takt.py` buendelt Minuten, bis
eine Volumen- (Arm E24.1) oder Umsatzschwelle (E24.2, `close * volume`)
gerissen ist. Die Schwelle je Markt ist der Mittelwert der M15-Groesse ueber
die ganze Historie, die Hierarchie M15:H1:H4:D1:W1 = 1:4:16:96:672.

**Die drei Tore, vorab (Register):**
  (a) netto R je Trade > 0 mit korrigiertem Intervall (79 Vergleiche,
      zweiwegig Markt x Woche geclustert wie E17) ohne Null;
  (b) Trefferquote > 50 % auf mindestens 2'000 Trades je Arm -- sonst ist
      "praktisch nur noch gewinnen" widerlegt, wie auch immer (a) ausgeht;
  (c) Replikation auf den 56 E17-Maerkten mit Verhaeltnis >= 0.5x.
  Alle drei noetig. (c) wird erst gerechnet, wenn (a) und (b) auf den zwoelf
  Maerkten halten -- Rechenzeit fuer 56 Maerkte ist sonst verschwendet.

**Was dieses Skript NICHT tut.** Es waehlt keine Schwelle nach dem Ergebnis,
es vergleicht keine Zellen jenseits der zwei angemeldeten Arme, und es
schreibt in `data/replay_fills/` nichts -- die 7'335 Zeitbalken-Fills bleiben
die Basis, gegen die berichtet wird.

**Die Ausgabe.** Je Arm und Markt eine JSON-Datei im Format von
`replay_all_markets.py` (jeder Fill, jedes Journal) unter
`data/replay_fills_e24/<arm>/<SYMBOL>.json`. `--auswerten` schreibt
`audit/E24_ERGEBNIS.json` und `audit/E24_ERGEBNIS.md`.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import NormalDist

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import replay_all_markets as ram
from study_e17_zeitebene import schwanz, zweiweg

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.config.settings import load_config
from traidingbrain.data import takt as takt_mod
from traidingbrain.data.dataversion import content_version
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Timeframe
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.execution.policy import policy_for
from traidingbrain.execution.venuebinding import Environment, VenueBinding
from traidingbrain.journal.build import entries_from
from traidingbrain.journal.identity import identity_for
from traidingbrain.journal.provenance import ProvenanceLedger
from traidingbrain.journal.record import Source
from traidingbrain.journal.version import (
    code_version,
    decision_version,
    run_signature,
)
from traidingbrain.sim.engine import BacktestEngine
from traidingbrain.strategies.guide import GuidePool

TAKT_ROOT = ROOT / "data" / "takt"
OUT = ROOT / "data" / "replay_fills_e24"
BASIS = ROOT / "data" / "replay_fills"
BERICHT_JSON = ROOT / "audit" / "E24_ERGEBNIS.json"
BERICHT_MD = ROOT / "audit" / "E24_ERGEBNIS.md"
REGISTER = ROOT / "audit" / "EXPERIMENTS_NEXT.yaml"
ARME = ("volumen", "dollar")
TAG_MS = 86_400_000
MIN_TRADES_TOR_B = 2_000
#: Tor (b): "praktisch nur gewinnen" ist bei dieser Quote schon widerlegt.
TREFFER_TOR_B = 0.5


# --------------------------------------------------------------------------- #
# Balken
# --------------------------------------------------------------------------- #

def takt_ordner(arm: str, symbol: str) -> Path:
    return TAKT_ROOT / arm / symbol


def baue_balken(symbol: str, arm: str, *, store: ParquetStore, force: bool = False) -> dict:
    """Takt-Balken fuer einen Markt erzeugen und zwischenspeichern."""
    ordner = takt_ordner(arm, symbol)
    meta = ordner / "schwelle.json"
    if meta.exists() and not force:
        return json.loads(meta.read_text(encoding="utf-8"))
    takt = takt_mod.ARME[arm]
    m1 = store.read(symbol, Timeframe.M1)
    m15 = store.read(symbol, Timeframe.M15)
    if m1.empty or m15.empty:
        return {}
    schwelle = takt.basis_schwelle(m15)
    started = time.perf_counter()
    frames = takt_mod.takt_hierarchie(m1, takt, schwelle)
    takt_mod.schreibe(frames, ordner)
    info = {
        "symbol": symbol,
        "arm": arm,
        "basis_schwelle": schwelle,
        "m1_minuten": len(m1),
        "m15_kerzen": len(m15),
        "balken": {tf.value: len(f) for tf, f in frames.items()},
        "mittlere_dauer_min": {
            tf.value: (float(f["minutes"].mean()) if len(f) else None) for tf, f in frames.items()
        },
        "sekunden": round(time.perf_counter() - started, 1),
    }
    meta.write_text(json.dumps(info, indent=1), encoding="utf-8")
    return info


# --------------------------------------------------------------------------- #
# Lauf
# --------------------------------------------------------------------------- #

def run_one(symbol: str, arm: str, *, config, store: ParquetStore,
            funding_store: FundingStore, max_bars: int | None) -> dict | None:
    started = time.perf_counter()
    info = baue_balken(symbol, arm, store=store)
    if not info:
        return None
    frames = takt_mod.lese(takt_ordner(arm, symbol), list(config.engine.timeframes.context))
    minutes = store.read(symbol, config.engine.timeframes.execution)
    if any(f.empty for f in frames.values()) or minutes.empty:
        return None

    analysis = MultiFrameAnalysis(frames, config.engine)
    funding = funding_store.read(symbol)
    analysed = time.perf_counter() - started
    engine = BacktestEngine(
        symbol, analysis, minute_frame=minutes,
        spec=SymbolSpec(symbol=symbol, **DEFAULT_SPEC),
        config=config, funding=funding, history=None,
    )
    pool = GuidePool.for_config(config)
    result = engine.run(pool, max_bars=max_bars)
    journal = entries_from(
        analysis, result.fills, symbol=symbol, strategy=pool.name,
        source=Source.REPLAY, signal=config.engine.timeframes.signal,
    )
    stamp, commit = decision_version(), code_version()
    # Die Signatur traegt den Takt. Ohne den Zusatz waeren diese Fills von
    # den 7'335 Zeitbalken-Fills nicht zu unterscheiden.
    signature = f"{run_signature(config, max_bars=max_bars)}|takt={arm}"
    identity = identity_for(
        config,
        VenueBinding.legacy_incoherent(
            data_venue=config.engine.exchange.name,
            price_venue=config.engine.exchange.name,
            price_environment=Environment.MAINNET,
            instrument_spec_venue=ram.SPEC_VENUE,
            policy=policy_for(ram.SPEC_VENUE, ram.LEGACY_POLICY),
            reason=ram.INCOHERENCE_REASON,
        ),
        pool,
        data_version=content_version({**frames, "m1": minutes}),
        funding_source=str(funding_store.root),
        analysis_venue=ram.ANALYSIS_VENUE,
        max_bars=max_bars,
    )
    journal = [
        replace(e, run_signature=signature, decision_version=stamp, code_version=commit)
        for e in journal
    ]
    ledger = ProvenanceLedger()
    schluessel: dict[int, str] = {}
    for f in result.fills:
        key = ledger.register(ram.decision_of(f, symbol=symbol, identity_stamp=identity.stamp()))
        schluessel[id(f)] = key
        ledger.record(ram.provenance_of(f, key, identity=identity))

    return {
        "symbol": symbol,
        "arm": arm,
        "experiment": "E24",
        "takt": info,
        "strategy": pool.name,
        "setups": [s.key for s in pool.setups],
        "decision_version": stamp,
        "code_version": commit,
        "run_signature": signature,
        "identity_stamp": identity.stamp(),
        "signal_timeframe": config.engine.timeframes.signal.value,
        "execution_timeframe": config.engine.timeframes.execution.value,
        "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "analysis_seconds": round(analysed, 1),
        "seconds": round(time.perf_counter() - started, 1),
        "snapshots_built": result.snapshots_built,
        "intents": result.intents,
        "intents_rejected_by_risk": result.intents_rejected_by_risk,
        "first_ts": result.first_ts,
        "last_ts": result.last_ts,
        "window_note": result.window_note,
        "max_bars": max_bars,
        "summary": result.summary(),
        "fills": [{**ram.fill_record(f), "decision_id": schluessel[id(f)]} for f in result.fills],
        "journal": [json.loads(e.to_json()) for e in journal],
        "fills_count": len(result.fills),
        "journal_count": len(journal),
        "enrichment_gap": len(result.fills) - len(journal),
    }


# --------------------------------------------------------------------------- #
# Auswertung
# --------------------------------------------------------------------------- #

def _z_krit() -> tuple[int, float]:
    n = int(re.search(r"total_comparisons:\s*(\d+)", REGISTER.read_text(encoding="utf-8")).group(1))
    return n, float(NormalDist().inv_cdf(1 - 0.05 / (2 * n)))


def lade(ordner: Path) -> list[dict]:
    zeilen: list[dict] = []
    for pfad in sorted(ordner.glob("*.json")):
        blob = json.loads(pfad.read_text(encoding="utf-8"))
        for row in blob["fills"]:
            zeilen.append({
                "symbol": blob["symbol"], "ts": int(row["opened_ts"]),
                "r": float(row["r_multiple"]), "setup": str(row.get("setup") or ""),
                "timeframe": str(row.get("timeframe") or ""),
            })
    zeilen.sort(key=lambda z: z["ts"])
    return zeilen


def bewerte(zeilen: list[dict], z: float) -> dict:
    if not zeilen:
        return {"n": 0}
    r = np.array([x["r"] for x in zeilen])
    markt = np.array([x["symbol"] for x in zeilen])
    ts = np.array([x["ts"] for x in zeilen])
    woche = ((ts - ts.min()) // (7 * TAG_MS)).astype(int)
    m, lo, hi = zweiweg(r, markt, woche, z)
    treffer = float((r > 0).mean())
    gewinner = r[r > 0]
    verlierer = r[r <= 0]
    return {
        "n": int(r.size), "mittel": m, "lo": lo, "hi": hi,
        "trefferquote": treffer,
        "mittlerer_gewinner": float(gewinner.mean()) if gewinner.size else None,
        "mittlerer_verlierer": float(verlierer.mean()) if verlierer.size else None,
        "maerkte": len(set(markt.tolist())),
        "je_setup": {
            s: {"n": int((np.array([x["setup"][:1] for x in zeilen]) == s).sum()),
                "mittel": float(r[np.array([x["setup"][:1] for x in zeilen]) == s].mean())}
            for s in sorted({x["setup"][:1] for x in zeilen})
        },
        "schwanz": schwanz(zeilen),
    }


def auswerten() -> int:
    n_vergleiche, z = _z_krit()
    basis = bewerte(lade(BASIS), z)
    arme = {}
    for arm in ARME:
        ordner = OUT / arm
        b = bewerte(lade(ordner), z) if ordner.exists() else {"n": 0}
        if b["n"]:
            tor_a = bool(b["mittel"] > 0 and not math.isnan(b["lo"]) and b["lo"] > 0)
            tor_b = bool(b["n"] >= MIN_TRADES_TOR_B and b["trefferquote"] > TREFFER_TOR_B)
            b.update({"tor_a": tor_a, "tor_b": tor_b, "tor_c": "ausstehend (erst nach a und b)",
                      "urteil": "TORE A UND B GEHALTEN -- (c) auf 56 Maerkten rechnen"
                      if (tor_a and tor_b) else "GEFALLEN"})
        arme[arm] = b
    ergebnis = {
        "experiment": "E24", "stand": datetime.now(UTC).isoformat(timespec="seconds"),
        "vergleiche": n_vergleiche, "z": z, "min_trades_tor_b": MIN_TRADES_TOR_B,
        "basis_zeitbalken": basis, "arme": arme,
    }
    BERICHT_JSON.write_text(json.dumps(ergebnis, indent=1), encoding="utf-8")
    BERICHT_MD.write_text(bericht_md(ergebnis), encoding="utf-8")
    print(bericht_md(ergebnis))
    return 0


def _f(x, d=4) -> str:
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:+.{d}f}"


def bericht_md(e: dict) -> str:
    z = [
        "# E24 — Der Takt der Balken",
        "",
        f"Stand {e['stand']}. Nachrechnen: `python scripts/study_e24_takt.py --auswerten`.",
        f"Korrigiertes Niveau: {e['vergleiche']} Vergleiche, z = {e['z']:.3f}; Intervall zweiwegig "
        "Markt x Woche geclustert (wie E17).",
        "",
        "| Arm | Trades | Märkte | Treffer | Mittel R | Intervall | Tor (a) | Tor (b) | Urteil |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    b = e["basis_zeitbalken"]
    z.append(f"| Basis Zeitbalken (M15) | {b['n']:,} | {b.get('maerkte','')} | "
             f"{b.get('trefferquote',0):.1%} | {_f(b.get('mittel'))} | "
             f"[{_f(b.get('lo'))}, {_f(b.get('hi'))}] | — | — | Referenz |")
    for arm, a in e["arme"].items():
        if not a["n"]:
            z.append(f"| E24 {arm} | 0 | | | | | | | noch nicht gelaufen |")
            continue
        z.append(f"| E24 {arm} | {a['n']:,} | {a['maerkte']} | {a['trefferquote']:.1%} | "
                 f"{_f(a['mittel'])} | [{_f(a['lo'])}, {_f(a['hi'])}] | "
                 f"{'ja' if a['tor_a'] else 'NEIN'} | {'ja' if a['tor_b'] else 'NEIN'} | "
                 f"{a['urteil']} |")
    z += ["", "## Je Setup", ""]
    for arm, a in e["arme"].items():
        if a["n"]:
            z.append(f"**{arm}:** " + ", ".join(
                f"{s} n={v['n']} {_f(v['mittel'])}" for s, v in a["je_setup"].items()))
    z += ["", "## Schwanz (vorab erklärt)", ""]
    for name, a in [("Basis", b), *e["arme"].items()]:
        s = a.get("schwanz") or {}
        if s:
            z.append(f"- **{name}:** schlechtester Wochenblock {s['schlechtester_block']:+.3f} R, "
                     f"schlechtester Markt {s['schlechtester_markt']} "
                     f"{s['schlechtester_markt_r']:+.3f} R, "
                     f"grösster Rückgang {s['groesster_rueckgang_R']:.1f} R, "
                     f"{s['anteil_maerkte_negativ']:.0%} der Märkte negativ")
    z += ["", "Tor (c), die Replikation auf 56 ungesehenen Märkten, wird nur gerechnet, "
               "wenn (a) und (b) halten.", ""]
    return "\n".join(z)


# --------------------------------------------------------------------------- #

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbols", default=",".join(ram.MARKETS))
    p.add_argument("--arme", default=",".join(ARME))
    p.add_argument("--strang", default=None, help="i/n: nur jeden n-ten Lauf ab i")
    p.add_argument("--max-bars", type=int, default=None, help="nur Rauchtest, kein Messlauf")
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--force", action="store_true")
    p.add_argument("--bauen", action="store_true", help="nur Balken erzeugen")
    p.add_argument("--auswerten", action="store_true")
    args = p.parse_args()
    if args.auswerten:
        return auswerten()

    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)
    funding_store = FundingStore(config.engine.paths.funding_dir)
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    arme = [a.strip() for a in args.arme.split(",") if a.strip()]
    laeufe = [(arm, sym) for arm in arme for sym in symbols]
    if args.strang:
        i, n = (int(x) for x in args.strang.split("/"))
        laeufe = laeufe[i::n]

    print(f"E24 Takt -- {len(laeufe)} Laeufe, Stempel {decision_version()}, "
          f"{'RAUCHTEST max_bars=' + str(args.max_bars) if args.max_bars else 'Messlauf'}",
          flush=True)
    for k, (arm, sym) in enumerate(laeufe, 1):
        if args.bauen:
            info = baue_balken(sym, arm, store=store, force=args.force)
            print(f"  [{k:>2}/{len(laeufe)}] {arm:8s} {sym:9s} Balken {info.get('balken')} "
                  f"Dauer/M15-Balken {info.get('mittlere_dauer_min',{}).get('M15')}", flush=True)
            continue
        ziel = args.out / arm / f"{sym}.json"
        ziel.parent.mkdir(parents=True, exist_ok=True)
        if ziel.exists() and not args.force and not args.max_bars:
            print(f"  [{k:>2}/{len(laeufe)}] {arm:8s} {sym:9s} liegt vor", flush=True)
            continue
        print(f"  [{k:>2}/{len(laeufe)}] {arm:8s} {sym:9s} laeuft ... ", end="", flush=True)
        try:
            res = run_one(sym, arm, config=config, store=store,
                          funding_store=funding_store, max_bars=args.max_bars)
        except Exception as exc:
            print(f"FEHLER {type(exc).__name__}: {exc}", flush=True)
            continue
        if res is None:
            print("keine Daten", flush=True)
            continue
        if args.max_bars:
            ziel = args.out / "rauchtest" / arm / f"{sym}.json"
            ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(json.dumps(res, indent=1), encoding="utf-8")
        print(f"{res['fills_count']:,} Trades in {res['seconds']:.0f}s "
              f"(Balken M15 {res['takt']['balken']['M15']:,})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
