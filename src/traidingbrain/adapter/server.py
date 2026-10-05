"""The local MCP adapter: what Claude may ask this machine to do.

    freqtrade/.venv/Scripts/python -m traidingbrain.adapter.server

Eleven tools. Eight are the ones the installation order names, three are the
ones the research order adds. **None of them can place an order**, and that is
a property of this file rather than a promise: there is no code path from any
tool here to an exchange's trading endpoint. The adapter talks to Freqtrade's
read endpoints and starts Freqtrade and research processes with argument lists
that `validate.py` has already checked against allowlists.

**Where each tool gets its answer, and why the split.** The order says to use
Freqtrade's REST endpoints where they exist and controlled processes for CLI
work. Status, portfolio and journal are REST, because a running bot is the
only thing that knows them. Backtests and research runs are processes, because
they take minutes to hours and there is no endpoint that would wait.

**The annotations are not decoration.** The order requires a data-changing
tool not be labelled read-only. `download_market_data` writes files and makes
network requests; `run_backtest` and `run_horizon_experiment` spawn processes
and write results; `stop_job` kills one. Those four carry
`read_only_hint=False`, and `stop_job` is additionally destructive. The other
seven only read.

**What a caller cannot do through this adapter:** place, modify or cancel an
exchange order; deposit or withdraw; change account permissions; read or write
a path of its own choosing; run a command of its own choosing; start a second
heavy job while one runs; or reach a market outside the configured whitelist.
"""

from __future__ import annotations

import json
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from traidingbrain.adapter import validate
from traidingbrain.adapter.jobs import Registry

ROOT = Path(__file__).resolve().parents[3]
FT_DIR = ROOT / "freqtrade"
USER_DIR = FT_DIR / "user_data"
STRATEGY_DIR = USER_DIR / "strategies"

BASE_CONFIG = USER_DIR / "config.base.json"
FREQAI_CONFIG = USER_DIR / "config.freqai.json"
LOCAL_CONFIG = USER_DIR / "config.local.json"

FT_BINARY = FT_DIR / ".venv" / "Scripts" / "freqtrade.exe"
FT_BINARY_POSIX = FT_DIR / ".venv" / "bin" / "freqtrade"
RESEARCH_PY = ROOT / ".venv" / "Scripts" / "python.exe"
RESEARCH_PY_POSIX = ROOT / ".venv" / "bin" / "python"

REGISTRY = Registry(ROOT / "data" / "jobs.json", log_dir=ROOT / "data" / "joblogs")

#: Loopback only. The order requires the API not be published, and a hostname
#: here rather than a configurable one is part of that.
API_BASE = "http://127.0.0.1:8081/api/v1"
API_TIMEOUT = 8.0

#: Below this a gross result is zero for reporting purposes, and dividing the
#: toll by it would print a meaningless ratio rather than a large one.
NEGLIGIBLE_USDT = 1e-9

#: Threads a research model may use. The order fixes this at two.
MODEL_THREADS = "2"

#: Hours a research round may run before the job is flagged overdue.
RESEARCH_LIMIT_SECONDS = 5 * 3600

server = MCPServer(
    name="traidingbrain-freqtrade",
    version="0.1.0",
    instructions=(
        "Lokaler Adapter fuer den Freqtrade-Ausfuehrungskern und die "
        "Forschungslaeufe des Trading Brain. Kein Werkzeug hier kann eine "
        "Order platzieren, aendern oder stornieren -- es existiert kein "
        "Codepfad dorthin. Schwere Laeufe sind Jobs: starten, Kennung "
        "zurueckbekommen, mit get_job_status nachsehen. Es laeuft genau einer "
        "gleichzeitig."
    ),
)

READS = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
WRITES = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False)
FETCHES = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)
KILLS = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True)


def ft_binary() -> Path:
    for candidate in (FT_BINARY, FT_BINARY_POSIX):
        if candidate.exists():
            return candidate
    raise RuntimeError(f"Freqtrade nicht installiert; erwartet {FT_BINARY}")


def research_python() -> Path:
    for candidate in (RESEARCH_PY, RESEARCH_PY_POSIX):
        if candidate.exists():
            return candidate
    raise RuntimeError(f"Forschungs-venv nicht gefunden; erwartet {RESEARCH_PY}")


def config_chain(*, freqai: bool) -> list[str]:
    chain = [BASE_CONFIG, FREQAI_CONFIG, LOCAL_CONFIG] if freqai else [BASE_CONFIG, LOCAL_CONFIG]
    missing = [p.name for p in chain if not p.is_file()]
    if missing:
        raise RuntimeError(
            f"Konfiguration fehlt: {', '.join(missing)}. "
            f"Fehlt config.local.json, dann: python scripts/freqtrade_setup.py"
        )
    out: list[str] = []
    for path in chain:
        out += ["-c", str(path)]
    return out


def credentials() -> tuple[str, str] | None:
    """Loopback API login, read from the gitignored local config.

    Returns None rather than raising when the file has no username: the API
    server accepts unauthenticated loopback calls in that configuration, and a
    status tool should report what it finds rather than refuse to look.
    """
    if not LOCAL_CONFIG.is_file():
        return None
    try:
        data = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    block = data.get("api_server", {})
    user, password = block.get("username"), block.get("password")
    return (user, password) if user and password else None


def api_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | list[Any]:
    """One GET against the local Freqtrade API.

    `path` is never built from a tool argument -- every call site passes a
    literal. Query parameters are passed through httpx, which encodes them, so
    a value cannot become part of the path.
    """
    try:
        response = httpx.get(
            f"{API_BASE}{path}", params=params, auth=credentials(), timeout=API_TIMEOUT
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return {"fehler": f"API antwortete {exc.response.status_code} auf {path}"}
    except httpx.HTTPError:
        return {
            "fehler": "Freqtrade laeuft nicht oder die API ist nicht erreichbar.",
            "hinweis": "Starten: python scripts/ft.py trade --strategy BaselineTrend",
        }
    payload: dict[str, Any] | list[Any] = response.json()
    return payload


@server.tool(
    description=(
        "Versionen, Modus, Datenalter, laufende Jobs und Erreichbarkeit der "
        "lokalen API. Der erste Aufruf fuer 'laeuft alles'."
    ),
    annotations=READS,
)
def get_system_status() -> dict[str, Any]:
    installed = FT_BINARY.exists() or FT_BINARY_POSIX.exists()
    candles = sorted((USER_DIR / "data" / "binance").glob("*.feather"))
    newest = max((p.stat().st_mtime for p in candles), default=0.0)

    dry_run: Any = "unbekannt"
    if BASE_CONFIG.is_file():
        try:
            dry_run = json.loads(BASE_CONFIG.read_text(encoding="utf-8")).get("dry_run")
        except (OSError, json.JSONDecodeError):
            dry_run = "Konfiguration nicht lesbar"

    return {
        "freqtrade_installiert": installed,
        "freqtrade_pfad": str(FT_BINARY),
        "dry_run_in_konfiguration": dry_run,
        "konfigurationen": {
            p.name: p.is_file() for p in (BASE_CONFIG, FREQAI_CONFIG, LOCAL_CONFIG)
        },
        "kerzendateien": len(candles),
        "neueste_kerzendatei_alter_stunden": (
            round((time.time() - newest) / 3600.0, 1) if newest else None
        ),
        "strategien": sorted(validate.known_strategies(STRATEGY_DIR)),
        "jobs": REGISTRY.summary(),
        "api": api_get("/version"),
        "echte_orders_moeglich": False,
    }


@server.tool(
    description="Verfuegbare Strategien im Strategieverzeichnis.", annotations=READS
)
def list_strategies() -> dict[str, Any]:
    names = sorted(validate.known_strategies(STRATEGY_DIR))
    return {
        "strategien": names,
        "verzeichnis": str(STRATEGY_DIR),
        "hinweis": (
            "BaselineTrend ist der Massstab ohne Modell, nicht ein Kandidat. "
            "FreqaiCostFiltered ist das Modell mit Kostenfilter."
        ),
    }


@server.tool(
    description=(
        "Oeffentliche Marktdaten laden. SCHREIBT Dateien und macht "
        "Netzanfragen. Nur Maerkte aus der Whitelist, nur bekannte Zeitebenen."
    ),
    annotations=FETCHES,
)
def download_market_data(
    pairs: list[str] | None = None,
    timeframes: list[str] | None = None,
    timerange: str | None = None,
) -> dict[str, Any]:
    allowed = validate.whitelist_from_config(BASE_CONFIG, LOCAL_CONFIG)
    wanted_pairs = validate.pairs(pairs, allowed=allowed)
    wanted_tfs = validate.timeframes(timeframes, default=["5m", "1h"])
    window = validate.timerange(timerange)

    command = [
        str(ft_binary()),
        "download-data",
        *config_chain(freqai=False),
        "--userdir",
        str(USER_DIR),
        "--pairs",
        *wanted_pairs,
        "--timeframes",
        *wanted_tfs,
    ]
    if window:
        command += ["--timerange", window]

    job, note = REGISTRY.start(
        kind="download", command=command, cwd=FT_DIR, label=f"{len(wanted_pairs)} Maerkte"
    )
    return {
        "job_id": job.job_id,
        "hinweis": note,
        "maerkte": wanted_pairs,
        "zeitebenen": wanted_tfs,
        "zeitraum": window or "(alles ab Konfiguration)",
    }


@server.tool(
    description=(
        "Einen registrierten Backtest starten. STARTET EINEN PROZESS und "
        "schreibt Ergebnisse. Nur vorhandene Strategien, nur ein Job "
        "gleichzeitig. Gibt eine Job-Kennung zurueck."
    ),
    annotations=WRITES,
)
def run_backtest(
    strategy: str,
    timerange: str | None = None,
    freqai: bool = False,
    freqai_model: str = "LightGBMRegressor",
) -> dict[str, Any]:
    name = validate.strategy(strategy, directory=STRATEGY_DIR)
    window = validate.timerange(timerange)

    command = [
        str(ft_binary()),
        "backtesting",
        *config_chain(freqai=freqai),
        "--userdir",
        str(USER_DIR),
        "--strategy",
        name,
    ]
    if window:
        command += ["--timerange", window]
    if freqai:
        # Allowlisted, not passed through: the model name reaches a process.
        allowed_models = {
            "LightGBMRegressor",
            "LightGBMClassifier",
            "XGBoostRegressor",
            "XGBoostClassifier",
        }
        if freqai_model not in allowed_models:
            raise validate.ArgumentRefusedError(
                f"Modell '{freqai_model}' nicht zugelassen. "
                f"Erlaubt: {', '.join(sorted(allowed_models))}"
            )
        command += ["--freqaimodel", freqai_model]

    job, note = REGISTRY.start(kind="backtest", command=command, cwd=FT_DIR, label=name)
    return {"job_id": job.job_id, "hinweis": note, "strategie": name, "freqai": freqai}


@server.tool(
    description="Fortschritt, Ergebnis oder Fehler eines Jobs.", annotations=READS
)
def get_job_status(job_id: str, lines: int = 40) -> dict[str, Any]:
    checked = validate.job_id(job_id)
    job = REGISTRY.get(checked)
    if job is None:
        return {"fehler": f"Keine Job-Kennung {checked}.", "bekannte": REGISTRY.summary()}
    return {
        "job_id": job.job_id,
        "art": job.kind,
        "zustand": job.state,
        "laufzeit_minuten": round(job.runtime_seconds / 60.0, 1),
        "ueberfaellig": job.overdue,
        "returncode": job.returncode,
        "protokoll_ende": REGISTRY.tail(checked, lines=max(1, min(lines, 400))),
    }


@server.tool(
    description="Einen laufenden Job abbrechen. BEENDET EINEN PROZESS.", annotations=KILLS
)
def stop_job(job_id: str) -> dict[str, Any]:
    checked = validate.job_id(job_id)
    return {"ergebnis": REGISTRY.stop(checked)}


@server.tool(
    description=(
        "Backtest-Ergebnisse lesen: Kennzahlen, Annahmen und -- was dabei am "
        "wichtigsten ist -- Brutto gegen Gebuehren getrennt."
    ),
    annotations=READS,
)
def get_backtest_report(newest: int = 1) -> dict[str, Any]:
    results = sorted(
        (USER_DIR / "backtest_results").glob("backtest-result-*.zip"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not results:
        return {"fehler": "Keine Backtest-Ergebnisse. Erst run_backtest aufrufen."}

    out: list[dict[str, Any]] = []
    for path in results[: max(1, min(newest, 10))]:
        with zipfile.ZipFile(path) as archive:
            names = [
                n
                for n in archive.namelist()
                if n.endswith(".json") and "meta" not in n and "config" not in n
            ]
            if not names:
                continue
            payload = json.loads(archive.read(names[0]))

        for name, block in payload.get("strategy", {}).items():
            trades = block.get("trades", [])
            notional = sum(
                t["open_rate"] * t["amount"] + t["close_rate"] * t["amount"] for t in trades
            )
            # The fee Freqtrade actually applied, taken from the trades rather
            # than assumed: it reads the exchange's worst-case tier at startup.
            fee_rate = trades[0]["fee_open"] if trades else 0.0
            fees = fee_rate * notional
            net = sum(t["profit_abs"] for t in trades)
            out.append(
                {
                    "datei": path.name,
                    "strategie": name,
                    "trades": len(trades),
                    "netto_usdt": round(net, 2),
                    "gebuehren_usdt": round(fees, 2),
                    "brutto_usdt": round(net + fees, 2),
                    "maut_vielfaches_des_bruttos": (
                        round(fees / abs(net + fees), 2)
                        if abs(net + fees) > NEGLIGIBLE_USDT
                        else None
                    ),
                    "umsatz_usdt": round(notional, 2),
                    "gebuehrensatz_je_seite": fee_rate,
                    "endsaldo": block.get("final_balance"),
                    "trefferquote_prozent": round(
                        100.0 * sum(1 for t in trades if t["profit_abs"] > 0) / max(1, len(trades)),
                        1,
                    ),
                }
            )
    return {"berichte": out}


@server.tool(
    description="Paper-Saldo, offene Positionen und Gewinn/Verlust des laufenden Bots.",
    annotations=READS,
)
def get_paper_portfolio() -> dict[str, Any]:
    return {
        "konfiguration": api_get("/show_config"),
        "saldo": api_get("/balance"),
        "offen": api_get("/status"),
        "anzahl": api_get("/count"),
        "gewinn": api_get("/profit"),
    }


@server.tool(
    description="Protokollierte Trades und ihre Ein-/Ausstiegsgruende.", annotations=READS
)
def get_trade_journal(limit: int = 50) -> dict[str, Any]:
    capped = max(1, min(limit, 500))
    return {
        "trades": api_get("/trades", {"limit": capped}),
        "einstiegsgruende": api_get("/entries"),
        "ausstiegsgruende": api_get("/exits"),
    }


@server.tool(
    description=(
        "Abdeckungsregister: je Quelle und Markt erste/letzte Beobachtung, "
        "Frequenz, Zeilen, Luecken, Duplikate. Zaehlt die Dateien wirklich."
    ),
    annotations=READS,
)
def get_data_coverage(sources: list[str] | None = None) -> dict[str, Any]:
    command = [str(research_python()), str(ROOT / "scripts" / "coverage.py"), "--json"]
    if sources:
        known = {"ohlcv", "funding", "openinterest", "accountratio", "sentiment", "flow"}
        for source in sources:
            if source not in known:
                raise validate.ArgumentRefusedError(
                    f"Quelle '{source}' unbekannt. Erlaubt: {', '.join(sorted(known))}"
                )
        command += ["--sources", *sources]

    job, note = REGISTRY.start(
        kind="coverage", command=command, cwd=ROOT, label="Abdeckung", limit_seconds=900
    )
    return {"job_id": job.job_id, "hinweis": note}


@server.tool(
    description=(
        "Einen angemeldeten Horizont-Versuch starten. STARTET EINEN PROZESS. "
        "Nur die festgelegten Horizonte (24/72/168h), Merkmalsgruppen "
        "(P, P+D, P+D+M, P+D+M+O) und Modelle (logistic, lightgbm)."
    ),
    annotations=WRITES,
)
def run_horizon_experiment(
    horizon_hours: int,
    feature_group: str,
    model: str = "lightgbm",
    pairs: list[str] | None = None,
) -> dict[str, Any]:
    hours = validate.horizon(horizon_hours)
    group = validate.feature_group(feature_group)
    which = validate.model(model)
    allowed = validate.whitelist_from_config(BASE_CONFIG, LOCAL_CONFIG)
    markets = validate.pairs(pairs, allowed=allowed)

    command = [
        str(research_python()),
        str(ROOT / "scripts" / "study_panel.py"),
        "--horizon",
        str(hours),
        "--features",
        group,
        "--model",
        which,
        "--pairs",
        *markets,
    ]
    job, note = REGISTRY.start(
        kind="horizon",
        command=command,
        cwd=ROOT,
        label=f"{hours}h {group} {which}",
        limit_seconds=RESEARCH_LIMIT_SECONDS,
        # The order caps a model at two threads. Set for every library that
        # reads one of these, because one of them always ignores the others.
        env={
            "OMP_NUM_THREADS": MODEL_THREADS,
            "OPENBLAS_NUM_THREADS": MODEL_THREADS,
            "MKL_NUM_THREADS": MODEL_THREADS,
            "NUMEXPR_NUM_THREADS": MODEL_THREADS,
        },
    )
    return {"job_id": job.job_id, "hinweis": note, "horizont": hours, "merkmale": group}


@server.tool(
    description="Registrierte Versuchsergebnisse lesen, inklusive der erfolglosen.",
    annotations=READS,
)
def get_experiment_report() -> dict[str, Any]:
    command = [str(research_python()), str(ROOT / "scripts" / "ratchet.py")]
    job, note = REGISTRY.start(
        kind="register", command=command, cwd=ROOT, label="Register", limit_seconds=600
    )
    return {
        "job_id": job.job_id,
        "hinweis": note,
        "lesehinweis": (
            "Die erfolglosen Zeilen sind die wertvollen: ohne sie waere der "
            "beste von n Versuchen per Konstruktion gut."
        ),
    }


def main() -> int:
    try:
        server.run(transport="stdio")
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
