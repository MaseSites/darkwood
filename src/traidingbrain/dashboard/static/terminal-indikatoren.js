/**
 * Die Indikatoren des Terminals: Rechnung und Verzeichnis.
 *
 * **Warum ein eigenes Modul.** Bis zum 20.10.2026 waren EMA 20 und EMA 200
 * im Zeichner festverdrahtet -- zwei Zahlen, die niemand aendern konnte. Wer
 * nur den 50er sehen will, hatte keine Stelle, an der er das sagt. Hier steht
 * die Rechnung getrennt von der Darstellung, und jeder Indikator beschreibt
 * SELBST, welche Parameter er hat. Das Panel baut sich daraus; ein neuer
 * Indikator braucht keine Zeile in der Oberflaeche.
 *
 * **Zwei Sorten, und der Unterschied ist nicht kosmetisch.** `overlay` liegt
 * in der Preisachse (EMA, Bollinger, VWAP). `pane` braucht eine eigene Achse,
 * weil seine Einheit keine Preiseinheit ist (RSI 0-100, MACD um null, Volumen
 * in Stueck). Ein RSI auf die Preisachse gelegt waere eine flache Linie am
 * unteren Rand -- genau der Fehler, den die Heatmap heute Abend schon einmal
 * gemacht hat.
 *
 * Alle Funktionen sind rein und geben ein Feld der Laenge der Eingabe zurueck,
 * mit `null` dort, wo der Indikator noch keinen Wert hat. Der Zeichner
 * ueberspringt `null`, statt bei 0 anzusetzen -- eine aufwaermende EMA, die
 * bei null beginnt, zieht eine Linie quer durch den Chart.
 */

/* ------------------------------------------------------------ Rechnung -- */

export function sma(werte, n) {
  const out = new Array(werte.length).fill(null);
  if (n < 1) return out;
  let summe = 0;
  for (let i = 0; i < werte.length; i++) {
    summe += werte[i];
    if (i >= n) summe -= werte[i - n];
    if (i >= n - 1) out[i] = summe / n;
  }
  return out;
}

export function ema(werte, n) {
  const out = new Array(werte.length).fill(null);
  if (n < 1 || werte.length < n) return out;
  const k = 2 / (n + 1);
  // Start auf dem einfachen Mittel der ersten n -- nicht auf werte[0]. Sonst
  // schleppt die Linie den ersten Kurs als Vorgeschichte mit sich herum.
  let v = 0;
  for (let i = 0; i < n; i++) v += werte[i];
  v /= n;
  out[n - 1] = v;
  for (let i = n; i < werte.length; i++) { v = werte[i] * k + v * (1 - k); out[i] = v; }
  return out;
}

export function stdabw(werte, n) {
  const out = new Array(werte.length).fill(null);
  const mittel = sma(werte, n);
  for (let i = n - 1; i < werte.length; i++) {
    let q = 0;
    for (let j = i - n + 1; j <= i; j++) { const d = werte[j] - mittel[i]; q += d * d; }
    out[i] = Math.sqrt(q / n);
  }
  return out;
}

export function trueRange(kerzen) {
  const out = new Array(kerzen.length).fill(null);
  for (let i = 0; i < kerzen.length; i++) {
    const k = kerzen[i];
    if (i === 0) { out[i] = k.high - k.low; continue; }
    const vz = kerzen[i - 1].close;
    out[i] = Math.max(k.high - k.low, Math.abs(k.high - vz), Math.abs(k.low - vz));
  }
  return out;
}

export function atr(kerzen, n) {
  // Wilders Glaettung, nicht das einfache Mittel -- so rechnet es jede Boerse
  // und jede Charting-Oberflaeche, und unsere Stops kommen aus derselben Zahl.
  const tr = trueRange(kerzen);
  const out = new Array(kerzen.length).fill(null);
  if (kerzen.length < n) return out;
  let v = 0;
  for (let i = 0; i < n; i++) v += tr[i];
  v /= n;
  out[n - 1] = v;
  for (let i = n; i < kerzen.length; i++) { v = (v * (n - 1) + tr[i]) / n; out[i] = v; }
  return out;
}

export function rsi(werte, n) {
  const out = new Array(werte.length).fill(null);
  if (werte.length <= n) return out;
  let auf = 0, ab = 0;
  for (let i = 1; i <= n; i++) {
    const d = werte[i] - werte[i - 1];
    if (d >= 0) auf += d; else ab -= d;
  }
  auf /= n; ab /= n;
  out[n] = ab === 0 ? 100 : 100 - 100 / (1 + auf / ab);
  for (let i = n + 1; i < werte.length; i++) {
    const d = werte[i] - werte[i - 1];
    auf = (auf * (n - 1) + Math.max(d, 0)) / n;
    ab = (ab * (n - 1) + Math.max(-d, 0)) / n;
    out[i] = ab === 0 ? 100 : 100 - 100 / (1 + auf / ab);
  }
  return out;
}

export function macd(werte, schnell, langsam, signal) {
  const a = ema(werte, schnell), b = ema(werte, langsam);
  const linie = werte.map((_, i) => (a[i] == null || b[i] == null ? null : a[i] - b[i]));
  const gefuellt = linie.map((v) => v ?? 0);
  const sig = ema(gefuellt, signal).map((v, i) => (linie[i] == null ? null : v));
  const hist = linie.map((v, i) => (v == null || sig[i] == null ? null : v - sig[i]));
  return { linie, signal: sig, hist };
}

export function stochastik(kerzen, n, glatt, d) {
  const roh = new Array(kerzen.length).fill(null);
  for (let i = n - 1; i < kerzen.length; i++) {
    let hi = -Infinity, lo = Infinity;
    for (let j = i - n + 1; j <= i; j++) { hi = Math.max(hi, kerzen[j].high); lo = Math.min(lo, kerzen[j].low); }
    roh[i] = hi === lo ? 50 : ((kerzen[i].close - lo) / (hi - lo)) * 100;
  }
  const k = sma(roh.map((v) => v ?? 0), glatt).map((v, i) => (roh[i] == null ? null : v));
  const dd = sma(k.map((v) => v ?? 0), d).map((v, i) => (k[i] == null ? null : v));
  return { k, d: dd };
}

export function bollinger(werte, n, mult) {
  const mitte = sma(werte, n), s = stdabw(werte, n);
  return {
    mitte,
    oben: werte.map((_, i) => (mitte[i] == null ? null : mitte[i] + mult * s[i])),
    unten: werte.map((_, i) => (mitte[i] == null ? null : mitte[i] - mult * s[i])),
  };
}

export function donchian(kerzen, n) {
  const oben = new Array(kerzen.length).fill(null), unten = new Array(kerzen.length).fill(null);
  for (let i = n - 1; i < kerzen.length; i++) {
    let hi = -Infinity, lo = Infinity;
    for (let j = i - n + 1; j <= i; j++) { hi = Math.max(hi, kerzen[j].high); lo = Math.min(lo, kerzen[j].low); }
    oben[i] = hi; unten[i] = lo;
  }
  return { oben, unten, mitte: oben.map((v, i) => (v == null ? null : (v + unten[i]) / 2)) };
}

export function keltner(kerzen, n, mult) {
  const mitte = ema(kerzen.map((k) => k.close), n), a = atr(kerzen, n);
  return {
    mitte,
    oben: mitte.map((v, i) => (v == null || a[i] == null ? null : v + mult * a[i])),
    unten: mitte.map((v, i) => (v == null || a[i] == null ? null : v - mult * a[i])),
  };
}

export function supertrend(kerzen, n, mult) {
  const a = atr(kerzen, n);
  const linie = new Array(kerzen.length).fill(null);
  const richtung = new Array(kerzen.length).fill(null);
  let obenVor = null, untenVor = null, rVor = 1;
  for (let i = 0; i < kerzen.length; i++) {
    if (a[i] == null) continue;
    const mp = (kerzen[i].high + kerzen[i].low) / 2;
    let ob = mp + mult * a[i], un = mp - mult * a[i];
    const vz = i > 0 ? kerzen[i - 1].close : kerzen[i].close;
    if (obenVor != null) ob = ob < obenVor || vz > obenVor ? ob : obenVor;
    if (untenVor != null) un = un > untenVor || vz < untenVor ? un : untenVor;
    let r = rVor;
    if (obenVor != null && kerzen[i].close > obenVor) r = 1;
    else if (untenVor != null && kerzen[i].close < untenVor) r = -1;
    linie[i] = r === 1 ? un : ob;
    richtung[i] = r;
    obenVor = ob; untenVor = un; rVor = r;
  }
  return { linie, richtung };
}

export function vwap(kerzen, zuruecksetzenMs) {
  // Rollt bei jedem neuen Abschnitt zurueck (Vorgabe: Kalendertag UTC). Ein
  // VWAP ohne Ruecksetzung ist nach ein paar Tagen eine waagrechte Linie und
  // sagt nichts mehr ueber den Handel von heute.
  const out = new Array(kerzen.length).fill(null);
  let pv = 0, v = 0, abschnitt = null;
  for (let i = 0; i < kerzen.length; i++) {
    const k = kerzen[i];
    const jetzt = zuruecksetzenMs > 0 ? Math.floor(k.ts / zuruecksetzenMs) : 0;
    if (abschnitt === null || jetzt !== abschnitt) { pv = 0; v = 0; abschnitt = jetzt; }
    const typ = (k.high + k.low + k.close) / 3;
    const menge = k.volume ?? 0;
    pv += typ * menge; v += menge;
    out[i] = v > 0 ? pv / v : null;
  }
  return out;
}

/* --------------------------------------------------------- Verzeichnis -- */

/**
 * Jeder Indikator beschreibt sich selbst. `felder` baut das Panel, `rechne`
 * liefert gezeichnete Linien. So kostet ein neuer Indikator genau einen
 * Eintrag hier und keine Zeile in der Oberflaeche.
 *
 * `linien[].art`: "linie" | "flaeche" (Band zwischen zwei Serien) | "balken"
 */
export const INDIKATOREN = {
  ema: {
    name: "EMA", art: "overlay", mehrfach: true,
    felder: [{ k: "n", label: "Periode", typ: "zahl", min: 1, max: 1000, vorgabe: 20 }],
    vorgaben: [{ n: 20, farbe: "#60a5fa" }, { n: 200, farbe: "#f87171" }],
    rechne: (kerzen, p) => [{ art: "linie", werte: ema(kerzen.map((k) => k.close), p.n), label: `EMA ${p.n}` }],
  },
  sma: {
    name: "SMA", art: "overlay", mehrfach: true,
    felder: [{ k: "n", label: "Periode", typ: "zahl", min: 1, max: 1000, vorgabe: 50 }],
    vorgaben: [{ n: 50, farbe: "#fbbf24" }],
    rechne: (kerzen, p) => [{ art: "linie", werte: sma(kerzen.map((k) => k.close), p.n), label: `SMA ${p.n}` }],
  },
  bb: {
    name: "Bollinger-Baender", art: "overlay",
    felder: [
      { k: "n", label: "Periode", typ: "zahl", min: 2, max: 400, vorgabe: 20 },
      { k: "mult", label: "Abweichungen", typ: "zahl", min: 0.5, max: 5, schritt: 0.1, vorgabe: 2 },
    ],
    vorgaben: [{ n: 20, mult: 2, farbe: "#a78bfa" }],
    rechne: (kerzen, p) => {
      const b = bollinger(kerzen.map((k) => k.close), p.n, p.mult);
      return [
        { art: "flaeche", oben: b.oben, unten: b.unten, label: `BB ${p.n}/${p.mult}` },
        { art: "linie", werte: b.mitte, dash: [4, 4] },
      ];
    },
  },
  keltner: {
    name: "Keltner-Kanal", art: "overlay",
    felder: [
      { k: "n", label: "Periode", typ: "zahl", min: 2, max: 400, vorgabe: 20 },
      { k: "mult", label: "ATR-Faktor", typ: "zahl", min: 0.5, max: 5, schritt: 0.1, vorgabe: 1.5 },
    ],
    vorgaben: [{ n: 20, mult: 1.5, farbe: "#2dd4bf" }],
    rechne: (kerzen, p) => {
      const b = keltner(kerzen, p.n, p.mult);
      return [{ art: "flaeche", oben: b.oben, unten: b.unten, label: `Keltner ${p.n}` },
              { art: "linie", werte: b.mitte, dash: [4, 4] }];
    },
  },
  donchian: {
    name: "Donchian-Kanal", art: "overlay",
    felder: [{ k: "n", label: "Periode", typ: "zahl", min: 2, max: 400, vorgabe: 20 }],
    vorgaben: [{ n: 20, farbe: "#94a3b8" }],
    rechne: (kerzen, p) => {
      const d = donchian(kerzen, p.n);
      return [{ art: "flaeche", oben: d.oben, unten: d.unten, label: `Donchian ${p.n}` }];
    },
  },
  supertrend: {
    name: "Supertrend", art: "overlay",
    felder: [
      { k: "n", label: "ATR-Periode", typ: "zahl", min: 2, max: 100, vorgabe: 10 },
      { k: "mult", label: "Faktor", typ: "zahl", min: 0.5, max: 10, schritt: 0.1, vorgabe: 3 },
    ],
    vorgaben: [{ n: 10, mult: 3, farbe: "#22c55e" }],
    rechne: (kerzen, p) => {
      const s = supertrend(kerzen, p.n, p.mult);
      return [{ art: "linie", werte: s.linie, richtung: s.richtung, label: `Supertrend ${p.n}/${p.mult}`, dick: 1.6 }];
    },
  },
  vwap: {
    name: "VWAP", art: "overlay",
    felder: [{
      k: "reset", label: "Ruecksetzung", typ: "auswahl", vorgabe: 86400000,
      optionen: [{ v: 3600000, t: "stuendlich" }, { v: 86400000, t: "taeglich" },
                 { v: 604800000, t: "woechentlich" }, { v: 0, t: "nie" }],
    }],
    vorgaben: [{ reset: 86400000, farbe: "#f0abfc" }],
    rechne: (kerzen, p) => [{ art: "linie", werte: vwap(kerzen, Number(p.reset)), label: "VWAP", dick: 1.4 }],
  },

  rsi: {
    name: "RSI", art: "pane", hoehe: 70, skala: [0, 100], marken: [30, 50, 70],
    felder: [{ k: "n", label: "Periode", typ: "zahl", min: 2, max: 200, vorgabe: 14 }],
    vorgaben: [{ n: 14, farbe: "#c084fc" }],
    rechne: (kerzen, p) => [{ art: "linie", werte: rsi(kerzen.map((k) => k.close), p.n), label: `RSI ${p.n}` }],
  },
  macd: {
    name: "MACD", art: "pane", hoehe: 70, marken: [0],
    felder: [
      { k: "schnell", label: "schnell", typ: "zahl", min: 1, max: 200, vorgabe: 12 },
      { k: "langsam", label: "langsam", typ: "zahl", min: 2, max: 400, vorgabe: 26 },
      { k: "signal", label: "Signal", typ: "zahl", min: 1, max: 100, vorgabe: 9 },
    ],
    vorgaben: [{ schnell: 12, langsam: 26, signal: 9, farbe: "#38bdf8" }],
    rechne: (kerzen, p) => {
      const m = macd(kerzen.map((k) => k.close), p.schnell, p.langsam, p.signal);
      return [{ art: "balken", werte: m.hist, label: "Histogramm" },
              { art: "linie", werte: m.linie, label: "MACD" },
              { art: "linie", werte: m.signal, farbe: "#fb923c", dash: [3, 3], label: "Signal" }];
    },
  },
  stoch: {
    name: "Stochastik", art: "pane", hoehe: 70, skala: [0, 100], marken: [20, 50, 80],
    felder: [
      { k: "n", label: "Periode", typ: "zahl", min: 2, max: 200, vorgabe: 14 },
      { k: "glatt", label: "%K-Glaettung", typ: "zahl", min: 1, max: 50, vorgabe: 3 },
      { k: "d", label: "%D", typ: "zahl", min: 1, max: 50, vorgabe: 3 },
    ],
    vorgaben: [{ n: 14, glatt: 3, d: 3, farbe: "#34d399" }],
    rechne: (kerzen, p) => {
      const s = stochastik(kerzen, p.n, p.glatt, p.d);
      return [{ art: "linie", werte: s.k, label: "%K" },
              { art: "linie", werte: s.d, farbe: "#fb923c", dash: [3, 3], label: "%D" }];
    },
  },
  atr: {
    name: "ATR", art: "pane", hoehe: 56,
    felder: [{ k: "n", label: "Periode", typ: "zahl", min: 2, max: 200, vorgabe: 14 }],
    vorgaben: [{ n: 14, farbe: "#fbbf24" }],
    rechne: (kerzen, p) => [{ art: "linie", werte: atr(kerzen, p.n), label: `ATR ${p.n}` }],
  },
  volumen: {
    name: "Volumen", art: "pane", hoehe: 56,
    felder: [{ k: "n", label: "Mittel ueber", typ: "zahl", min: 1, max: 400, vorgabe: 20 }],
    vorgaben: [{ n: 20, farbe: "#64748b" }],
    rechne: (kerzen, p) => {
      const v = kerzen.map((k) => k.volume ?? 0);
      return [{ art: "balken", werte: v, nachKerze: true, label: "Volumen" },
              { art: "linie", werte: sma(v, p.n), farbe: "#fbbf24", label: `Mittel ${p.n}` }];
    },
  },
};

/** Die Vorgabe-Belegung: was sichtbar ist, wenn noch nie etwas eingestellt wurde. */
export function vorgabeBelegung() {
  return {
    ema: INDIKATOREN.ema.vorgaben.map((v) => ({ ...v, an: true })),
    volumen: INDIKATOREN.volumen.vorgaben.map((v) => ({ ...v, an: false })),
  };
}
