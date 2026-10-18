"""Der Derivatespeicher darf zwei Börsen nicht in eine Datei mischen.

**Der Anlass, aus `audit/CHATGPT_BRIEFING_02.md` Abschnitt 5.1.**
`LivePositioning.refresh` schreibt frisch geholte Zeilen über `store.write` in
dieselbe Datei wie die Backfill-Historie. Die Live-Quelle kommt aus
`run_live.py:171` über `config.engine.exchange.name` — also **Binance**. Die
Historie kommt aus `backfill_derivatives.py:74-81` über hartkodiertes
`ccxt.bybit` — also **Bybit**. `_tidy` dedupliziert mit
`drop_duplicates(subset="ts", keep="last")`, also gewinnt bei überlappenden
Zeitstempeln die später geschriebene Zeile.

Die Schemata trugen **keine Venue-Spalte**. Nach dem Schreiben wäre nicht mehr
feststellbar, welche Zeile von welcher Börse kam.

**Die Grössenordnung ist gemessen, nicht geschätzt.** `learn/panel.py:138-141`
hält fest: Bybit liefert 16419.749 für BTCUSDT am 2021-10-01 00:00, das
Binance-Archiv 47921.245 für dieselbe Stunde — Faktor ~2.9. Und
`analysis/positioning.py:48` setzt `MIN_OI_CHANGE = 0.004`, also 0.4 %. Die
Naht wäre eine gigantische Open-Interest-Bewegung, die rein aus dem
Börsenwechsel entsteht — ein Signal aus einem Datenfehler.

**Gemessen ist es nicht passiert:** alle vier Dateien enden 2026-09-29, null
Sprünge über 50 %, und BTCUSDT 2021-10-01 00:00 steht bei 16419.749 — der
Bybit-Wert auf die letzte Dezimalstelle. Die Gefahr ist latent. Diese Tests
halten sie latent.
"""

from __future__ import annotations

import shutil

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from traidingbrain.data.derivatives import (
    SCHEMA_VERSION,
    DerivativesStore,
    ForeignVenueError,
)

OI = "open_interest"
RATIO = "account_ratio"


def _oi(ts: int, wert: float) -> pd.DataFrame:
    return pd.DataFrame({"ts": [ts], "open_interest": [wert]})


# --------------------------------------------------------------------------- #
# Die Venue ist Pflicht
# --------------------------------------------------------------------------- #


def test_ein_speicher_ohne_venue_ist_nicht_konstruierbar(tmp_path) -> None:
    """Kein Vorgabewert.

    `DerivativesStore(root)` war die alte Signatur, und `DerivativesSource`
    hatte daneben `venue_name: str = "bybit"` (derivatives.py:112). Genau
    dieses Paar hat die Mischung möglich gemacht.
    """
    with pytest.raises(TypeError):
        DerivativesStore(tmp_path)  # type: ignore[call-arg]


def test_eine_unbekannte_venue_wird_abgelehnt(tmp_path) -> None:
    with pytest.raises(ValueError, match="kraken"):
        DerivativesStore(tmp_path, venue="kraken")


# --------------------------------------------------------------------------- #
# Partitionen: physisch getrennt, nicht nur beschriftet
# --------------------------------------------------------------------------- #


def test_zwei_venues_schreiben_in_verschiedene_dateien(tmp_path) -> None:
    """Eine Venue-Spalte allein genügt nicht, wenn beide in dieselbe Datei gehen."""
    bybit = DerivativesStore(tmp_path, venue="bybit")
    binance = DerivativesStore(tmp_path, venue="binance")

    bybit.write("BTCUSDT", OI, _oi(1_000, 16_419.749))
    binance.write("BTCUSDT", OI, _oi(1_000, 47_921.245))

    assert bybit.path("BTCUSDT", OI) != binance.path("BTCUSDT", OI)
    assert "bybit" in str(bybit.path("BTCUSDT", OI))
    assert "binance" in str(binance.path("BTCUSDT", OI))

    # Und jede Datei trägt nur ihren eigenen Wert.
    assert bybit.read("BTCUSDT", OI)["open_interest"].tolist() == [16_419.749]
    assert binance.read("BTCUSDT", OI)["open_interest"].tolist() == [47_921.245]


def test_jede_zeile_traegt_ihre_venue_im_schema(tmp_path) -> None:
    """Eine Datei muss sich selbst erklären, auch ohne ihren Pfad.

    Die alten Schemata hatten nur `ts` und den Wert. Eine Datei, die aus ihrem
    Verzeichnis gelöst wird, war damit herkunftslos.
    """
    store = DerivativesStore(tmp_path, venue="bybit")
    store.write("BTCUSDT", OI, _oi(1_000, 16_419.749))

    tabelle = pq.read_table(store.path("BTCUSDT", OI))
    assert "venue" in tabelle.schema.names
    assert tabelle.column("venue").to_pylist() == ["bybit"]
    assert tabelle.schema.metadata is not None
    assert tabelle.schema.metadata[b"schema_version"] == str(SCHEMA_VERSION).encode()


# --------------------------------------------------------------------------- #
# Der Kern: ein fremder Schreibversuch bricht ab
# --------------------------------------------------------------------------- #


def test_eine_fremde_zeile_im_rahmen_bricht_ab(tmp_path) -> None:
    """Der Rahmen bringt eine Venue mit, die nicht die des Speichers ist."""
    store = DerivativesStore(tmp_path, venue="bybit")
    fremd = _oi(1_000, 47_921.245)
    fremd["venue"] = "binance"
    with pytest.raises(ForeignVenueError, match="binance"):
        store.write("BTCUSDT", OI, fremd)


def test_eine_bestehende_fremde_datei_blockt_das_schreiben(tmp_path) -> None:
    """Der Fall, der die Historie verdorben hätte.

    Die Partition trennt die Dateien schon — dieser Test prüft die zweite
    Schranke dahinter: liegt am Zielpfad eine Datei mit fremden Zeilen, bricht
    das Schreiben ab statt zu mischen. Nachgestellt wird das, indem die
    Bybit-Datei in die Binance-Partition kopiert wird, wie es ein versehentlich
    kopiertes Verzeichnis oder eine halb gelaufene Migration hinterlässt.
    """
    bybit = DerivativesStore(tmp_path, venue="bybit")
    bybit.write("BTCUSDT", OI, _oi(1_000, 16_419.749))

    binance = DerivativesStore(tmp_path, venue="binance")
    ziel = binance.path("BTCUSDT", OI)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bybit.path("BTCUSDT", OI), ziel)

    with pytest.raises(ForeignVenueError, match="bybit"):
        binance.write("BTCUSDT", OI, _oi(2_000, 47_921.245))


def test_gleiche_venue_darf_anhaengen(tmp_path) -> None:
    """Die Gegenprobe -- der Schutz darf nicht alles aussperren."""
    store = DerivativesStore(tmp_path, venue="bybit")
    store.write("BTCUSDT", OI, _oi(1_000, 16_419.749))
    store.write("BTCUSDT", OI, _oi(2_000, 16_500.0))
    gelesen = store.read("BTCUSDT", OI)
    assert gelesen["ts"].tolist() == [1_000, 2_000]
    assert set(gelesen["venue"]) == {"bybit"}


# --------------------------------------------------------------------------- #
# Deduplizierung nicht allein über den Zeitstempel
# --------------------------------------------------------------------------- #


def test_dedupliziert_ueber_venue_und_zeitstempel(tmp_path) -> None:
    """Zwei Börsen können denselben Zeitstempel tragen und verschiedene Werte.

    Innerhalb einer Partition ist `ts` eindeutig; der Schlüssel muss trotzdem
    `(venue, ts)` sein, damit eine spätere Zusammenführung mehrerer Partitionen
    nicht stillschweigend eine Börse verschluckt.
    """
    store = DerivativesStore(tmp_path, venue="bybit")
    store.write("BTCUSDT", OI, _oi(1_000, 16_419.749))
    store.write("BTCUSDT", OI, _oi(1_000, 16_420.000))  # Korrektur, gleiche Zeit
    gelesen = store.read("BTCUSDT", OI)
    assert len(gelesen) == 1, "innerhalb einer Venue gewinnt die spaetere Zeile"
    assert gelesen["open_interest"].iloc[0] == 16_420.000


# --------------------------------------------------------------------------- #
# Das Erbe: lesbar, niemals beschreibbar
# --------------------------------------------------------------------------- #


def _legacy_anlegen(root, symbol: str, kind: str, ts: int, wert: float) -> None:
    """Eine Datei im ALTEN Layout, wie sie heute auf der Platte liegt."""
    pfad = root / symbol / f"{kind}.parquet"
    pfad.parent.mkdir(parents=True, exist_ok=True)
    spalte = "open_interest" if kind == OI else "buy_ratio"
    tabelle = pa.table({"ts": pa.array([ts], pa.int64()),
                        spalte: pa.array([wert], pa.float64())})
    pq.write_table(tabelle, pfad, compression="zstd")


def test_das_alte_layout_wird_niemals_beschrieben(tmp_path) -> None:
    """`bestehende Dateien nicht umschreiben` -- als Code, nicht als Vorsatz."""
    _legacy_anlegen(tmp_path, "BTCUSDT", OI, 1_000, 16_419.749)
    alt = tmp_path / "BTCUSDT" / f"{OI}.parquet"
    vorher = alt.read_bytes()

    store = DerivativesStore(tmp_path, venue="bybit")
    store.write("BTCUSDT", OI, _oi(2_000, 16_500.0))

    assert alt.read_bytes() == vorher, "die Legacy-Datei ist byte-identisch"
    assert store.path("BTCUSDT", OI) != alt


def test_legacy_wird_nur_bei_passender_venue_gelesen(tmp_path) -> None:
    """Kein stiller Ersatz mit einer anderen Börse.

    Das Manifest sagt, welche Venue die Legacy-Datei trägt. Ein Speicher für
    eine ANDERE Venue darf sie nicht als seine eigene lesen.
    """
    _legacy_anlegen(tmp_path, "BTCUSDT", OI, 1_000, 16_419.749)
    DerivativesStore.write_provenance(tmp_path, venue="bybit", evidence="Test")

    bybit = DerivativesStore(tmp_path, venue="bybit", on_foreign="legacy")
    assert bybit.read("BTCUSDT", OI)["open_interest"].tolist() == [16_419.749]

    binance = DerivativesStore(tmp_path, venue="binance", on_foreign="legacy")
    assert binance.read("BTCUSDT", OI).empty, (
        "fremde Legacy-Daten werden NICHT als eigene gelesen"
    )


def test_strenger_lesemodus_bricht_bei_fremdem_erbe_ab(tmp_path) -> None:
    _legacy_anlegen(tmp_path, "BTCUSDT", OI, 1_000, 16_419.749)
    DerivativesStore.write_provenance(tmp_path, venue="bybit", evidence="Test")
    streng = DerivativesStore(tmp_path, venue="binance", on_foreign="raise")
    with pytest.raises(ForeignVenueError, match="bybit"):
        streng.read("BTCUSDT", OI)


def test_erbe_ohne_manifest_wird_keiner_venue_zugeordnet(tmp_path) -> None:
    """`unbekannte Provenienz nicht automatisch einer Venue zuweisen`."""
    _legacy_anlegen(tmp_path, "BTCUSDT", OI, 1_000, 16_419.749)
    # Kein Manifest geschrieben.
    store = DerivativesStore(tmp_path, venue="bybit", on_foreign="legacy")
    assert store.read("BTCUSDT", OI).empty, (
        "ohne Manifest ist die Herkunft unbekannt, nicht 'bybit'"
    )

    streng = DerivativesStore(tmp_path, venue="bybit", on_foreign="raise")
    with pytest.raises(ForeignVenueError, match="unbekannt"):
        streng.read("BTCUSDT", OI)


def test_on_foreign_wird_erst_beim_erbe_verlangt(tmp_path) -> None:
    """Die Angabe ist dort Pflicht, wo sie etwas entscheidet -- und nur dort.

    Zuerst verlangte `read()` sie immer. Drei Tests fielen durch, die ihre
    EIGENE Partition lasen -- dort gibt es keine Fremddaten-Frage, und eine
    Pflichtangabe waere Zeremonie ohne Schutz gewesen. Jetzt entsteht die
    Frage genau dann, wenn ein Erbe unbekannter Herkunft in Betracht kommt.
    """
    store = DerivativesStore(tmp_path, venue="bybit")

    # Nichts da: keine Frage, leere Reihe.
    assert store.read("BTCUSDT", OI).empty

    # Eigene Partition: keine Frage.
    store.write("BTCUSDT", OI, _oi(1_000, 16_419.749))
    assert len(store.read("BTCUSDT", OI)) == 1

    # Ein Erbe fuer ein ANDERES Symbol: jetzt entsteht die Frage.
    _legacy_anlegen(tmp_path, "ETHUSDT", OI, 1_000, 1_234.5)
    with pytest.raises(TypeError, match="on_foreign"):
        store.read("ETHUSDT", OI)


# --------------------------------------------------------------------------- #
# Das Manifest
# --------------------------------------------------------------------------- #


def test_das_manifest_haelt_hash_und_beleg_fest(tmp_path) -> None:
    _legacy_anlegen(tmp_path, "BTCUSDT", OI, 1_000, 16_419.749)
    _legacy_anlegen(tmp_path, "ETHUSDT", RATIO, 1_000, 0.52)

    manifest = DerivativesStore.write_provenance(
        tmp_path,
        venue="bybit",
        evidence="BTCUSDT 2021-10-01 00:00 steht bei 16419.749 (Bybit) "
                 "gegen 47921.245 (Binance-Archiv)",
    )

    assert manifest["venue"] == "bybit"
    assert manifest["inferred"] is True, "die Venue steht in keiner Datei"
    assert "16419.749" in manifest["evidence"]
    eintraege = {e["path"]: e for e in manifest["files"]}
    assert f"BTCUSDT/{OI}.parquet" in eintraege
    assert f"ETHUSDT/{RATIO}.parquet" in eintraege
    for e in eintraege.values():
        assert len(e["sha256"]) == 64
        assert e["rows"] == 1
        assert e["first_ts"] == 1_000 and e["last_ts"] == 1_000
