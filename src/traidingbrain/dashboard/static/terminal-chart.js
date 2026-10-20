/**
 * Der Chart des Darkwood Terminals -- nach der Vorlage vom 20.10.2026.
 *
 * Was die Vorlage zeigt und was hier gezeichnet wird:
 *   - Kerzen, Gruen/Rot.
 *   - EMA 20 und EMA 200 als gestrichelte Linien mit Beschriftung links oben.
 *     Beide werden HIER aus den Kerzen gerechnet, nicht vom Server geholt;
 *     dafuer fragt der Client genug Kerzen an (400).
 *   - Zonen als farbige Flaechen (hellblau unten, rosa oben) mit Sternen.
 *     Quelle: `bands` der Marktansicht (gleiche Hochs/Tiefs, Angebot/Nachfrage,
 *     Orderbloecke, FVGs). Die Sterne sind die Beruehrungen des naechsten
 *     Levels derselben Art -- ein Mass, kein Urteil.
 *   - Stop und Ziel offener Positionen als Linien mit dem USD-Betrag.
 *   - Ein Volumenprofil links als Kurve (Volumen je Preisstufe).
 *   - Ein orangener Rahmen um die Signalkerze, wenn ein Setup vorliegt.
 */

const PAD = { left: 56, right: 92, top: 14, bottom: 26 };

export function ema(values, n) {
  const k = 2 / (n + 1);
  const out = new Array(values.length).fill(null);
  let acc = null;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    acc = acc === null ? v : v * k + acc * (1 - k);
    if (i >= n - 1) out[i] = acc;
  }
  return out;
}

function fmt(p) {
  if (p >= 1000) return p.toLocaleString("de-CH", { maximumFractionDigits: 1 });
  if (p >= 10) return p.toFixed(2);
  return p.toFixed(4);
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function drawTerminalChart(canvas, view, opts) {
  const ratio = window.devicePixelRatio || 1;
  const W = canvas.clientWidth;
  const H = canvas.clientHeight;
  if (!W || !H || !view || !view.candles?.length) return null;
  if (canvas.width !== W * ratio || canvas.height !== H * ratio) {
    canvas.width = W * ratio;
    canvas.height = H * ratio;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, W, H);

  const c = {
    rule: cssVar("--rule"), rule2: cssVar("--rule-2"), ink: cssVar("--ink"), ink2: cssVar("--ink-2"),
    ink3: cssVar("--ink-3"), long: cssVar("--long"), short: cssVar("--short"), star: cssVar("--star"),
    mark: cssVar("--mark"), surface: cssVar("--surface"),
  };

  const candles = view.candles;
  const shown = opts?.visible ? candles.slice(-opts.visible) : candles.slice(-Math.max(60, Math.floor((W - PAD.left - PAD.right) / 7)));
  const offset = candles.length - shown.length;
  const pL = PAD.left, pR = W - PAD.right, pT = PAD.top, pB = H - PAD.bottom;
  const pW = pR - pL, pH = pB - pT;

  let lo = Math.min(...shown.map((k) => k.low));
  let hi = Math.max(...shown.map((k) => k.high));
  for (const line of opts?.lines ?? []) { lo = Math.min(lo, line.price); hi = Math.max(hi, line.price); }
  const padP = (hi - lo) * 0.06 || 1;
  lo -= padP; hi += padP;
  const span = hi - lo;
  const y = (p) => pB - ((p - lo) / span) * pH;
  const slot = pW / shown.length;
  const x = (i) => pL + slot * (i + 0.5);
  const body = Math.max(2, Math.floor(slot * 0.66));

  /* Raster + Preisachse */
  ctx.font = '11px ui-monospace, "Cascadia Mono", Menlo, monospace';
  ctx.textBaseline = "middle";
  const step = niceStep(span, 6);
  for (let p = Math.ceil(lo / step) * step; p <= hi; p += step) {
    const py = Math.round(y(p)) + 0.5;
    ctx.strokeStyle = c.rule; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(pL, py); ctx.lineTo(pR, py); ctx.stroke();
    ctx.fillStyle = c.ink3; ctx.textAlign = "left";
    ctx.fillText(fmt(p), pR + 8, py);
  }

  /* Zonen (Flaechen) mit Sternen */
  const lastClose = shown[shown.length - 1].close;
  const stars = [];
  for (const b of view.bands ?? []) {
    if (b.high < lo || b.low > hi) continue;
    const top = y(b.high), bottom = y(b.low);
    const above = (b.high + b.low) / 2 > lastClose;
    ctx.fillStyle = above ? cssVar("--zone-hi") : cssVar("--zone-lo");
    ctx.fillRect(pL, top, pW, Math.max(2, bottom - top));
    const touches = nearestTouches(view, b);
    stars.push({ x: pR - 8, y: top + 10, n: touches, align: "right" });
  }
  for (const s of stars) drawStars(ctx, s.x, s.y, s.n, c, s.align);

  /* Volumenprofil links */
  drawProfile(ctx, shown, { pL, pT, pB, y, lo, hi }, c);

  /* EMAs */
  const closes = candles.map((k) => k.close);
  const e20 = ema(closes, 20), e200 = ema(closes, 200);
  const drawLine = (series, colour, dash) => {
    ctx.save(); ctx.setLineDash(dash); ctx.strokeStyle = colour; ctx.lineWidth = 1.2;
    ctx.beginPath(); let started = false;
    for (let i = 0; i < shown.length; i++) {
      const v = series[offset + i]; if (v === null || v === undefined) continue;
      const px = x(i), py = y(v);
      if (!started) { ctx.moveTo(px, py); started = true; } else ctx.lineTo(px, py);
    }
    ctx.stroke(); ctx.restore();
  };
  if (opts?.indicators !== false) {
    drawLine(e200, c.short, [5, 4]);
    drawLine(e20, "#60a5fa", [3, 3]);
  }

  /* Kerzen */
  for (let i = 0; i < shown.length; i++) {
    const k = shown[i];
    const up = k.close >= k.open;
    const col = up ? c.long : c.short;
    const px = Math.round(x(i));
    ctx.strokeStyle = col; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(px + 0.5, y(k.high)); ctx.lineTo(px + 0.5, y(k.low)); ctx.stroke();
    const t = y(Math.max(k.open, k.close)), bt = y(Math.min(k.open, k.close));
    ctx.fillStyle = col;
    ctx.fillRect(px - body / 2, t, body, Math.max(1, bt - t));
  }

  /* Signalkerze: orangener Rahmen */
  if (opts?.signalIndex !== undefined && opts.signalIndex >= offset) {
    const i = opts.signalIndex - offset; const k = shown[i];
    if (k) {
      ctx.strokeStyle = c.mark; ctx.lineWidth = 1.5;
      ctx.strokeRect(x(i) - body / 2 - 4, y(k.high) - 4, body + 8, y(k.low) - y(k.high) + 8);
    }
  }

  /* Linien: Stop / Ziel / Einstieg offener Positionen, Zeichnungen */
  const boxes = [];
  for (const line of opts?.lines ?? []) {
    const py = Math.round(y(line.price)) + 0.5;
    ctx.save(); ctx.setLineDash(line.dash ?? [6, 4]); ctx.strokeStyle = line.colour; ctx.lineWidth = line.width ?? 1.5;
    ctx.beginPath(); ctx.moveTo(pL, py); ctx.lineTo(pR, py); ctx.stroke(); ctx.restore();
    boxes.push({ y: py, label: line.label, colour: line.colour, id: line.id, closable: line.closable });
  }

  /* Zeitachse */
  ctx.fillStyle = c.ink3; ctx.textAlign = "center"; ctx.textBaseline = "top";
  // Beschriftung nach PIXELN, nicht nach Kerzenzahl: bei 400 Kerzen auf einem
  // schmalen Fenster ueberlagerten sich sieben Zeitstempel zu einem Brei.
  // Alle ~96 px eine Marke, egal wie viele Kerzen dazwischen liegen.
  const every = Math.max(1, Math.round(96 / slot));
  for (let i = 0; i < shown.length; i += every) {
    const d = new Date(shown[i].ts);
    ctx.fillText(`${d.getDate()}.${d.getMonth() + 1} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`, x(i), pB + 6);
  }

  /* Letzter Preis rechts */
  const lpy = Math.round(y(lastClose)) + 0.5;
  ctx.fillStyle = lastClose >= shown[shown.length - 1].open ? c.long : c.short;
  ctx.fillRect(pR + 2, lpy - 9, PAD.right - 6, 18);
  ctx.fillStyle = "#04120a"; ctx.textAlign = "left"; ctx.textBaseline = "middle";
  ctx.fillText(fmt(lastClose), pR + 8, lpy);

  /* Hover-Fadenkreuz */
  if (opts?.hover) {
    const hx = opts.hover.x, hy = opts.hover.y;
    ctx.save(); ctx.setLineDash([3, 3]); ctx.strokeStyle = c.ink3;
    ctx.beginPath(); ctx.moveTo(hx + 0.5, pT); ctx.lineTo(hx + 0.5, pB); ctx.moveTo(pL, hy + 0.5); ctx.lineTo(pR, hy + 0.5); ctx.stroke();
    ctx.restore();
    const price = lo + ((pB - hy) / pH) * span;
    ctx.fillStyle = c.surface; ctx.fillRect(pR + 2, hy - 9, PAD.right - 6, 18);
    ctx.fillStyle = c.ink; ctx.fillText(fmt(price), pR + 8, hy);
  }

  return { pL, pR, pT, pB, slot, x, y, lo, hi, offset, count: shown.length, boxes, e20: e20[e20.length - 1], e200: e200[e200.length - 1] };
}

function nearestTouches(view, band) {
  const mid = (band.high + band.low) / 2;
  let best = null;
  for (const l of view.levels ?? []) {
    const d = Math.abs(l.price - mid);
    if (best === null || d < best.d) best = { d, touches: l.touches ?? 1 };
  }
  return Math.max(1, Math.min(5, best ? best.touches : 2));
}

function drawStars(ctx, x, y, n, c, align) {
  const size = 9, gap = 2, total = 5;
  const startX = align === "right" ? x - total * (size + gap) : x;
  for (let i = 0; i < total; i++) {
    const cx = startX + i * (size + gap) + size / 2;
    ctx.fillStyle = i < n ? c.star : "rgba(255,255,255,0.18)";
    star(ctx, cx, y, size / 2);
  }
}

function star(ctx, cx, cy, r) {
  ctx.beginPath();
  for (let i = 0; i < 10; i++) {
    const rr = i % 2 === 0 ? r : r * 0.45;
    const a = -Math.PI / 2 + (i * Math.PI) / 5;
    const px = cx + Math.cos(a) * rr, py = cy + Math.sin(a) * rr;
    if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
  }
  ctx.closePath(); ctx.fill();
}

function drawProfile(ctx, candles, g, c) {
  const bins = 40;
  const hist = new Array(bins).fill(0);
  for (const k of candles) {
    const p = (k.high + k.low) / 2;
    const i = Math.max(0, Math.min(bins - 1, Math.floor(((p - g.lo) / (g.hi - g.lo)) * bins)));
    hist[i] += k.volume ?? 0;
  }
  const max = Math.max(...hist) || 1;
  const width = 48;
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(g.pL, g.pB);
  for (let i = 0; i < bins; i++) {
    const p = g.lo + ((i + 0.5) / bins) * (g.hi - g.lo);
    ctx.lineTo(g.pL + (hist[i] / max) * width, g.y(p));
  }
  ctx.lineTo(g.pL, g.pT);
  ctx.closePath();
  ctx.fillStyle = "rgba(232,237,245,0.08)";
  ctx.fill();
  ctx.strokeStyle = "rgba(232,237,245,0.35)"; ctx.lineWidth = 1; ctx.stroke();
  ctx.restore();
}

function niceStep(span, target) {
  const raw = span / target;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const n = raw / mag;
  const nice = n < 1.5 ? 1 : n < 3.5 ? 2 : n < 7.5 ? 5 : 10;
  return nice * mag;
}

export function drawEquity(canvas, series, range) {
  const ratio = window.devicePixelRatio || 1;
  const W = canvas.clientWidth, H = canvas.clientHeight;
  if (!W || !H) return;
  if (canvas.width !== W * ratio || canvas.height !== H * ratio) { canvas.width = W * ratio; canvas.height = H * ratio; }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const pL = 48, pR = W - 16, pT = 16, pB = H - 36;
  const vals = series.map((p) => p.equity);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < 1) { lo -= 5; hi += 5; }
  const pad = (hi - lo) * 0.1; lo -= pad; hi += pad;
  const y = (v) => pB - ((v - lo) / (hi - lo)) * (pB - pT);
  const x = (i) => pL + (i / Math.max(1, series.length - 1)) * (pR - pL);
  ctx.font = "12px system-ui, sans-serif"; ctx.fillStyle = "#2563eb"; ctx.strokeStyle = "#dbeafe";
  const step = niceStep(hi - lo, 5);
  ctx.textBaseline = "middle"; ctx.textAlign = "right";
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
    const py = Math.round(y(v)) + 0.5;
    ctx.beginPath(); ctx.setLineDash([2, 3]); ctx.moveTo(pL, py); ctx.lineTo(pR, py); ctx.stroke();
    ctx.fillText(v.toLocaleString("de-CH", { maximumFractionDigits: 0 }), pL - 8, py);
  }
  ctx.setLineDash([]);
  ctx.strokeStyle = "#1d4ed8"; ctx.lineWidth = 2.2; ctx.beginPath();
  series.forEach((p, i) => { const px = x(i), py = y(p.equity); if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py); });
  ctx.stroke();
  ctx.fillStyle = "#1d4ed8";
  series.forEach((p, i) => { ctx.beginPath(); ctx.arc(x(i), y(p.equity), 3.5, 0, Math.PI * 2); ctx.fill(); });
  ctx.fillStyle = "#2563eb"; ctx.textAlign = "center"; ctx.textBaseline = "top";
  const every = Math.max(1, Math.round(series.length / 6));
  series.forEach((p, i) => {
    if (i % every !== 0 && i !== series.length - 1) return;
    const d = new Date(p.ts);
    const label = range === "today" ? `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}` : `${d.getDate()}.${d.getMonth() + 1}.`;
    ctx.fillText(label, x(i), pB + 8);
  });
}
