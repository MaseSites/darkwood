/**
 * Der Chart des Darkwood Terminals -- mit umschaltbaren Ebenen.
 *
 * Jede Ebene zeichnet EINE Art von Marktstruktur, und jede kommt aus der
 * Analyse, nicht aus einer Erfindung im Browser:
 *
 *   ema        EMA 20 / 200, hier aus den Kerzen gerechnet
 *   fvg        Fair Value Gaps          (bands: fvg_bullish / fvg_bearish)
 *   zonen      Angebot und Nachfrage    (bands: supply / demand)
 *   liquiditaet gleiche Hochs/Tiefs     (bands: equal_highs / equal_lows)
 *              plus die Sweeps, die sie geholt haben (events: sweep_up/down)
 *   struktur   BOS und CHoCH            (events) und Swings (levels)
 *   trend      Trendlinien              (diagonals)
 *   volumen    Volumenprofil links      (aus den Kerzen)
 *   heatmap    ruhende Liquiditaet rechts (aus dem Orderbuch)
 *   positionen Einstieg / Stop / Ziel
 *
 * ZOOM UND VERSCHIEBEN: `visible` (wie viele Kerzen) und `end` (Index der
 * letzten sichtbaren). `end` darf GROESSER sein als die Kerzenzahl -- dann
 * entsteht rechts leerer Raum, wie bei TradingView, damit man die aktuelle
 * Kerze aus dem rechten Rand holen kann.
 */

import { INDIKATOREN } from "./terminal-indikatoren.js";
import { WERKZEUGE } from "./terminal-zeichnen.js";
import {
  achsenText, countdownText, heikinAshi, skalaBauen, zeichneHochTief, zeichneKerzen,
  zeichneSitzungen, zeitText,
} from "./terminal-darstellung.js";

const PAD = { left: 56, right: 92, top: 14, bottom: 26 };
//: Luft zwischen zwei Unterachsen. Zwei Register, nicht eins: 6 px INNERHALB
//: einer Achse (Beschriftung zum Rand), 10 px ZWISCHEN ihnen -- sonst lesen
//: sich drei gestapelte Achsen als eine einzige gestreifte Flaeche.
const PANE_LUFT = 10;

/**
 * Die EBENEN sind die Zeichnungen des Charts -- Zonen, Pools, Struktur,
 * Linien. Sie werden an- und ausgeschaltet, mehr nicht, und gehoeren ins
 * Settings-Fenster.
 *
 * Die INDIKATOREN (terminal-indikatoren.js) sind gerechnete Kurven mit
 * Parametern und haben ein eigenes Fenster. `ema` stand bis zum 20.10.2026
 * HIER und war damit auf 20 und 200 festgenagelt -- wer nur den 50er sehen
 * wollte, hatte keine Stelle, an der er das sagt.
 */
export const EBENEN = {
  fvg: "Fair Value Gaps",
  zonen: "Angebot & Nachfrage",
  liquiditaet: "Liquidität (Pools & Sweeps)",
  struktur: "Struktur (BOS / CHoCH / Swings)",
  trend: "Trendlinien",
  volumen: "Volumen-Näherung (aus Kerzen)",
  vprofil: "Volumenprofil + VPOC (echte Trades)",
  heatmap: "Orderbuch-Heatmap",
  grosstrades: "Grosse Trades (Beträge je Preis)",
  optionen: "Options-Strikes · Gamma-Last (BTC/ETH)",
  positionen: "Positionen & Linien",
  // Keine Chart-Ebenen, sondern SEITENTEILE. Sie stehen trotzdem hier, weil
  // der Nutzer sie im selben Fenster sucht -- "was sehe ich" ist eine Frage,
  // und nicht zwei. Der Zeichner ignoriert sie; terminal.js blendet die
  // Kaesten aus.
  kalender: "Wirtschaftskalender (Seitenleiste)",
  orderbuch: "Orderbuch (Seitenleiste)",
  watchlist: "Watchlist (Seitenleiste)",
};

//: Welche Eintraege KEINE Chart-Ebenen sind, sondern Seitenteile.
export const SEITENTEILE = { watchlist: "#panel-watchlist", kalender: "#panel-kalender", orderbuch: "#panel-orderbuch" };

const BAND_EBENE = {
  fvg_bullish: "fvg", fvg_bearish: "fvg",
  supply: "zonen", demand: "zonen",
  order_block_bullish: "zonen", order_block_bearish: "zonen",
  equal_highs: "liquiditaet", equal_lows: "liquiditaet",
};
const BAND_FARBE = {
  fvg_bullish: "245,158,11", fvg_bearish: "245,158,11",
  supply: "248,113,113", demand: "52,211,153",
  order_block_bullish: "52,211,153", order_block_bearish: "248,113,113",
  equal_highs: "248,113,113", equal_lows: "96,165,250",
};

export function ema(values, n) {
  const k = 2 / (n + 1);
  const out = new Array(values.length).fill(null);
  let acc = null;
  for (let i = 0; i < values.length; i++) {
    acc = acc === null ? values[i] : values[i] * k + acc * (1 - k);
    if (i >= n - 1) out[i] = acc;
  }
  return out;
}

export function fmt(p) {
  const a = Math.abs(p ?? 0);
  if (a >= 1000) return (p ?? 0).toLocaleString("de-CH", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
  if (a >= 10) return (p ?? 0).toFixed(2);
  return (p ?? 0).toFixed(4);
}

function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

export function drawTerminalChart(canvas, view, opts = {}) {
  const ratio = window.devicePixelRatio || 1;
  const W = canvas.clientWidth, H = canvas.clientHeight;
  const candles = opts.candles ?? view?.candles ?? [];
  if (!W || !H || !candles.length) return null;
  if (canvas.width !== W * ratio || canvas.height !== H * ratio) { canvas.width = W * ratio; canvas.height = H * ratio; }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, W, H);

  const an = opts.layers ?? {};
  const on = (k) => an[k] !== false;
  const c = {
    rule: cssVar("--rule"), ink: cssVar("--ink"), ink3: cssVar("--ink-3"), long: cssVar("--long"),
    short: cssVar("--short"), star: cssVar("--star"), mark: cssVar("--mark"), surface: cssVar("--surface"),
    ground: cssVar("--ground"), ink2: cssVar("--ink-2"), raised: cssVar("--raised"),
    // `c.mono` wurde schon vor dem 21.10. benutzt (Pool-Beschriftung) und
    // war nie gesetzt -- die Schrift fiel still auf die Vorgabe zurueck.
    mono: 'ui-monospace, "Cascadia Mono", Menlo, monospace',
  };
  // Ansicht und Skala aus der Bedienung (terminal-ansicht.js). Fehlt beides,
  // ist alles wie vor dem 21.10.: Kerzen, linear, Gitter an.
  const ansicht = opts.ansicht ?? {};
  const skala = opts.skala ?? {};

  const pL = PAD.left, pR = W - PAD.right, pT = PAD.top;
  // Die Unterachsen werden VOM Preisbereich abgezogen, nicht ueber ihn gelegt.
  // Ein RSI (0-100) in der Preisachse waere ein flacher Strich am unteren
  // Rand -- derselbe Groessenordnungsfehler wie bei der Heatmap heute Abend.
  const aktivePanes = (opts.indikatoren ?? [])
    .filter((e) => e.an !== false && INDIKATOREN[e.art]?.art === "pane");
  const paneHoehen = aktivePanes.map((e) => INDIKATOREN[e.art].hoehe ?? 60);
  const paneGesamt = paneHoehen.reduce((a, b) => a + b + PANE_LUFT, 0);
  const pBvoll = H - PAD.bottom;
  // Der Preis behaelt mindestens 45 % der Hoehe; wer sechs Unterachsen
  // anschaltet, bekommt sie schmaler statt einen Chart ohne Kerzen.
  const pB = Math.max(pT + (pBvoll - pT) * 0.45, pBvoll - paneGesamt);
  const pW = pR - pL, pH = pB - pT;

  const total = candles.length;
  const visible = Math.max(20, Math.min(2000, Math.round(opts.visible ?? Math.max(60, Math.floor(pW / 7)))));
  // `end` darf ueber die Kerzenzahl hinausgehen -- der Ueberhang wird rechts
  // zu leerem Raum. Begrenzt auf ein Drittel des Fensters, damit der Chart
  // nicht ins Nichts geschoben werden kann.
  const maxEnd = total + Math.floor(visible / 3);
  const end = opts.end === null || opts.end === undefined ? total : Math.max(20, Math.min(maxEnd, Math.round(opts.end)));
  const offset = end - visible;
  const shown = candles.slice(Math.max(0, offset), Math.min(total, end));
  if (!shown.length) return null;
  const leer = Math.max(0, end - total);                 // leere Spalten rechts
  const spalten = shown.length + leer + Math.max(0, -offset);
  const vorn = Math.max(0, -offset);                     // leere Spalten links
  const formingIndex = opts.forming && end >= total ? vorn + shown.length - 1 : -1;

  let lo = Math.min(...shown.map((k) => k.low)), hi = Math.max(...shown.map((k) => k.high));
  if (on("positionen")) for (const line of opts.lines ?? []) {
    if (line.price > lo * 0.85 && line.price < hi * 1.15) { lo = Math.min(lo, line.price); hi = Math.max(hi, line.price); }
  }
  const padP = (hi - lo) * 0.06 || 1;
  lo -= padP; hi += padP;
  // Von Hand gezogene Preisachse (TradingView: Achse ziehen = Auto aus).
  // Gespeichert als Faktor um die Mitte, nicht als feste Preise -- so bleibt
  // die Streckung beim naechsten Tick und beim Verschieben erhalten.
  if (skala.streckung && skala.streckung !== 1) {
    const mitte = (lo + hi) / 2, halb = ((hi - lo) / 2) * skala.streckung;
    lo = mitte - halb; hi = mitte + halb;
  }
  if (skala.modus === "log" && lo <= 0) lo = Math.min(...shown.map((k) => k.low)) * 0.98;
  const span = hi - lo;
  const sk = skalaBauen({ modus: skala.modus, invert: !!skala.invert, lo, hi, pT, pB });
  const y = sk.y;
  const basis = shown[0]?.close;
  const slot = pW / spalten;
  const x = (i) => pL + slot * (i + 0.5);                 // i = Spaltenindex
  const xk = (ki) => x(vorn + ki);                        // ki = Index in `shown`
  const body = Math.max(1, Math.floor(slot * 0.66));

  /* ---- Raster + Preisachse ---- */
  ctx.font = '11px ui-monospace, "Cascadia Mono", Menlo, monospace';
  ctx.textBaseline = "middle";
  // Unter log rueckt das Gitter oben zusammen: Linien, die naeher als 18 px
  // an der vorigen laegen, fallen weg, statt sich zu ueberschreiben.
  const step = niceStep(span, sk.log ? 10 : 6);
  let letzteY = null;
  for (let p = Math.ceil(lo / step) * step; p <= hi; p += step) {
    const py = Math.round(y(p)) + 0.5;
    if (letzteY !== null && Math.abs(py - letzteY) < 18) continue;
    letzteY = py;
    if (ansicht.gitter !== false) {
      ctx.strokeStyle = c.rule; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(pL, py); ctx.lineTo(pR, py); ctx.stroke();
    }
    ctx.fillStyle = c.ink3; ctx.textAlign = "left";
    ctx.fillText(achsenText(p, skala.modus, basis, fmt), pR + 8, py);
  }
  if (ansicht.gitter !== false && ansicht.gitterSenkrecht !== false) {
    ctx.save(); ctx.strokeStyle = c.rule; ctx.globalAlpha = 0.55; ctx.lineWidth = 1;
    const jede = Math.max(1, Math.round(96 / slot));
    ctx.beginPath();
    for (let i = 0; i < shown.length; i += jede) { const gx = Math.round(xk(i)) + 0.5; ctx.moveTo(gx, pT); ctx.lineTo(gx, pB); }
    ctx.stroke(); ctx.restore();
  }

  /* ---- Zonen-Ebenen (fvg / zonen / liquiditaet) ---- */
  const lastClose = shown[shown.length - 1].close;
  for (const b of view?.bands ?? []) {
    const ebene = BAND_EBENE[b.kind];
    if (!ebene || !on(ebene)) continue;
    if (b.high < lo || b.low > hi) continue;
    const top = y(b.high), bottom = y(b.low);
    const rgb = BAND_FARBE[b.kind] ?? "124,138,163";
    // Ab dem Balken, an dem die Zone entstand -- nicht ueber die ganze Breite.
    // Ein Pool ueber den ganzen Chart behauptet, er haette schon vorher
    // dagelegen; gelesen wird er als "liegt seit DANN da und ist offen".
    const iStart = b.from_ts == null ? null : indexFuerTs(candles, b.from_ts);
    const xStart = iStart == null ? pL : Math.max(pL, xk(iStart - Math.max(0, offset)));
    ctx.fillStyle = `rgba(${rgb},0.16)`;
    ctx.fillRect(xStart, top, Math.max(2, pR - xStart), Math.max(2, bottom - top));
    if (ebene === "liquiditaet") {
      // Pools bekommen eine Kante und Sterne: die Zahl der Beruehrungen ist
      // das Mass, wie viel dort liegt.
      ctx.strokeStyle = `rgba(${rgb},0.55)`; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(xStart, top + 0.5); ctx.lineTo(pR, top + 0.5); ctx.stroke();
      drawStars(ctx, pR - 8, top + 10, naechsteBeruehrungen(view, b), c);
      // Wer hier liegt: ueber dem Preis die Stops der Shorts (Kaufseite),
      // darunter die der Longs. Das ist die Richtung, in die der Markt zieht.
      const kaufseite = b.kind === "equal_highs";
      ctx.fillStyle = `rgba(${rgb},0.85)`;
      ctx.font = `9px ${c.mono}`;
      ctx.textAlign = "left";
      ctx.fillText(kaufseite ? "Kaufseite" : "Verkaufsseite", xStart + 4, top - 3);
    }
  }

  /* ---- Trendlinien ---- */
  // Beschnitten auf den Preisbereich. Seit die Unterachsen (RSI, Volumen)
  // Platz vom Preis abziehen, endet er oberhalb des Chartbodens -- eine
  // verlaengerte Trendlinie lief sonst quer durch den RSI und sah dort aus
  // wie ein Indikator, der sie nie gezeichnet hat.
  ctx.save();
  ctx.beginPath(); ctx.rect(pL, pT, pR - pL, pB - pT); ctx.clip();
  if (on("trend")) for (const g of view?.diagonals ?? []) {
    const i0 = indexFuerTs(candles, g.from_ts), i1 = indexFuerTs(candles, g.to_ts);
    if (i0 === null || i1 === null) continue;
    ctx.save();
    ctx.strokeStyle = g.kind === "support" ? "rgba(52,211,153,0.5)" : "rgba(248,113,113,0.5)";
    ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(xk(i0 - Math.max(0, offset)), y(g.from_price));
    ctx.lineTo(xk(i1 - Math.max(0, offset)), y(g.to_price)); ctx.stroke(); ctx.restore();
  }

  ctx.restore();

  /* ---- Volumenprofil links ---- */
  if (on("volumen")) drawProfile(ctx, shown, { pL, pT, pB, y, lo, hi });
  if (on("vprofil") && opts.vprofil) drawEchtesProfil(ctx, opts.vprofil, { pL, pR, pT, pB, y, lo, hi, c });
  if (on("grosstrades") && opts.grosstrades) drawGrosseTrades(ctx, opts.grosstrades, { pL, pR, pT, pB, y, lo, hi, c });
  if (on("optionen") && opts.optionen?.verfuegbar) drawOptionen(ctx, opts.optionen, { pL, pR, pT, pB, y, lo, hi, c });

  /* ---- EMAs ---- */
  // Zeichnet eine Serie in einen beliebigen Bereich. `yy` bildet den Wert auf
  // Pixel ab -- fuer Overlays die Preisachse, fuer Unterachsen deren eigene.
  // `null` wird UEBERSPRUNGEN statt auf 0 gesetzt: eine aufwaermende EMA, die
  // bei null beginnt, zieht sonst eine Linie quer durch den Chart.
  const zeichneSerie = (serie, yy, { farbe, dash = [], dick = 1.2, richtung = null }) => {
    ctx.save(); ctx.setLineDash(dash); ctx.lineWidth = dick;
    let offen = false, letzteR = null;
    for (let i = 0; i < shown.length; i++) {
      const j = Math.max(0, offset) + i;
      const v = serie[j];
      if (v === null || v === undefined || !Number.isFinite(v)) { if (offen) { ctx.stroke(); offen = false; } continue; }
      // Supertrend wechselt die Farbe mit der Richtung -- dafuer muss der Zug
      // an der Wende abgesetzt werden, sonst faerbt die letzte Farbe alles.
      const r = richtung ? richtung[j] : null;
      if (offen && richtung && r !== letzteR) { ctx.stroke(); offen = false; }
      if (!offen) {
        ctx.strokeStyle = richtung ? (r === 1 ? c.long : c.short) : farbe;
        ctx.beginPath(); ctx.moveTo(xk(i), yy(v)); offen = true;
      } else ctx.lineTo(xk(i), yy(v));
      letzteR = r;
    }
    if (offen) ctx.stroke();
    ctx.restore();
  };

  const zeichneFlaeche = (oben, unten, yy, farbe) => {
    ctx.save(); ctx.fillStyle = `${farbe}22`;
    ctx.beginPath();
    let erster = null, letzter = null;
    for (let i = 0; i < shown.length; i++) {
      const v = oben[Math.max(0, offset) + i];
      if (v == null) continue;
      if (erster === null) { erster = i; ctx.moveTo(xk(i), yy(v)); } else ctx.lineTo(xk(i), yy(v));
      letzter = i;
    }
    if (erster === null) { ctx.restore(); return; }
    for (let i = letzter; i >= erster; i--) {
      const v = unten[Math.max(0, offset) + i];
      if (v != null) ctx.lineTo(xk(i), yy(v));
    }
    ctx.closePath(); ctx.fill(); ctx.restore();
    zeichneSerie(oben, yy, { farbe, dick: 1 });
    zeichneSerie(unten, yy, { farbe, dick: 1 });
  };

  /* ---- Overlay-Indikatoren (einstellbar, nicht mehr festverdrahtet) ---- */
  const legende = [];
  ctx.save();
  ctx.beginPath(); ctx.rect(pL, pT, pR - pL, pB - pT); ctx.clip();
  for (const eintrag of opts.indikatoren ?? []) {
    const def = INDIKATOREN[eintrag.art];
    if (!def || def.art !== "overlay" || eintrag.an === false) continue;
    let serien;
    try { serien = def.rechne(candles, eintrag); } catch { continue; }
    for (const sr of serien) {
      const farbe = sr.farbe ?? eintrag.farbe ?? "#60a5fa";
      if (sr.art === "flaeche") zeichneFlaeche(sr.oben, sr.unten, y, farbe);
      else zeichneSerie(sr.werte, y, { farbe, dash: sr.dash ?? [], dick: sr.dick ?? 1.2, richtung: sr.richtung ?? null });
      if (sr.label) {
        const reihe = sr.werte ?? sr.oben ?? [];
        legende.push({ label: sr.label, reihe, wert: reihe.filter((v) => v != null).pop(), farbe });
      }
    }
  }

  ctx.restore();

  /* ---- Sitzungswechsel ---- */
  if (ansicht.sitzungen) zeichneSitzungen(ctx, shown, xk, { pT, pB, c });

  /* ---- Vergleich (zweites Symbol, auf den ersten sichtbaren Schluss normiert) ---- */
  if (opts.vergleich?.candles?.length && basis) {
    const nachTs = new Map(opts.vergleich.candles.map((k) => [k.ts, k.close]));
    let vBasis = null;
    ctx.save(); ctx.strokeStyle = "#c084fc"; ctx.lineWidth = 1.3; ctx.beginPath();
    let offen = false, letzterWert = null;
    for (let i = 0; i < shown.length; i++) {
      const v = nachTs.get(shown[i].ts);
      if (v == null) { offen = false; continue; }
      vBasis ??= v;
      const p = basis * (v / vBasis);
      letzterWert = (v / vBasis - 1) * 100;
      if (!offen) { ctx.moveTo(xk(i), y(p)); offen = true; } else ctx.lineTo(xk(i), y(p));
    }
    ctx.stroke(); ctx.restore();
    opts.vergleich.prozent = letzterWert;
  }

  /* ---- Kerzen (im gewaehlten Typ) ---- */
  const plot = ansicht.typ === "ha"
    ? heikinAshi(candles).slice(Math.max(0, offset), Math.min(total, end))
    : shown;
  zeichneKerzen(ctx, ansicht.typ ?? "kerzen", plot, shown, {
    xk, y, body, c, formingKi: formingIndex >= 0 ? formingIndex - vorn : -1, pT, pB, pL, pR,
  });
  if (ansicht.hochTief) zeichneHochTief(ctx, shown, xk, y, { c, pL, pR }, fmt);

  /* ---- Struktur: BOS / CHoCH / Sweeps als Marken an der Kerze ---- */
  if (on("struktur") || on("liquiditaet")) {
    for (const e of view?.events ?? []) {
      const ki = (e.bar_index ?? -1) - Math.max(0, offset);
      if (ki < 0 || ki >= shown.length) continue;
      const istSweep = String(e.kind).startsWith("sweep");
      if (istSweep ? !on("liquiditaet") : !on("struktur")) continue;
      const k = shown[ki];
      const runter = e.kind === "sweep_down" || e.kind === "bos_down";
      const py = runter ? y(k.low) + 10 : y(k.high) - 10;
      ctx.fillStyle = istSweep ? c.star : (e.kind === "choch" ? c.mark : c.ink3);
      ctx.font = "9px ui-monospace, Menlo, monospace"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      const label = istSweep ? (runter ? "↓LQ" : "↑LQ") : (e.kind === "choch" ? "CHoCH" : "BOS");
      ctx.fillText(label, xk(ki), py);
    }
  }

  /* ---- Signalkerze ---- */
  if (opts.signalIndex !== undefined) {
    const ki = opts.signalIndex - Math.max(0, offset);
    if (ki >= 0 && ki < shown.length) {
      const k = shown[ki];
      ctx.strokeStyle = c.mark; ctx.lineWidth = 1.5;
      ctx.strokeRect(xk(ki) - body / 2 - 4, y(k.high) - 4, body + 8, y(k.low) - y(k.high) + 8);
    }
  }

  /* ---- Orderbuch-Heatmap am rechten Rand ---- */
  if (on("heatmap") && opts.book) drawHeatmap(ctx, opts.book, { pR, y, lo, hi, pH });

  /* ---- Zeichnungen des Nutzers ---- */
  // Nach den Kerzen, vor den Positionslinien: was ein Mensch von Hand
  // eingezeichnet hat, gehoert ueber den Kurs und unter die Kontozahlen.
  const zeitZuX = (ts, idx) => {
    // Rechts der letzten Kerze gibt es keinen Zeitstempel mehr -- dort wird
    // der gespeicherte Spaltenindex benutzt, sonst klebte jede Zeichnung im
    // leeren Raum an der letzten Kerze.
    const i = indexFuerTs(candles, ts);
    if (i !== null && i < total) return xk(i - Math.max(0, offset));
    return x(vorn + (idx ?? total) - Math.max(0, offset));
  };
  const malen = (d, stift) => {
    const wz = WERKZEUGE[d.typ]; if (!wz?.male) return;
    const pix = d.punkte.map((pt) => ({ x: zeitZuX(pt.ts, pt.index), y: y(pt.preis) }));
    if (pix.some((q) => !Number.isFinite(q.x) || !Number.isFinite(q.y))) return;
    ctx.save();
    ctx.lineCap = "butt"; ctx.lineJoin = "miter"; ctx.setLineDash([]);
    try { wz.male(ctx, pix, stift, { pL, pR, pT, pB, preisText: fmt }, d); } catch { /* eine kaputte Zeichnung darf den Chart nicht nehmen */ }
    ctx.restore();
  };
  ctx.save();
  ctx.beginPath(); ctx.rect(pL, pT, pR - pL, pB - pT); ctx.clip();
  for (const d of opts.zeichnungen ?? []) malen(d, { farbe: d.farbe ?? "#f59e0b", dicke: d.dicke ?? 1.4 });
  // Der angefangene Zug als Vorschau: halb durchsichtig, damit man sieht,
  // dass er noch nicht sitzt.
  if (opts.angefangen?.punkte?.length) {
    const a = opts.angefangen;
    const wz = WERKZEUGE[a.typ];
    const genug = wz?.punkte === 0 ? a.punkte.length > 1 : a.punkte.length >= (wz?.punkte ?? 2);
    ctx.globalAlpha = 0.55;
    if (genug || wz?.punkte === 0) malen({ ...a, punkte: a.punkte }, { ...(opts.stift ?? {}), farbe: opts.stift?.farbe ?? "#f59e0b", dicke: opts.stift?.dicke ?? 1.4 });
    // Gesetzte Punkte zeigen, auch wenn der Zug noch nicht vollstaendig ist.
    ctx.globalAlpha = 1;
    ctx.fillStyle = opts.stift?.farbe ?? "#f59e0b";
    for (const pt of a.punkte) {
      const qx = zeitZuX(pt.ts, pt.index), qy = y(pt.preis);
      ctx.beginPath(); ctx.arc(qx, qy, 3, 0, 7); ctx.fill();
    }
  }
  ctx.restore();

  /* ---- Positionslinien ---- */
  const boxes = [];
  if (on("positionen")) for (const line of opts.lines ?? []) {
    if (line.price < lo || line.price > hi) continue;
    const py = Math.round(y(line.price)) + 0.5;
    ctx.save(); ctx.setLineDash(line.dash ?? [6, 4]); ctx.strokeStyle = line.colour; ctx.lineWidth = line.width ?? 1.5;
    ctx.beginPath(); ctx.moveTo(pL, py); ctx.lineTo(pR, py); ctx.stroke(); ctx.restore();
    boxes.push({ y: py, label: line.label, colour: line.colour, id: line.id, closable: line.closable });
  }

  /* ---- Zeitachse ---- */
  ctx.fillStyle = c.ink3; ctx.textAlign = "center"; ctx.textBaseline = "top";
  const every = Math.max(1, Math.round(96 / slot));
  for (let i = 0; i < shown.length; i += every) {
    const d = new Date(shown[i].ts);
    ctx.fillText(`${d.getDate()}.${d.getMonth() + 1} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`, xk(i), pB + 6);
  }

  /* ---- Letzter Preis ---- */
  // Immer der ECHTE Schluss, auch unter Heikin-Ashi oder Prozent-Skala.
  const lpy = Math.round(y(lastClose)) + 0.5;
  const lpFarbe = lastClose >= shown[shown.length - 1].open ? c.long : c.short;
  ctx.fillStyle = lpFarbe;
  ctx.fillRect(pR + 2, lpy - 9, PAD.right - 6, 18);
  ctx.fillStyle = "#04120a"; ctx.textAlign = "left"; ctx.textBaseline = "middle";
  ctx.fillText(fmt(lastClose), pR + 8, lpy);
  // Countdown bis Kerzenschluss: der Bot entscheidet genau dann.
  const rest = ansicht.countdown !== false && opts.schlussBei ? countdownText(opts.schlussBei - Date.now()) : null;
  if (rest && end >= total) {
    ctx.fillStyle = c.raised; ctx.fillRect(pR + 2, lpy + 9, PAD.right - 6, 15);
    ctx.fillStyle = c.ink2; ctx.font = `10px ${c.mono}`;
    ctx.fillText(rest, pR + 8, lpy + 17);
    ctx.font = '11px ui-monospace, "Cascadia Mono", Menlo, monospace';
  }

  /* ---- Fadenkreuz ---- */
  // `hover.y === null` heisst: nur die senkrechte Linie (gekoppeltes
  // Fadenkreuz im Mehrfach-Layout -- dort kennt der Nachbar die Zeit, nicht
  // den Preis).
  let hoverKi = null;
  if (opts.hover) {
    const hx = opts.hover.x, hy = opts.hover.y;
    ctx.save(); ctx.setLineDash([3, 3]); ctx.strokeStyle = c.ink3;
    ctx.beginPath(); ctx.moveTo(hx + 0.5, pT); ctx.lineTo(hx + 0.5, H - PAD.bottom);
    if (hy !== null && hy !== undefined) { ctx.moveTo(pL, hy + 0.5); ctx.lineTo(pR, hy + 0.5); }
    ctx.stroke();
    ctx.restore();
    if (hy !== null && hy !== undefined && hy >= pT && hy <= pB) {
      const price = sk.preisBei(hy);
      ctx.fillStyle = c.surface; ctx.fillRect(pR + 2, hy - 9, PAD.right - 6, 18);
      ctx.fillStyle = c.ink; ctx.textAlign = "left"; ctx.textBaseline = "middle";
      ctx.fillText(achsenText(price, skala.modus, basis, fmt), pR + 8, hy);
    }
    // Zeitmarke auf der Zeitachse.
    const spalte = Math.floor((hx - pL) / slot);
    const ki = spalte - vorn;
    if (ki >= 0 && ki < shown.length) {
      hoverKi = ki;
      const takt = shown.length > 1 ? shown[1].ts - shown[0].ts : 900000;
      const text = zeitText(shown[ki].ts, takt);
      ctx.font = `10.5px ${c.mono}`;
      const w = ctx.measureText(text).width + 12;
      const bx = Math.max(pL, Math.min(pR - w, hx - w / 2));
      ctx.fillStyle = c.surface; ctx.fillRect(bx, H - PAD.bottom + 2, w, 17);
      ctx.fillStyle = c.ink; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(text, bx + w / 2, H - PAD.bottom + 11);
      ctx.font = '11px ui-monospace, "Cascadia Mono", Menlo, monospace';
    }
  }
  // Legendenwerte am Fadenkreuz statt am Ende (TradingViews Datenfenster):
  // `wertBei` liest denselben Index, an dem die Ablesung oben steht.
  const hoverJ = hoverKi === null ? null : Math.max(0, offset) + hoverKi;

  /* ---- Unterachsen: RSI, MACD, Stochastik, ATR, Volumen ---- */
  let paneY = pB + PANE_LUFT;
  for (let n = 0; n < aktivePanes.length; n++) {
    const eintrag = aktivePanes[n], def = INDIKATOREN[eintrag.art];
    const h = paneHoehen[n], oben = paneY, unten = paneY + h;
    paneY = unten + PANE_LUFT;
    if (unten > H - 4) break;                      // kein Zeichnen ins Nichts

    let serien;
    try { serien = def.rechne(candles, eintrag); } catch { continue; }
    const sichtbar = [];
    for (const sr of serien) {
      for (let i = 0; i < shown.length; i++) {
        const v = sr.werte?.[Math.max(0, offset) + i];
        if (v != null && Number.isFinite(v)) sichtbar.push(v);
      }
    }
    if (!sichtbar.length) continue;
    // Die Skala der Achse: fest, wenn der Indikator eine hat (RSI 0-100),
    // sonst aus den SICHTBAREN Werten -- nicht aus allen, sonst staucht ein
    // alter Ausreisser die ganze Achse flach.
    let pLo, pHi;
    if (def.skala) { [pLo, pHi] = def.skala; }
    else {
      pLo = Math.min(...sichtbar, ...(def.marken ?? []));
      pHi = Math.max(...sichtbar, ...(def.marken ?? []));
      const luft = (pHi - pLo) * 0.1 || 1; pLo -= luft; pHi += luft;
    }
    const pSpan = (pHi - pLo) || 1;
    const yy = (v) => unten - ((v - pLo) / pSpan) * h;

    ctx.save();
    ctx.strokeStyle = c.rule; ctx.lineWidth = 1;
    ctx.strokeRect(pL + 0.5, oben + 0.5, pR - pL, h);
    ctx.setLineDash([2, 4]);
    for (const marke of def.marken ?? []) {
      if (marke < pLo || marke > pHi) continue;
      const my = Math.round(yy(marke)) + 0.5;
      ctx.beginPath(); ctx.moveTo(pL, my); ctx.lineTo(pR, my); ctx.stroke();
      ctx.fillStyle = c.ink3; ctx.textAlign = "left"; ctx.textBaseline = "middle";
      ctx.fillText(String(marke), pR + 6, my);
    }
    ctx.restore();

    for (const sr of serien) {
      const farbe = sr.farbe ?? eintrag.farbe ?? "#94a3b8";
      if (sr.art === "balken") {
        ctx.save();
        const nullY = Math.max(oben, Math.min(unten, yy(Math.max(pLo, Math.min(pHi, 0)))));
        for (let i = 0; i < shown.length; i++) {
          const j = Math.max(0, offset) + i, v = sr.werte[j];
          if (v == null || !Number.isFinite(v)) continue;
          // Volumenbalken nehmen die Farbe ihrer Kerze -- so liest man
          // Kaufdruck ohne eine zweite Legende.
          ctx.fillStyle = sr.nachKerze
            ? (candles[j].close >= candles[j].open ? `${c.long}66` : `${c.short}66`)
            : (v >= 0 ? `${c.long}99` : `${c.short}99`);
          const vy = yy(v);
          ctx.fillRect(xk(i) - body / 2, Math.min(vy, nullY), Math.max(1, body), Math.max(1, Math.abs(vy - nullY)));
        }
        ctx.restore();
      } else {
        zeichneSerie(sr.werte, yy, { farbe, dash: sr.dash ?? [], dick: sr.dick ?? 1.2 });
      }
      if (sr.label) {
        const reihe = sr.werte ?? [];
        legende.push({ label: sr.label, reihe, wert: reihe.filter((v) => v != null).pop(), farbe, pane: true });
      }
    }
    ctx.save();
    ctx.fillStyle = c.ink3; ctx.textAlign = "left"; ctx.textBaseline = "top";
    ctx.font = '10px ui-monospace, "Cascadia Mono", Menlo, monospace';
    ctx.fillText(def.name, pL + 5, oben + 4);
    ctx.restore();
  }

  // Werte am Fadenkreuz einsetzen; ohne Fadenkreuz bleibt der letzte Wert.
  for (const e of legende) {
    if (hoverJ !== null && e.reihe) { const v = e.reihe[hoverJ]; e.wert = v ?? null; }
    delete e.reihe;
  }
  if (opts.vergleich?.prozent != null) {
    legende.push({ label: opts.vergleich.label, wert: null, text: `${opts.vergleich.prozent >= 0 ? "+" : ""}${opts.vergleich.prozent.toFixed(2)}%`, farbe: "#c084fc" });
  }

  return { pL, pR, pT, pB, slot, x: xk, y, lo, hi, offset: Math.max(0, offset), vorn, end, total,
    count: shown.length, spalten, boxes, legende, visible, preisBei: sk.preisBei, hoverKi,
    W, H, padRechts: PAD.right };
}

function indexFuerTs(candles, ts) {
  if (!candles.length) return null;
  if (ts <= candles[0].ts) return 0;
  if (ts >= candles[candles.length - 1].ts) return candles.length - 1;
  let lo = 0, hi = candles.length - 1;
  while (lo < hi) { const m = (lo + hi) >> 1; if (candles[m].ts < ts) lo = m + 1; else hi = m; }
  return lo;
}

function naechsteBeruehrungen(view, band) {
  const mid = (band.high + band.low) / 2;
  let best = null;
  for (const l of view?.levels ?? []) {
    const d = Math.abs(l.price - mid);
    if (best === null || d < best.d) best = { d, touches: l.touches ?? 1 };
  }
  return Math.max(1, Math.min(5, best ? best.touches : 2));
}

function drawStars(ctx, x, y, n, c) {
  const size = 9, gap = 2, total = 5;
  const startX = x - total * (size + gap);
  for (let i = 0; i < total; i++) {
    ctx.fillStyle = i < n ? c.star : "rgba(255,255,255,0.18)";
    star(ctx, startX + i * (size + gap) + size / 2, y, size / 2);
  }
}
function star(ctx, cx, cy, r) {
  ctx.beginPath();
  for (let i = 0; i < 10; i++) {
    const rr = i % 2 === 0 ? r : r * 0.45;
    const a = -Math.PI / 2 + (i * Math.PI) / 5;
    const p = [cx + Math.cos(a) * rr, cy + Math.sin(a) * rr];
    if (i === 0) ctx.moveTo(p[0], p[1]); else ctx.lineTo(p[0], p[1]);
  }
  ctx.closePath(); ctx.fill();
}

/**
 * Das echte Volumenprofil: Umsatz je Preis aus jedem einzelnen Trade eines
 * abgeschlossenen Tages, mit Point of Control und Value Area.
 *
 * Zwei Dinge, die es von der Kerzen-Naeherung daneben unterscheiden:
 * die Koerbe haengen an der Preisgroessenordnung und nicht am Zoom (ein POC,
 * der sich beim Hineinzoomen verschiebt, ist keine Eigenschaft des Marktes),
 * und jeder Korb weiss, wer der Aggressor war.
 */
function drawEchtesProfil(ctx, p, g) {
  const koerbe = (p.koerbe ?? []).filter((k) => k.preis >= g.lo && k.preis <= g.hi);
  if (!koerbe.length) return;
  const max = Math.max(...koerbe.map((k) => k.volumen)) || 1;
  const breite = 86, x0 = g.pL;
  // Korbhoehe aus dem Preisabstand zweier Koerbe, nicht aus der Chartbreite:
  // so stossen die Balken aneinander, egal wie weit gezoomt ist.
  const schritt = koerbe.length > 1 ? Math.abs(g.y(koerbe[1].preis) - g.y(koerbe[0].preis)) : 3;
  const h = Math.max(1, schritt - 0.5);

  ctx.save();
  for (const k of koerbe) {
    const w = (k.volumen / max) * breite;
    const yy = g.y(k.preis) - h / 2;
    const inVA = k.preis >= p.val && k.preis <= p.vah;
    // Innerhalb der Value Area heller: dort lag die Mehrheit des Umsatzes.
    ctx.fillStyle = inVA ? "rgba(232,237,245,0.30)" : "rgba(232,237,245,0.12)";
    ctx.fillRect(x0, yy, w, h);
    // Der Kaeuferanteil als zweiter Balken darueber -- nicht daneben, sonst
    // liest man zwei Volumina statt einer Aufteilung.
    const anteil = k.volumen > 0 ? k.kaeufer / k.volumen : 0.5;
    ctx.fillStyle = anteil >= 0.5 ? "rgba(34,197,94,0.42)" : "rgba(239,68,68,0.42)";
    ctx.fillRect(x0, yy, w * Math.abs(anteil - 0.5) * 2, h);
  }
  // POC und die beiden Raender der Value Area, ueber die ganze Breite.
  const linie = (preis, farbe, dash, text) => {
    if (preis < g.lo || preis > g.hi) return;
    const yy = Math.round(g.y(preis)) + 0.5;
    ctx.strokeStyle = farbe; ctx.lineWidth = 1; ctx.setLineDash(dash);
    ctx.beginPath(); ctx.moveTo(g.pL, yy); ctx.lineTo(g.pR, yy); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = farbe; ctx.font = '9px ui-monospace, Menlo, monospace';
    ctx.textAlign = "left"; ctx.textBaseline = "bottom";
    ctx.fillText(text, g.pL + breite + 5, yy - 1);
  };
  linie(p.vah, "rgba(148,163,184,0.75)", [3, 3], "VAH");
  linie(p.val, "rgba(148,163,184,0.75)", [3, 3], "VAL");
  linie(p.poc, "#facc15", [], `VPOC ${p.tag}`);
  ctx.restore();
}


/* Grosse Trades: wo viel Nominal den Besitzer gewechselt hat, mit dem Betrag.
 *
 * Nicht „institutionelle Liquidität". Das Orderbuch ist anonym; wer hinter
 * einem Abschluss steht, steht in keinem öffentlichen Feld. Was hier steht,
 * ist der Betrag — und der ist gemessen.
 *
 * Die Schwelle kommt vom Server und ist das oberste Promille DIESES Tages,
 * nicht eine runde Zahl: auf BTC sind das 711'227 USD je Abschluss, auf einem
 * kleineren Markt entsprechend weniger. Eine feste Grenze hätte auf dem einen
 * Markt alles und auf dem anderen nichts gezeigt.
 *
 * Gezeichnet wird RECHTS, weil links das Volumenprofil steht. Beide gleichzeitig
 * auf derselben Seite wären zwei Balkenreihen übereinander, und man läse eine.
 */
function drawGrosseTrades(ctx, d, g) {
  const stufen = (d.stufen ?? []).filter((s) => s.preis >= g.lo && s.preis <= g.hi);
  if (!stufen.length) return;
  const max = Math.max(...stufen.map((s) => s.usd)) || 1;
  // Hoechstens ein Fuenftel der Chartbreite. Fest 74 px waren auf einem
  // schmalen Fenster die halbe Zeichenflaeche, und die Kerzen verschwanden
  // hinter der Ebene, die sie erklaeren sollte.
  const breite = Math.min(74, (g.pR - g.pL) * 0.2), x1 = g.pR;
  // Die Balkenhoehe aus dem PREISABSTAND zweier benachbarter Stufen.
  //
  // Der Server liefert die Stufen nach Betrag sortiert, nicht nach Preis.
  // `stufen[0]` und `stufen[1]` sind also die zwei groessten, und ihr
  // Abstand ist beliebig: lagen sie zufaellig nebeneinander, kam eine Hoehe
  // von 2 px heraus, die Beschriftung fiel unter ihre Schwelle und die
  // ganze Ebene zeigte keine einzige Zahl -- gemessen am 21.10.2026 mit
  // vier Textpixeln im ganzen Streifen.
  const preise = stufen.map((s) => s.preis).sort((a, b) => a - b);
  let luecke = Infinity;
  for (let i = 1; i < preise.length; i++) luecke = Math.min(luecke, preise[i] - preise[i - 1]);
  const schritt = Number.isFinite(luecke) && luecke > 0
    ? Math.abs(g.y(g.lo) - g.y(g.lo + luecke)) : 10;
  const h = Math.max(2, Math.min(16, schritt - 1));

  ctx.save();
  ctx.font = '9px ui-monospace, Menlo, monospace';
  ctx.textBaseline = "middle";
  let beschriftet = 0;
  for (const s of stufen) {
    const w = (s.usd / max) * breite;
    const yy = g.y(s.preis);
    // Die Aufteilung der Aggressoren färbt den Balken. Bei exakt der Hälfte
    // grau: eine Stufe ohne Übergewicht als grün zu zeichnen wäre eine
    // Richtungsaussage, die die Zahl nicht hergibt.
    const anteil = s.usd > 0 ? s.kaeufer_usd / s.usd : 0.5;
    const ab = Math.abs(anteil - 0.5);
    // Durchscheinend. Diese Ebene erklaert die Kerzen und darf sie nicht
    // zudecken: bei 0.8 Deckkraft stand sie wie eine Wand davor.
    ctx.fillStyle = ab < 0.05 ? "rgba(148,163,184,0.26)"
      : anteil > 0.5 ? `rgba(34,197,94,${0.20 + ab * 0.4})` : `rgba(239,68,68,${0.20 + ab * 0.4})`;
    ctx.fillRect(x1 - w, yy - h / 2, w, h);
    // Der Betrag INNERHALB des Balkens, rechtsbuendig. Links davon stand er
    // mitten im Kursverlauf und las sich wie eine Beschriftung der Kerzen.
    const txt = s.usd >= 1e9 ? `${(s.usd / 1e9).toFixed(1)} Mrd`
      : s.usd >= 1e6 ? `${Math.round(s.usd / 1e6)} Mio`
      : `${Math.round(s.usd / 1e3)} Tsd`;
    // Die Beschriftung LINKS vom Balken, mit dunkler Unterlage.
    //
    // Nicht im Balken: die Verteilung ist langschwänzig -- die grösste Stufe
    // war am 21.10. das Zehnfache der übrigen, also blieben für alle anderen
    // 2 bis 10 px, und keine einzige Zahl passte hinein. Den Balken dafür
    // logarithmisch zu stauchen hätte die Zahlen lesbar gemacht und die
    // Längen zur Lüge: ein Balken, der zehnmal so viel Umsatz zeigt, muss
    // zehnmal so lang sein.
    //
    // Nur die sechs grössten, sonst überschreiben sich die Zeilen.
    if (h >= 7 && beschriftet < 6) {
      beschriftet++;
      const tw = ctx.measureText(txt).width;
      ctx.fillStyle = "rgba(7,9,13,0.78)";
      ctx.fillRect(x1 - w - tw - 9, yy - 6, tw + 7, 12);
      ctx.fillStyle = "rgba(232,237,245,0.96)";
      ctx.textAlign = "right";
      ctx.fillText(txt, x1 - w - 5, yy);
    }
  }
  // Kopfzeile: woher, wie viel, ab wann. Ohne sie ist eine Balkenreihe am
  // Rand eine Behauptung.
  // UNTEN rechts, nicht oben: oben steht die Indikatorlegende, und die
  // Kopfzeile lief quer darueber.
  const kopf = `grosse Trades ${d.tag} · ab ${Math.round(d.schwelle_usd / 1e3)} Tsd · `
    + `${d.anzahl} Stück · ${d.anteil_umsatz.toFixed(1)} % des Umsatzes`;
  ctx.fillStyle = "rgba(154,167,187,0.9)";
  ctx.textAlign = "right"; ctx.textBaseline = "bottom";
  ctx.fillText(kopf, x1 - 2, g.pB - 3);
  ctx.restore();
}

/* Options-Strikes: waagrechte Linien dort, wo Gamma-Last hängt.
 *
 * Keine GEX-Linie, und das ist keine Sparmassnahme. Gamma Exposure braucht
 * ein Vorzeichen — welche Seite die Händler halten —, und das steht in keinen
 * öffentlichen Daten. Auf BTC macht die Konvention den Unterschied zwischen
 * 571 und 181 Mio USD je 1 %: sie entscheidet über zwei Drittel der Zahl.
 * Hier steht darum nur der BETRAG, und die Linien tragen keine Richtung.
 *
 * Gezeichnet wird Gamma, nicht offenes Interesse. Reines OI täuscht: die
 * grössten Positionen liegen weit aus dem Geld und bewegen fast nichts — der
 * 60'000er Put auf BTC trägt 10'955 Kontrakte und bei einem Spot von 84'500
 * ein Gamma nahe null. Was hier oben steht, steht am Geld.
 */
function drawOptionen(ctx, o, g) {
  const zeilen = (o.strikes ?? []).filter((z) => z.strike >= g.lo && z.strike <= g.hi);
  if (!zeilen.length) return;
  const max = Math.max(...zeilen.map((z) => z.gamma_usd)) || 1;

  ctx.save();
  ctx.font = '9px ui-monospace, Menlo, monospace';
  ctx.textBaseline = "middle";
  for (const z of zeilen) {
    const anteil = z.gamma_usd / max;
    const yy = Math.round(g.y(z.strike)) + 0.5;
    // Violett, weil im Chart keine andere Ebene diese Farbe trägt: eine
    // Options-Linie darf nicht wie ein Kursniveau aussehen.
    ctx.strokeStyle = `rgba(167,139,250,${0.25 + anteil * 0.55})`;
    ctx.lineWidth = anteil > 0.6 ? 1.6 : 1;
    ctx.setLineDash([2, 4]);
    ctx.beginPath(); ctx.moveTo(g.pL, yy); ctx.lineTo(g.pR, yy); ctx.stroke();
    ctx.setLineDash([]);

    // Beschriftung links, damit sie nicht mit den grossen Trades rechts
    // kollidiert. Nur, wo die Linie kräftig genug ist, um sie zu verdienen.
    if (anteil >= 0.45) {
      const txt = `${Math.round(z.strike).toLocaleString("de-CH")} · `
        + `${(z.gamma_usd / 1e6).toFixed(1)} Mio/1 %`;
      const tw = ctx.measureText(txt).width;
      ctx.fillStyle = "rgba(7,9,13,0.8)";
      ctx.fillRect(g.pL + 2, yy - 6, tw + 6, 12);
      ctx.fillStyle = "rgba(196,181,253,0.95)";
      ctx.textAlign = "left";
      ctx.fillText(txt, g.pL + 5, yy);
    }
  }
  // UNTEN links. Oben steht die Indikatorlegende, und die Kopfzeile lief quer
  // darueber -- derselbe Fehler wie zuvor bei den grossen Trades, zwei Stunden
  // spaeter noch einmal gemacht.
  ctx.fillStyle = "rgba(167,139,250,0.75)";
  ctx.textAlign = "left"; ctx.textBaseline = "bottom";
  ctx.fillText(
    `${o.waehrung}-Optionen · Gamma-Last, Betrag ohne Vorzeichen · C/P ${o.call_put_oi.toFixed(2)}`,
    g.pL + 2, g.pB - 3);
  ctx.restore();
}

function drawProfile(ctx, candles, g) {
  const bins = 48, hist = new Array(bins).fill(0);
  for (const k of candles) {
    const i = Math.max(0, Math.min(bins - 1, Math.floor((((k.high + k.low) / 2 - g.lo) / (g.hi - g.lo)) * bins)));
    hist[i] += k.volume ?? 0;
  }
  const max = Math.max(...hist) || 1, width = 52;
  // Die Zeile mit dem meisten Volumen. "Point of Control" heisst sie erst,
  // wenn sie aus echten Trades je Preis kommt -- was hier gerechnet wird, ist
  // eine NAEHERUNG aus Kerzen, und die verteilt das ganze Volumen einer Kerze
  // auf ihren Mittelpreis.
  //
  // Hier stand "und damit der staerkste Magnet". Das war eine
  // Signalbehauptung ohne Beleg, geschrieben von mir am 20.10.2026 und am
  // 21.10. in der Datenrecherche aufgefallen. Diese Ebene sagt "hier lag
  // Umsatz" und sonst nichts.
  const poc = hist.indexOf(max);
  ctx.save();
  for (let i = 0; i < bins; i++) {
    const h = (g.pB - g.pT) / bins;
    const yy = g.y(g.lo + ((i + 0.5) / bins) * (g.hi - g.lo)) - h / 2;
    ctx.fillStyle = i === poc ? "rgba(250,204,21,0.45)" : "rgba(232,237,245,0.14)";
    ctx.fillRect(g.pL, yy, (hist[i] / max) * width, Math.max(1, h - 1));
  }
  ctx.restore();
}

/**
 * Ruhende Liquiditaet aus dem Orderbuch, als Streifen am rechten Rand.
 *
 * Kein Bookmap ueber die Zeit -- dafuer muesste die x-Achse Sekunden sein,
 * und sie zeigt Kerzen. Was hier steht, ist der AKTUELLE Zustand: wo liegen
 * die Waende. Das ist die Frage, die ein Stop oder ein Ziel beantwortet
 * haben will, und sie ist mit einem Schnappschuss ehrlich zu beantworten.
 */
function drawHeatmap(ctx, heat, g) {
  const koerbe = heat.bins ?? [];
  if (!koerbe.length) return;

  // **Die Koerbe werden auf die PIXEL gerechnet, nicht auf den Preis.** Der
  // Server buendelt in 60 Koerbe ueber die Buchspanne; wie hoch die auf dem
  // Schirm ist, haengt am Zoom. Bei 2'400 USD Chart und 260 USD Buch sind das
  // 33 Pixel -- 60 Koerbe darin sind ein halber Pixel hoch und mit Alpha 0.10
  // ueber vollfarbigen Kerzen schlicht unsichtbar. Also: so viele Zeilen wie
  // Platz ist, mindestens 3 Pixel hoch.
  const yLo = g.y(Math.max(heat.low, g.lo)), yHi = g.y(Math.min(heat.high, g.hi));
  const bandH = Math.abs(yLo - yHi);
  if (bandH < 2) return;
  const zeilen = Math.max(4, Math.min(koerbe.length, Math.floor(bandH / 3)));
  const oben = Math.min(yLo, yHi), hoehe = bandH / zeilen;

  const topf = Array.from({ length: zeilen }, () => [0, 0]);  // [Gebote, Briefe]
  for (const [preis, menge, seite] of koerbe) {
    if (preis < g.lo || preis > g.hi) continue;
    const i = Math.max(0, Math.min(zeilen - 1, Math.floor((g.y(preis) - oben) / hoehe)));
    topf[i][seite > 0 ? 0 : 1] += menge;
  }
  const max = Math.max(...topf.map(([b, a]) => Math.max(b, a)), 1e-9);
  const breite = 46, x0 = g.pR - breite;

  ctx.save();
  // Eigene Spur mit dunklem Grund: sonst mischt sich jeder Streifen mit der
  // Kerze darunter und man liest die Kerzenfarbe als Buchtiefe.
  ctx.fillStyle = "rgba(8,11,16,0.82)";
  ctx.fillRect(x0, oben, breite, bandH);
  for (let i = 0; i < zeilen; i++) {
    const [gebote, briefe] = topf[i];
    const menge = Math.max(gebote, briefe);
    if (menge <= 0) continue;
    const stark = Math.min(1, menge / max);
    ctx.fillStyle = gebote >= briefe
      ? `rgba(34,197,94,${0.22 + stark * 0.68})`
      : `rgba(239,68,68,${0.22 + stark * 0.68})`;
    ctx.fillRect(x0, oben + i * hoehe, breite * (0.18 + stark * 0.82), Math.max(1, hoehe - 0.5));
  }
  // Wo das Buch ueberhaupt reicht -- sonst liest man die leere Flaeche
  // darueber und darunter als "keine Liquiditaet" statt als "nicht gemessen".
  ctx.strokeStyle = "rgba(250,204,21,0.45)";
  ctx.lineWidth = 1; ctx.setLineDash([2, 3]);
  ctx.beginPath(); ctx.moveTo(x0, oben + 0.5); ctx.lineTo(g.pR, oben + 0.5);
  ctx.moveTo(x0, oben + bandH - 0.5); ctx.lineTo(g.pR, oben + bandH - 0.5); ctx.stroke();
  ctx.setLineDash([]);
  ctx.restore();
}

function niceStep(span, target) {
  const raw = span / target, mag = Math.pow(10, Math.floor(Math.log10(raw))), n = raw / mag;
  return (n < 1.5 ? 1 : n < 3.5 ? 2 : n < 7.5 ? 5 : 10) * mag;
}

/* ------------------------------------------------- Kurven (Konto, Verlauf) -- */
function lineChart(canvas, series, { yOf, label, colour, grid, axis, zero }) {
  const ratio = window.devicePixelRatio || 1;
  const W = canvas.clientWidth, H = canvas.clientHeight;
  if (!W || !H || !series.length) return;
  if (canvas.width !== W * ratio || canvas.height !== H * ratio) { canvas.width = W * ratio; canvas.height = H * ratio; }
  const ctx = canvas.getContext("2d"); ctx.setTransform(ratio, 0, 0, ratio, 0, 0); ctx.clearRect(0, 0, W, H);
  const pL = 52, pR = W - 16, pT = 16, pB = H - 36;
  const vals = series.map(yOf);
  let lo = Math.min(...vals, zero ? 0 : Infinity), hi = Math.max(...vals, zero ? 0 : -Infinity);
  if (hi - lo < 1e-9) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.1; lo -= pad; hi += pad;
  const y = (v) => pB - ((v - lo) / (hi - lo)) * (pB - pT);
  const x = (i) => pL + (i / Math.max(1, series.length - 1)) * (pR - pL);
  ctx.font = "12px system-ui, sans-serif"; ctx.textBaseline = "middle"; ctx.textAlign = "right";
  const step = niceStep(hi - lo, 5);
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
    const py = Math.round(y(v)) + 0.5;
    ctx.strokeStyle = grid; ctx.setLineDash([2, 3]); ctx.beginPath(); ctx.moveTo(pL, py); ctx.lineTo(pR, py); ctx.stroke();
    ctx.fillStyle = axis; ctx.fillText(v.toLocaleString("de-CH", { maximumFractionDigits: 2 }), pL - 8, py);
  }
  ctx.setLineDash([]);
  if (zero) { const z = Math.round(y(0)) + 0.5; ctx.strokeStyle = axis; ctx.beginPath(); ctx.moveTo(pL, z); ctx.lineTo(pR, z); ctx.stroke(); }
  ctx.strokeStyle = colour; ctx.lineWidth = 2.2; ctx.beginPath();
  series.forEach((p, i) => { const px = x(i), py = y(yOf(p)); if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py); });
  ctx.stroke();
  ctx.fillStyle = colour;
  if (series.length <= 80) series.forEach((p, i) => { ctx.beginPath(); ctx.arc(x(i), y(yOf(p)), 3.2, 0, Math.PI * 2); ctx.fill(); });
  ctx.fillStyle = axis; ctx.textAlign = "center"; ctx.textBaseline = "top";
  const every = Math.max(1, Math.round(series.length / 6));
  series.forEach((p, i) => { if (i % every !== 0 && i !== series.length - 1) return; ctx.fillText(label(p), x(i), pB + 8); });
}

export function drawEquity(canvas, series, range) {
  lineChart(canvas, series, {
    yOf: (p) => p.equity, colour: "#1d4ed8", grid: "#dbeafe", axis: "#2563eb", zero: false,
    label: (p) => { const d = new Date(p.ts); return range === "today" ? `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}` : `${d.getDate()}.${d.getMonth() + 1}.`; },
  });
}

export function drawRCurve(canvas, points) {
  lineChart(canvas, points, {
    yOf: (p) => p.cumulative_r, colour: cssVar("--long") || "#22c55e", grid: cssVar("--rule") || "#1f2733",
    axis: cssVar("--ink-3") || "#6b7789", zero: true,
    label: (p) => { const d = new Date(p.ts); return `${d.getDate()}.${d.getMonth() + 1}. ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; },
  });
}
