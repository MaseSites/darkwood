# Phase 0 — `mypy --strict src`: 3 von 20 behoben, 17 dokumentiert

Master-Direktive 03, Phase 0, mit ihrer eigenen Ausnahmeklausel: *„Falls ein
mypy-Fehler nur durch eine fachliche Verhaltensentscheidung lösbar wäre,
diesen Fehler nicht verdecken. Dokumentieren und Phase fortsetzen."*

Diese Klausel greift bei 17 der 20 Fehler, aus **drei verschiedenen Gründen**.

---

## Behoben: 3 Fehler, beide Dateien ausserhalb der Entscheidungs-Hülle

| Datei | Zeile | Fehler | Änderung |
|---|---|---|---|
| `journal/replayset.py` | 66 | `type-arg` | `list[dict]` → `list[dict[str, Any]]` |
| `journal/replayset.py` | 110 | `type-arg` | dieselbe Parametrisierung |
| `learn/goalsim.py` | 159 | `no-any-return` | Indexergebnis benannt statt direkt zurückgegeben |

Beide Module sind **nicht** in der 59-Modul-Hülle von `decision_version`.
Geprüft, nicht angenommen. `Any` ist bei `replayset` die wahre Aussage: die
`journal`-Zeilen sind beliebiges JSON.

---

## Nicht behoben, Grund 1: die Korrektur würde den Entscheidungsstempel bewegen

| Datei | Zeile | Fehler |
|---|---|---|
| `journal/version.py` | 259 | `"AST" has no attribute "body"` |
| `live/paperstate.py` | 448 | `arg-type` (2×, `**dict[str, str \| int]` → `Tally`) |

**Beide Module liegen in der Entscheidungs-Hülle.** Ich hatte sie zuerst
behoben — `setattr(node, "body", …)` statt `node.body = …`, und
`restored: dict[str, Any]` statt der Vereinigung. Beide Änderungen sind zur
Laufzeit identisch. Gemessen:

| | |
|---|---|
| `decision_version` vorher (= Banner des laufenden Händlers) | `d8c7f12104e4` |
| nach beiden Korrekturen | `dc971bb66fa5` |
| nach Rücknahme von `version.py` allein | `6635bbf78cc7` |
| nach Rücknahme beider | **`d8c7f12104e4`** |

Die Zwischenstufe ist der Beleg, dass **beide** Dateien in der Hülle liegen —
`journal.version` sogar in seiner **eigenen**.

**Warum das eine fachliche Entscheidung ist und keine Typisierung.** Der
Stempel ist ein AST-normalisierter Hash der Hülle; er lässt Prosa fallen,
nicht Code. `setattr(x, "body", v)` und `x.body = v` sind verschiedener Code,
also bewegt sich der Hash zu Recht — er kann „semantisch gleicher Umbau" nicht
von „Verhalten geändert" unterscheiden, und das ist konservativ und richtig.

Die Folge wäre aber, dass die laufende Vorwärtsstichprobe
(`audit/FORWARD_SAMPLE_ISOLATION.md`) unter `d8c7f12104e4` weiterschreibt,
während jeder künftige Lauf `dc971bb66fa5` trüge — eine gespaltene Epoche
**ohne Verhaltensunterschied**. Das ist genau die Art stiller
Identitätsänderung, gegen die `journal/era.py` gebaut wurde.

Darum zurückgenommen und hier benannt, statt den Fehler zu verdecken.

**Der eigentliche Befund dahinter:** Stufe 0 (`mypy --strict` sauber) und die
Stabilität des Entscheidungsstempels stehen für **jedes Hüllenmodul** im
Widerspruch. Jede Typkorrektur in einem der 59 Module spaltet die Epoche. Das
ist kein Fehler in einer der beiden Regeln — es ist eine ungelöste Spannung,
und sie gehört entschieden, nicht umgangen. Denkbare Auflösungen, keine davon
hier getroffen:

1. Den Stempel nur über die **Hülle ohne `journal.version`** bilden — die
   stempelnde Datei aus ihrer eigenen Messung nehmen.
2. Eine ausdrückliche Liste „semantisch neutraler Umbauten" führen, gegen die
   der Stempel absichtlich blind ist. Gefährlich: wer die Liste pflegt,
   entscheidet, was als „neutral" gilt.
3. Die Spannung akzeptieren und solche Korrekturen nur bei einem geplanten
   Epochenwechsel vornehmen — also wenn die Vorwärtsstichprobe ohnehin neu
   beginnt.

Meine Empfehlung ist 3, mit 1 als späterer Verbesserung. Beides braucht eine
Freigabe.

---

## Nicht behoben, Grund 2: ein Modul, das nicht importierbar ist

| Datei | Fehler |
|---|---|
| `adapter/server.py` | 2× `import-not-found` + 12× `untyped-decorator` |

```python
from mcp.server.mcpserver import MCPServer   # Zeile 41
from mcp.types import ToolAnnotations        # Zeile 42
```

Gemessen:

| | |
|---|---|
| `import mcp` | `ModuleNotFoundError: No module named 'mcp'` |
| `mcp` in `pyproject.toml` | **nein** |
| Wer importiert `adapter.server`? | **niemand** — nicht `src`, nicht `scripts`, nicht `tests` |

Die beiden Adapter-Tests (`test_adapter_jobs.py`, `test_adapter_validate.py`)
importieren `adapter.jobs` und `adapter.validate`, nicht `server`.

**Das ist unerreichbarer Code mit einer undeklarierten, nicht installierten
Abhängigkeit.** 14 der 20 Fehler kommen aus einem Modul, das in dieser
Umgebung nicht laufen kann. Die 12 `untyped-decorator`-Fehler sind eine
*Folge* der beiden Importfehler: ohne Typen ist `MCPServer` `Any`, und ein
`Any`-Dekorator gilt unter `--strict` als untypisiert.

Die richtige Behebung ist eine **Produktentscheidung**, nicht eine
Typannotation:

- `mcp` als Abhängigkeit deklarieren und den Adapter behalten, oder
- den Adapter entfernen.

`mcp.*` in die bestehenden `ignore_missing_imports`-Überschreibungen
aufzunehmen (neben `ccxt.*`, `duckdb.*`, `structlog.*`, `pyarrow.*`) würde
14 auf 12 senken und die Frage nicht beantworten. Ein `exclude` für die Datei
wäre Verdecken. Beides nicht getan.

---

## Prüfstand nach Phase 0

| | |
|---|---|
| `mypy --strict src` | **17 Fehler in 3 Dateien** (vorher 20 in 5) |
| davon unerreichbares Modul | 14 |
| davon Hüllenmodule | 3 |
| `ruff check src tests scripts` | **sauber** |
| `decision_version` | **`d8c7f12104e4`** — unverändert, identisch zum Banner der laufenden Stichprobe |
| `run_signature` | unverändert |

## Etiketten

| Aussage | |
|---|---|
| Die 3 behobenen Module liegen aussserhalb der Hülle | **BELEGT** (`decision_closure()` abgefragt) |
| `version.py` und `paperstate.py` liegen in der Hülle | **BELEGT** (Stempel bewegt sich, Zwischenstufe isoliert den Beitrag) |
| Die Korrekturen sind zur Laufzeit identisch | **MODELLIERT** — `setattr` gegen Attributzuweisung und eine reine Annotation sind semantisch gleich, aber nicht durch einen Test bewiesen |
| `mcp` ist nicht installiert und nicht deklariert | **BELEGT** |
| `adapter/server.py` ist unerreichbar | **BELEGT** (projektweite Suche nach Importen) |
| Stufe 0 ist nach dieser Phase geschlossen | **NEIN** — und der Grund ist benannt, nicht umgangen |

---

## Nachtrag: die Spannung löst sich an der Art der Änderung

Nach Phase 0 gemessen, welche Module der Direktive in der Hülle liegen:

| Modul | Hülle | betrifft |
|---|---|---|
| `analysis.context` | **IN** | Phase 1 |
| `data.derivatives` | **IN** | Phase 1 |
| `data.venue` | **IN** | Phase 1, 2 |
| `risk.limits` | **IN** | Phase 5 |
| `data.funding` | ausserhalb | — |
| `execution.order` | ausserhalb | Phase 2 |
| `api.app` | ausserhalb | Phase 5 |
| `proposals.builder` | ausserhalb | Phase 5 |

Damit ist die Regel klar und braucht keine Ausnahmeliste:

- Eine **reine Typkorrektur** in einem Hüllenmodul darf den Stempel nicht
  bewegen — sie spaltet die Epoche ohne Verhaltensunterschied. Zurücknehmen
  und dokumentieren (Phase 0).
- Eine **echte Verhaltensänderung** in einem Hüllenmodul *soll* den Stempel
  bewegen. Genau dafür ist er gebaut. Fortfahren und den neuen Stempel
  protokollieren (Phase 1 und folgende).

Der laufende Prozess ist in beiden Fällen unberührt: er hält seinen Code im
Speicher, und er wird nicht neu gestartet.
