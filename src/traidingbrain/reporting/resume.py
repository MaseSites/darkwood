"""Partial results a study can come back to.

A study over four markets and four years takes hours, and the laptop it runs on
gets shut down. Twice now a run has died on the last of four markets and thrown
away everything the first three produced -- which makes the study not slow but
unfinishable, because the window between shutdowns is shorter than the run.

So each market's results are written as soon as that market is done, and a
restart skips what is already there. Nothing clever: one JSON file per study,
keyed by market, replaced wholesale on each write.

**Keyed on the question, not only on the market.** A file that remembered
"BTCUSDT: 495 trades" could not say *which* configuration produced it, and the
next study to reuse the name would silently inherit the last one's numbers. The
key carries the variant, and the file carries a signature of the settings the
run was made under; a signature that no longer matches is discarded rather than
merged, because half a comparison across two configurations is worse than none.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Partial:
    """What a study has finished so far.

    Values are plain lists of floats -- the R multiples of every trade in one
    (market, variant) cell. Anything a study wants to report is derivable from
    those, and keeping the raw numbers means a changed summary does not need a
    new four-hour run.
    """

    path: Path
    signature: str
    cells: dict[str, list[float]] = field(default_factory=dict)
    notes: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path, signature: str) -> Partial:
        """Whatever is on disk for this signature, or an empty start.

        A file written under different settings is dropped rather than merged.
        Comparing three markets measured one way against one measured another
        is not a comparison, and the failure would be invisible in the output.
        """
        if not path.exists():
            return cls(path=path, signature=signature)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls(path=path, signature=signature)
        if data.get("signature") != signature:
            return cls(path=path, signature=signature)
        return cls(
            path=path,
            signature=signature,
            cells={k: [float(x) for x in v] for k, v in data.get("cells", {}).items()},
            notes=dict(data.get("notes", {})),
        )

    @staticmethod
    def key(symbol: str, variant: str) -> str:
        return f"{symbol}|{variant}"

    def has(self, symbol: str, variant: str) -> bool:
        return self.key(symbol, variant) in self.cells

    def put(self, symbol: str, variant: str, values: list[float], **notes: Any) -> None:
        """Record one cell and write immediately.

        Immediately, because the whole point is surviving a shutdown that gives
        no warning. One file rewrite per market per variant is nothing next to
        the minutes of computation it protects.
        """
        self.cells[self.key(symbol, variant)] = [round(float(v), 6) for v in values]
        for name, value in notes.items():
            self.notes[f"{self.key(symbol, variant)}|{name}"] = value
        self.save()

    def note(self, symbol: str, variant: str, name: str) -> Any:
        return self.notes.get(f"{self.key(symbol, variant)}|{name}")

    def collect(self, variant: str) -> list[float]:
        """Every market's values for one variant, pooled."""
        out: list[float] = []
        for key, values in self.cells.items():
            if key.endswith(f"|{variant}"):
                out.extend(values)
        return out

    def symbols_done(self, variant: str) -> list[str]:
        return sorted(k.split("|")[0] for k in self.cells if k.endswith(f"|{variant}"))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"signature": self.signature, "cells": self.cells, "notes": self.notes}
        # Written beside the target and moved into place, so a shutdown during
        # the write leaves the previous file intact rather than a truncated one.
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(self.path)
