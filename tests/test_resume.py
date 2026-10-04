"""Partial study results, and the two ways resuming goes quietly wrong.

A study over four markets takes hours and the laptop it runs on gets shut down.
Twice a run died on the last of four markets and threw away the first three,
which made the study unfinishable rather than slow. So results are written per
market and a restart skips what is there.

The risk that comes with resuming is worse than the problem it solves, because
it is silent: a run that picks up numbers measured under *different* settings
reports a comparison that was never made, and nothing in the output says so.
Two tests exist for that, and one for the shutdown landing mid-write.
"""

from __future__ import annotations

import json
from pathlib import Path

from traidingbrain.reporting.resume import Partial


def test_a_finished_market_is_not_computed_again(tmp_path: Path) -> None:
    """The whole point: four hours of work survives the machine going off."""
    path = tmp_path / "study.json"
    first = Partial.load(path, signature="v1")
    first.put("BTCUSDT", "alle", [0.5, -1.0, 2.0])

    resumed = Partial.load(path, signature="v1")

    assert resumed.has("BTCUSDT", "alle")
    assert not resumed.has("ETHUSDT", "alle")
    assert resumed.collect("alle") == [0.5, -1.0, 2.0]


def test_results_from_other_settings_are_dropped_rather_than_merged(tmp_path: Path) -> None:
    """The failure that would be invisible.

    Three markets measured at one starting equity and a fourth at another is
    not a comparison, and a pooled mean over the four would look exactly like a
    real one. Discarding is the only safe answer: recomputing costs hours,
    reporting a number nobody can trust costs more.
    """
    path = tmp_path / "study.json"
    old = Partial.load(path, signature="equity=10000")
    old.put("BTCUSDT", "alle", [1.0, 1.0])
    old.put("ETHUSDT", "alle", [1.0])

    fresh = Partial.load(path, signature="equity=1000")

    assert not fresh.has("BTCUSDT", "alle")
    assert fresh.collect("alle") == []


def test_a_damaged_file_starts_over_instead_of_raising(tmp_path: Path) -> None:
    """A shutdown during a write, or anything else that truncates the file.

    Starting over costs the run; raising costs the run *and* leaves a study
    that cannot be started again without someone deleting a file by hand.
    """
    path = tmp_path / "study.json"
    path.write_text('{"signature": "v1", "cells": {"BTC', encoding="utf-8")

    recovered = Partial.load(path, signature="v1")

    assert recovered.cells == {}
    recovered.put("BTCUSDT", "alle", [0.1])
    assert Partial.load(path, signature="v1").has("BTCUSDT", "alle")


def test_the_file_is_replaced_atomically(tmp_path: Path) -> None:
    """Written beside the target and moved into place.

    A shutdown halfway through a direct write leaves a truncated file, and the
    next run would discard everything -- which is exactly the loss this module
    was built to prevent, reintroduced by how it saves.
    """
    path = tmp_path / "study.json"
    partial = Partial.load(path, signature="v1")
    partial.put("BTCUSDT", "alle", [1.0])
    partial.put("ETHUSDT", "alle", [2.0])

    assert not path.with_suffix(".tmp").exists(), "the scratch file was left behind"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data["cells"]) == {"BTCUSDT|alle", "ETHUSDT|alle"}


def test_variants_of_one_market_are_kept_apart(tmp_path: Path) -> None:
    """A market appears once per variant, and pooling must not mix them.

    Without the variant in the key, the second cadence written for a market
    would overwrite the first and the comparison would silently become a
    comparison of one thing with itself.
    """
    path = tmp_path / "study.json"
    partial = Partial.load(path, signature="v1")
    partial.put("BTCUSDT", "H1", [1.0, 1.0])
    partial.put("BTCUSDT", "M15", [-1.0])

    assert partial.collect("H1") == [1.0, 1.0]
    assert partial.collect("M15") == [-1.0]
    assert partial.symbols_done("H1") == ["BTCUSDT"]


def test_notes_travel_with_their_cell(tmp_path: Path) -> None:
    """A pooled summary needs the span each market covered, and a resumed run
    has to read it off disk rather than from a process that never computed it."""
    path = tmp_path / "study.json"
    partial = Partial.load(path, signature="v1")
    partial.put("BTCUSDT", "H1", [1.0], first_ts=100, last_ts=900)

    resumed = Partial.load(path, signature="v1")

    assert resumed.note("BTCUSDT", "H1", "first_ts") == 100
    assert resumed.note("BTCUSDT", "H1", "last_ts") == 900
    assert resumed.note("ETHUSDT", "H1", "first_ts") is None
