/* deliberate-ignore no-active-state -- diese Datei traegt keine Stile; `S.hover`
   ist der Fadenkreuz-Zustand des Charts. Alle :active-Zustaende stehen in
   terminal.css, je Knopf. */
/**
 * Darkwood Terminal -- der Controller.
 *
 * Vier Ansichten wie im alten Dashboard (Markt, Konto, Trades, Verlauf), jede
 * mit ihrem eigenen Platz. Alles liest ECHTE Daten; nichts hier erfindet eine
 * Zahl. Wo das Projekt eine Zahl noch nicht hat, steht das dabei.
 *
 * Takt: Kopfzeile und Orderbuch jede Sekunde, die FORMENDE Kerze alle zwei;
 * abgeschlossene Kerzen alle 15 s; Score alle 30 s; Kalender alle 15 min.
 * Der Punkt oben rechts blinkt bei jedem Tick und nennt die Uhrzeit des
 * letzten -- ein stehender Chart und ein toter Feed sehen sonst gleich aus.
 */
import { drawTerminalChart, drawEquity, drawRCurve, fmt, EBENEN } from "/static/terminal-chart.js";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const api = async (path, opts) => {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) { let msg = `${r.status}`; try { const j = await r.json(); msg = j.detail ?? JSON.stringify(j); } catch { /* text */ } throw new Error(msg); }
  return r.json();
};
const money = (v, d = 2) => (v ?? 0).toLocaleString("de-CH", { minimumFractionDigits: d, maximumFractionDigits: d });
const px = (v) => fmt(v ?? 0);
const signed = (v, d = 2) => (v >= 0 ? "+" : "") + money(v, d);
const pct = (v, d = 2) => (v >= 0 ? "+" : "") + (v ?? 0).toFixed(d) + "%";
const clock = (ts) => { const d = new Date(ts); return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`; };
const day = (ts) => { const d = new Date(ts); return `${d.getDate()}.${d.getMonth() + 1}. ${clock(ts).slice(0, 5)}`; };

const S = {
  symbol: "BTCUSDT", tf: "M15", view: "markt", center: "chart", mode: "bot", histSrc: "alle",
  market: null, live: null, head: null, score: null, positions: [], botPositions: [], history: [], calendar: null,
  settings: null, side: "long", indicators: true, hover: null, drawings: [], tool: "cross",
  alerts: JSON.parse(localStorage.getItem("dw-alerts") || "[]"), lastOb: null, range: "month", account: null,
  // Zoom JE SYMBOL UND ZEITEBENE. Vorher gab es einen gemeinsamen Zustand,
  // und wer BTC auf 400 Kerzen gezogen hatte, bekam ETH genauso duenn --
  // eine Einstellung, die fuer einen Markt gemacht war, galt fuer alle.
  zoomBy: {}, drag: null, curve: null, book: null, heat: null,
  ebenen: JSON.parse(localStorage.getItem("dw-ebenen") || "{}"),
};
function zoomKey() { return `${S.symbol}|${S.tf}`; }
function zoom() { return (S.zoomBy[zoomKey()] ??= { visible: null, end: null }); }
function zoomReset() { S.zoomBy[zoomKey()] = { visible: null, end: null }; }

/* Eine symbolgebundene Antwort kann nach dem Wechsel eintreffen -- sie gehoert
   dann zum alten Markt. BTCs Orderbuch als Heatmap unter ETH zieht die
   Preisachse auf 80'000 hoch und druckt die ETH-Kerzen zu einem Strich
   zusammen. Wer fragt, merkt sich den Markt und verwirft die Spaetzuendung. */
const VERALTET = Symbol("veraltet");
async function fuerMarkt(abruf) {
  const schluessel = zoomKey();
  const daten = await abruf(S.symbol, S.tf);
  return zoomKey() === schluessel ? daten : VERALTET;
}

/* ------------------------------------------------------------- Sterne -- */
function stars(n) {
  const tpl = $("#star-tpl").content;
  const wrap = document.createElement("span"); wrap.className = "stars"; wrap.setAttribute("aria-label", `${n} von 5 Sternen`);
  for (let i = 0; i < 5; i++) { const s = tpl.firstElementChild.cloneNode(true); if (i < n) s.classList.add("on"); wrap.appendChild(s); }
  return wrap.outerHTML;
}
function pulse() { const d = $("#live"); d.classList.remove("tick"); void d.offsetWidth; d.classList.add("tick"); $("#live-time").textContent = clock(Date.now()); }

/* ------------------------------------------------------------ Kopfzeile -- */
async function tickHead() {
  try {
    const kopf = await fuerMarkt((s) => api(`/api/terminal/head/${s}`));
    if (kopf === VERALTET) return;
    S.head = kopf;
    const h = S.head;
    $("#hd-price").textContent = px(h.last);
    const chg = $("#hd-chg"); chg.textContent = pct(h.change_pct); chg.className = `topbar__chg ${h.change_pct >= 0 ? "up" : "down"}`;
    $("#hd-meta").textContent = `H ${px(h.high)} · T ${px(h.low)} · Vol ${(h.quote_volume / 1e9).toFixed(2)}B${h.funding_rate !== null ? ` · Funding ${(h.funding_rate * 100).toFixed(4)}%` : ""}`;
    pulse(); updateManualSummary();
  } catch (e) { $("#hd-meta").textContent = `Kopfzeile: ${e.message}`; }
}

/* ------------------------------------------------------- Formende Kerze -- */
async function tickLive() {
  try {
    const kerze = await fuerMarkt((s, tf) => api(`/api/terminal/live-candle/${s}?tf=${tf}`));
    if (kerze === VERALTET) return;
    S.live = kerze;
    if (S.view === "markt" && S.center === "chart") renderChart();
  } catch (e) { /* alte Kerze bleibt */ }
}
function mergedCandles() {
  if (!S.market) return [];
  const base = S.market.candles, k = S.live;
  if (!k || k.symbol !== S.symbol || k.timeframe !== S.tf) return base;
  const last = base[base.length - 1];
  const live = { ts: k.ts, open: k.open, high: k.high, low: k.low, close: k.close, volume: k.volume };
  if (!last || k.ts > last.ts) return [...base, live];
  if (k.ts === last.ts) return [...base.slice(0, -1), live];
  return base;
}

/* ------------------------------------------------------------ Orderbuch -- */
async function tickBook() {
  if (S.view !== "markt") return;
  try {
    const ob = await fuerMarkt((s) => api(`/api/terminal/orderbook/${s}?depth=40`));
    if (ob === VERALTET) return;
    S.book = ob;
    const maxQ = Math.max(...ob.bids.slice(0, 12).map((b) => b[1]), ...ob.asks.slice(0, 12).map((a) => a[1]), 1e-9);
    $("#ob").innerHTML = ob.bids.slice(0, 12).map((b, i) => {
      const a = ob.asks[i] ?? [0, 0];
      const changed = S.lastOb && (S.lastOb.bids[i]?.[1] !== b[1] || S.lastOb.asks[i]?.[1] !== a[1]);
      return `<div class="ob__row${changed ? " flash" : ""}">
        <div class="ob__cell ob__bid" style="--w:${(b[1] / maxQ) * 100}%"><span>${px(b[0])} <small class="muted">${b[1].toFixed(3)}</small></span></div>
        <div class="ob__cell ob__ask" style="--w:${(a[1] / maxQ) * 100}%"><span><small class="muted">${a[1].toFixed(3)}</small> ${px(a[0])}</span></div></div>`;
    }).join("") + `<div class="ob__spread">Spread ${ob.spread_bp.toFixed(2)} bp</div>`;
    $("#ob-sum").innerHTML = `<span class="${ob.bid_share_pct >= 50 ? "up" : "down"}">${ob.bid_share_pct.toFixed(0)}%</span> <span class="muted">(${(Math.abs(ob.bid_share_pct - 50) * 2).toFixed(0)}%)</span>`;
    S.lastOb = ob;
    setTimeout(() => $$(".ob__row.flash").forEach((r) => r.classList.remove("flash")), 260);
  } catch (e) { $("#ob-sum").textContent = "–"; }
}

/* ---------------------------------------------------- Heatmap (tiefes Buch) -- */
// Getrennt von der Leiter oben: die zeigt den Spread und braucht Tempo, die
// Heatmap braucht TIEFE. Gemessen auf BTCUSDT decken 20 Zeilen 6 USD ab und
// 1000 Zeilen 262 -- bei rund 1'500 USD Charthoehe ist nur das zweite sichtbar.
// Darum seltener, dafuer tief, und serverseitig in 60 Koerbe gebuendelt.
async function tickHeatmap() {
  if (S.view !== "markt" || S.ebenen.heatmap === false) return;
  try {
    const h = await fuerMarkt((s) => api(`/api/terminal/heatmap/${s}?bins=60`));
    if (h === VERALTET) return;
    S.heat = h;
    if (S.center === "chart") renderChart();
  } catch (e) { /* alte Heatmap bleibt stehen */ }
}

/* ------------------------------------------------------------- Kalender -- */
async function tickCalendar() {
  try {
    S.calendar = await api("/api/terminal/calendar");
    const k = S.calendar, top = k.events.slice(0, 6);
    $("#cal").innerHTML = top.length ? top.map((e) => `
      <div class="cal__row" data-impact="${e.impact}" title="${e.title} · Prognose ${e.forecast || "–"} · zuvor ${e.previous || "–"}">
        <div><div class="cal__title">${e.country} ${e.title}</div><div class="cal__when">${day(e.ts)} · in ${e.hours_away.toFixed(1)} h</div></div>
        ${stars({ High: 5, Medium: 3, Low: 1, Holiday: 0 }[e.impact] ?? 1)}</div>`).join("") : `<p class="empty">Keine Termine diese Woche.</p>`;
    $("#cal-sum").innerHTML = `<span class="${k.risk_pct < 30 ? "up" : "down"}">${(100 - k.risk_pct).toFixed(0)}%</span> <span class="muted">(${k.high_within_24h} schwer/24h)</span>`;
  } catch (e) { $("#cal").innerHTML = `<p class="empty">Kalender nicht erreichbar: ${e.message}</p>`; }
}

/* ----------------------------------------------------------------- Chart -- */
async function loadMarket() {
  try {
    const m = await fuerMarkt((s, tf) => api(`/api/market/${s}/chart?timeframe=${tf}&candles=600`));
    if (m === VERALTET) return;
    S.market = m;
  } catch (e) { S.market = null; $("#legend").innerHTML = `<span class="down">Chart: ${e.message}</span>`; }
  renderChart();
}
function positionLines() {
  const lines = [];
  for (const p of [...S.botPositions, ...S.positions]) {
    if (p.symbol !== S.symbol) continue;
    const qty = p.qty ?? 0, side = String(p.side).toLowerCase().startsWith("l") ? 1 : -1;
    lines.push({ price: p.entry, colour: "#e8edf5", dash: [2, 3], width: 1, label: `Einstieg ${px(p.entry)}`, id: `${p.id}-e` });
    if (p.tp) lines.push({ price: p.tp, colour: "#22c55e", label: `${signed((p.tp - p.entry) * qty * side, 0)} USD`, id: `${p.id}-tp`, closable: p.source === "manuell", pid: p.id, kind: "tp" });
    if (p.sl) lines.push({ price: p.sl, colour: "#ef4444", label: `${signed((p.sl - p.entry) * qty * side, 0)} USD`, id: `${p.id}-sl`, closable: p.source === "manuell", pid: p.id, kind: "sl" });
  }
  for (const d of S.drawings) if (d.symbol === S.symbol) lines.push({ price: d.price, colour: "#f59e0b", dash: [1, 0], width: 1, label: px(d.price), id: d.id, closable: true });
  for (const a of S.alerts) if (a.symbol === S.symbol) lines.push({ price: a.price, colour: "#facc15", dash: [8, 4], width: 1, label: `Alarm ${px(a.price)}`, id: `al-${a.id}`, closable: true });
  return lines;
}
function chartOpts(extra = {}) {
  const candles = mergedCandles();
  const forming = !!(S.live && S.live.symbol === S.symbol && S.live.timeframe === S.tf && !S.live.closed && candles.length && candles[candles.length - 1].ts === S.live.ts);
  const setup = S.market?.setups?.[0];
  const z = zoom();
  // Das Buch traegt sein Symbol -- wie die formende Kerze. Ein fremdes Buch
  // liefert Heatmap-Baender in einer ganz anderen Groessenordnung.
  const buch = S.heat && S.heat.symbol === S.symbol ? S.heat : null;
  return { candles, forming, lines: positionLines(), layers: S.ebenen, book: buch,
    visible: z.visible, end: z.end,
    signalIndex: setup ? (S.market.candles.length - 1) : undefined, ...extra };
}
function renderChart() {
  const canvas = $("#chart");
  if (!S.market) return;
  const g = drawTerminalChart(canvas, S.market, chartOpts({ hover: S.hover }));
  if (!g) return;
  const candles = mergedCandles(), last = candles[candles.length - 1];
  $("#legend").innerHTML = g.ema ? `<span><b style="color:#ef4444">EMA 200</b> ${g.ema.e200 ? px(g.ema.e200) : "–"}</span><span><b style="color:#60a5fa">EMA 20</b> ${g.ema.e20 ? px(g.ema.e20) : "–"}</span>` : "";
  if (!S.hover) $("#readout").textContent = `${day(last.ts)}  O ${px(last.open)}  H ${px(last.high)}  L ${px(last.low)}  C ${px(last.close)}  ATR ${S.market.atr_pct !== undefined ? (S.market.atr_pct * 100).toFixed(2) : "–"}%${zoom().end !== null ? "  · verschoben" : ""}`;
  $("#lineboxes").innerHTML = g.boxes.map((b) => `<div class="linebox" style="top:${b.y}px;color:${b.colour}"><span>${b.label}</span>${b.closable ? `<button data-line="${b.id}" title="entfernen">x</button>` : ""}</div>`).join("");
}
/* ------------------------------------------------- Ebenen-Einstellungen -- */
const EBENEN_FARBE = {
  ema: "#60a5fa", fvg: "#f59e0b", zonen: "#34d399", liquiditaet: "#f87171",
  struktur: "#9aa7bb", trend: "#22c55e", volumen: "#e8edf5", heatmap: "#facc15", positionen: "#ffffff",
};

function ebeneAn(key) { return S.ebenen[key] !== false; }

function ebenenMarkup() {
  return Object.entries(EBENEN).map(([k, label]) =>
    `<button class="lay" type="button" role="checkbox" aria-checked="${ebeneAn(k)}" data-lay="${k}">
       <span class="lay__box"></span>
       <span class="lay__swatch" style="background:${EBENEN_FARBE[k]}"></span>
       <span>${label}</span></button>`).join("") +
    `<div class="pop__foot"><button type="button" data-all="on">alle an</button>
       <button type="button" data-all="off">alle aus</button>
       <button type="button" data-all="reset">Vorgabe</button></div>`;
}

// Nur die Haken umsetzen, nie das Panel neu bauen. Ein per innerHTML ersetzter
// Knopf ist beim Hochblubbern schon aus dem DOM -- panel.contains(target) meldet
// dann false und der Schliesser draussen haut das Fenster nach einem Klick zu.
function renderLayers() {
  $$("[data-lay]", $("#layers")).forEach((b) =>
    b.setAttribute("aria-checked", String(ebeneAn(b.dataset.lay))));
}

function wireLayers() {
  const btn = $("#btn-indicators"), panel = $("#layers");
  panel.innerHTML = ebenenMarkup();
  renderLayers();
  panel.addEventListener("click", (e) => {
    e.stopPropagation();
    const ebene = e.target.closest("[data-lay]"), alle = e.target.closest("[data-all]");
    if (ebene) S.ebenen[ebene.dataset.lay] = !ebeneAn(ebene.dataset.lay);
    else if (alle) {
      S.ebenen = alle.dataset.all === "reset" ? {}
        : Object.fromEntries(Object.keys(EBENEN).map((k) => [k, alle.dataset.all === "on"]));
    } else return;
    localStorage.setItem("dw-ebenen", JSON.stringify(S.ebenen));
    renderLayers(); renderChart();
  });
  const zu = () => { panel.hidden = true; btn.setAttribute("aria-expanded", "false"); };
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const offen = btn.getAttribute("aria-expanded") === "true";
    if (offen) { zu(); return; }
    panel.hidden = false; btn.setAttribute("aria-expanded", "true");
    // Aus dem Knopf wachsen lassen, 140 ms -- nicht aus dem Nichts.
    panel.classList.add("enter");
    requestAnimationFrame(() => panel.classList.remove("enter"));
  });
  document.addEventListener("click", zu);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") zu(); });
}

function wireChart() {
  const canvas = $("#chart");
  canvas.addEventListener("pointermove", (e) => {
    const box = canvas.getBoundingClientRect();
    const pos = { x: e.clientX - box.left, y: e.clientY - box.top };
    if (S.drag) {
      const g = drawTerminalChart(canvas, S.market, chartOpts());
      if (g) {
        const shift = Math.round((pos.x - S.drag.x) / g.slot);
        if (shift !== 0) {
          const total = mergedCandles().length;
          // Nach rechts ueber das Ende hinaus ist erlaubt: der Zeichner macht
          // daraus leeren Raum, wie bei TradingView. Vorher war bei der
          // letzten Kerze Schluss und man kam nicht an den rechten Rand.
          const maxEnd = total + Math.floor((g.visible ?? g.count) / 3);
          const end = Math.max(20, Math.min(maxEnd, S.drag.end - shift));
          zoom().end = end >= total ? (end > total ? end : null) : end;
          S.drag = { x: pos.x, end };
        }
      }
      renderChart(); return;
    }
    S.hover = pos;
    const g = drawTerminalChart(canvas, S.market, chartOpts({ hover: S.hover }));
    if (g) {
      const i = Math.max(0, Math.min(g.count - 1, Math.floor((pos.x - g.pL) / g.slot)));
      const k = mergedCandles()[g.offset + i];
      if (k) $("#readout").textContent = `${day(k.ts)}  O ${px(k.open)}  H ${px(k.high)}  L ${px(k.low)}  C ${px(k.close)}  ${pct(((k.close - k.open) / k.open) * 100)}`;
    }
  });
  canvas.addEventListener("pointerdown", (e) => {
    if (S.tool !== "cross" || !S.market) return;
    const box = canvas.getBoundingClientRect();
    S.drag = { x: e.clientX - box.left, end: zoom().end ?? mergedCandles().length };
    canvas.setPointerCapture(e.pointerId);
  });
  const endDrag = () => { S.drag = null; };
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);
  canvas.addEventListener("pointerleave", () => { S.hover = null; S.drag = null; renderChart(); });
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const g = drawTerminalChart(canvas, S.market, chartOpts());
    if (!g) return;
    const factor = e.deltaY > 0 ? 1.15 : 1 / 1.15;
    zoom().visible = Math.max(20, Math.min(2000, Math.round((g.visible ?? g.count) * factor)));
    renderChart();
  }, { passive: false });
  canvas.addEventListener("dblclick", () => { zoomReset(); renderChart(); });
  canvas.addEventListener("click", (e) => {
    if (!S.market || S.tool === "cross") return;
    const box = canvas.getBoundingClientRect();
    const g = drawTerminalChart(canvas, S.market, chartOpts());
    const price = g.lo + ((g.pB - (e.clientY - box.top)) / (g.pB - g.pT)) * (g.hi - g.lo);
    if (S.tool === "hline") { S.drawings.push({ id: `d${Date.now()}`, symbol: S.symbol, price }); renderChart(); }
    if (S.tool === "alert") addAlert(price);
  });
  $("#lineboxes").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-line]"); if (!b) return;
    const id = b.dataset.line;
    if (id.startsWith("al-")) { S.alerts = S.alerts.filter((a) => `al-${a.id}` !== id); saveAlerts(); renderChart(); renderTrades(); return; }
    if (id.startsWith("d")) { S.drawings = S.drawings.filter((d) => d.id !== id); renderChart(); return; }
    const line = positionLines().find((l) => l.id === id);
    if (line?.pid) {
      const p = S.positions.find((x) => x.id === line.pid);
      try { await api(`/api/terminal/positions/${line.pid}/tpsl?${line.kind === "tp" ? `sl=${p.sl ?? ""}` : `tp=${p.tp ?? ""}`}`, { method: "POST" }); await tickPositions(); }
      catch (err) { flash($("#m-msg"), err.message, "err"); }
    }
  });
  $$(".tools button").forEach((b) => b.addEventListener("click", () => {
    const t = b.dataset.tool;
    if (t === "clear") { S.drawings = []; renderChart(); return; }
    S.tool = t; $$(".tools button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  }));
  new ResizeObserver(() => renderChart()).observe($("#chartwrap"));
  wireLayers();
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    if (e.key === "1") setView("markt"); if (e.key === "2") setView("konto"); if (e.key === "3") setView("trades"); if (e.key === "4") setView("verlauf");
    if (e.key === "m") setMode("manual"); if (e.key === "b") setMode("bot");
    if (S.view === "markt" && (e.key === "+" || e.key === "-")) { const z = zoom(); z.visible = Math.max(20, Math.round((z.visible ?? 120) * (e.key === "+" ? 1 / 1.15 : 1.15))); renderChart(); }
  });
}

/* ----------------------------------------------------------------- Alerts -- */
function saveAlerts() { localStorage.setItem("dw-alerts", JSON.stringify(S.alerts)); }
function addAlert(price) {
  S.alerts.push({ id: Date.now(), symbol: S.symbol, price, created: Date.now(), fired: false });
  if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
  saveAlerts(); renderChart(); renderTrades();
}
function checkAlerts() {
  if (!S.head) return;
  for (const a of S.alerts) {
    if (a.fired || a.symbol !== S.symbol) continue;
    const prev = a.last ?? S.head.last;
    if ((prev <= a.price && S.head.last >= a.price) || (prev >= a.price && S.head.last <= a.price)) {
      a.fired = true; a.firedAt = Date.now();
      if ("Notification" in window && Notification.permission === "granted") new Notification(`${a.symbol} ${px(a.price)} erreicht`);
    }
    a.last = S.head.last;
  }
  saveAlerts();
}

/* ------------------------------------------------------------------ Score -- */
async function tickScore() {
  try {
    const sc = await fuerMarkt((s) => api(`/api/terminal/score/${s}`));
    if (sc === VERALTET) return;
    S.score = sc; renderScore(); renderReco();
  }
  catch (e) { $("#score-head").textContent = `Score: ${e.message}`; }
}
function card(k) {
  const dirClass = k.direction === "long" ? "up" : k.direction === "short" ? "down" : "neutral";
  const word = k.direction === "long" ? "Long" : k.direction === "short" ? "Short" : "Neutral";
  const label = ["chart", "liquiditaet", "entry"].includes(k.key) ? word : (k.pct >= 0 ? "Positiv" : "Negativ");
  return `<div class="card" data-key="${k.key}" data-measured="${k.measured}" title="${k.text}"><div class="card__label">${k.label}</div>${stars(k.stars)}
    <div class="card__val ${dirClass}">${k.measured ? `${label} (${k.pct >= 0 ? "+" : ""}${k.pct.toFixed(0)}%)` : "noch keine Messung"}</div><div class="card__text">${k.text}</div></div>`;
}
function renderScore() {
  const s = S.score; if (!s) return;
  const dir = $("#score-dir"); dir.textContent = s.direction === "long" ? "Long" : s.direction === "short" ? "Short" : "Neutral";
  dir.className = `score__dir ${s.direction === "long" ? "up" : s.direction === "short" ? "down" : "muted"}`;
  $("#score-head").textContent = `${s.headline} · Deutlichkeit ${s.rating}/100 (${s.band})`;
  for (const [l, sh] of [["#score-long", "#score-short"], ["#r-long", "#r-short"]]) {
    $(l).style.width = `${s.long_pct}%`; $(l).textContent = `${s.long_pct.toFixed(0)}%`;
    $(sh).style.width = `${s.short_pct}%`; $(sh).textContent = `${s.short_pct.toFixed(0)}%`;
  }
  $("#cards").innerHTML = s.cards.map(card).join("");
  $("#chart-cards").innerHTML = s.chart_cards.map(card).join("");
  const hint = $("#r-hint"); hint.textContent = s.direction === "long" ? "Buy" : s.direction === "short" ? "Sell" : "Abwarten";
  hint.className = `rating__hint ${s.direction === "long" ? "up" : s.direction === "short" ? "down" : "muted"}`;
}

/* ------------------------------------------------- Bot entscheidet / empfiehlt -- */
function renderDecisions() {
  const s = S.settings; if (!s) return;
  const st = $("#dec-state");
  st.textContent = s.trader_running ? "Automatik läuft — der Bot entscheidet Größe, Hebel, Stop und Ziel selbst." : "Automatik steht. Es wird nichts eröffnet.";
  st.className = `dec__state ${s.trader_running ? "up" : "down"}`;
  $("#dec-margin").textContent = `${s.margin_pct.toFixed(0)} % des Kontos = ${money(s.initial_margin_usd, 0)} USD`;
  $("#dec-lev").textContent = `${s.leverage.toFixed(0)}× (Position ${money(s.initial_margin_usd * s.leverage, 0)} USD)`;
  $("#dec-stop").textContent = "aus dem Setup (Struktur), nie nachgezogen";
  $("#dec-target").textContent = "aus dem Setup, Chance:Risiko mindestens " + (s.fix_crv ? `${s.crv}:1` : "offen (Tor aus)");
  // Zwei verschiedene Regeln, und bis zum 20.10. abends stand hier nur die
  // schwächere: `max_loss_pct` LEHNT einen Trade ab, der mehr riskieren
  // würde (35 % — ein Notnagel, der fast nie greift), `risk_cap_pct` KÜRZT
  // die Position auf 1.5 %. Gezeigt wurde die 35 unter dem Wort
  // „Risikodeckel", also las man, ein Trade dürfe ein Drittel des Kontos
  // riskieren. Die bindende Regel steht jetzt zuerst.
  $("#dec-maxrisk").textContent = s.risk_cap_pct != null
    ? `${s.risk_cap_pct.toFixed(2)} % des Kontos je Trade — die Position wird dafür gekürzt`
      + ` (Ablehnung erst über ${s.max_loss_pct.toFixed(0)} %)`
    : `kein Deckel; abgelehnt erst über ${s.max_loss_pct.toFixed(0)} % des Kontos je Trade`;
  $("#dec-slots").textContent = "5 gleichzeitig (Margin bindet bei 3)";
  $("#dec-gates").textContent = (s.fix_crv ? `CRV ${s.crv}:1` : "CRV offen") + " · Kostentor offen";
  $("#dec-note").textContent = "Der Bot handelt auf M15-Schluss, zwölf Märkte, Papiergeld. Die Regeln stehen in config_offen/; Änderungen laufen über Konto → Erweiterte Einstellungen und tragen eine neue Laufsignatur.";
  $("#dec-next").innerHTML = `<b>Geplant, sobald E17 durch ist:</b> höchstens 2 gleichgerichtete Positionen (die vier Stops um 17:13 waren vier Longs in einer Minute) und der Trail-Ausstieg E22.`;
  $("#bs-auto").setAttribute("aria-checked", String(s.auto_trader));
}
function reco() {
  const s = S.score, m = S.market, st = S.settings, h = S.head;
  if (!s || !m || !st || !h) return null;
  const setup = m.setups?.[0];
  const side = setup ? (String(setup.side).toLowerCase().startsWith("l") ? "long" : "short") : s.direction;
  if (side === "neutral") return { side, text: "Abwarten — der Score ist nicht eindeutig und kein Setup liegt vor." };
  const price = h.last, atr = (m.atr_pct ?? 0.003) * price;
  const sl = setup ? setup.stop : (side === "long" ? price - atr : price + atr);
  const dist = Math.abs(price - sl);
  const tp = setup ? setup.target : (side === "long" ? price + 1.5 * dist : price - 1.5 * dist);
  const margin = st.balance * st.margin_pct / 100, lev = st.leverage;
  const qty = margin * lev / price, risk = dist * qty;
  return { side, price, sl, tp, margin, lev, qty, risk, riskPct: risk / st.balance * 100, fromSetup: !!setup, setup };
}
function renderReco() {
  const r = reco(); const host = $("#reco-body");
  if (!r) { host.textContent = "—"; return; }
  if (r.side === "neutral") { host.textContent = r.text; return; }
  host.innerHTML = `<div class="${r.side === "long" ? "up" : "down"}"><b>${r.side === "long" ? "Long" : "Short"}</b> bei ${px(r.price)} ${r.fromSetup ? `· Setup ${r.setup.key}` : "· nach Score, Stop 1×ATR"}</div>
    <div>Margin ${money(r.margin, 0)} USD · Hebel ${r.lev.toFixed(0)}× · Risiko ${money(r.risk, 2)} USD (${r.riskPct.toFixed(1)} %)</div>
    <div><span class="down">SL ${px(r.sl)}</span> · <span class="up">TP ${px(r.tp)}</span> · CRV ${(Math.abs(r.tp - r.price) / Math.abs(r.price - r.sl)).toFixed(2)}</div>
    <div class="muted">So würde der Bot es machen — eine Regel, keine Prognose. Gemessene Erwartung je Trade liegt nahe null.</div>`;
}

/* ------------------------------------------------------ Positionen & Co. -- */
async function tickPositions() {
  try {
    const [man, bot] = await Promise.all([api("/api/terminal/positions"), api("/api/portfolio/open")]);
    S.positions = man;
    S.botPositions = bot.map((p) => ({ id: `bot-${p.symbol}`, symbol: p.symbol, side: p.side, qty: p.qty, entry: p.entry, leverage: p.leverage, margin: p.margin,
      tp: p.target, sl: p.stop, opened_ts: p.opened_ts, last: p.last_price, unrealized: p.unrealised ?? 0, position_size: p.notional ?? (p.qty ?? 0) * (p.entry ?? 0), source: "bot", r_now: p.r_now, setup: p.setup }));
  } catch (e) { /* alte Werte bleiben */ }
  renderStrip(); renderTrades(); if (S.view === "markt") renderChart();
}
async function tickHistory() {
  try { S.history = await api("/api/terminal/history?limit=100"); } catch (e) { /* bleibt */ }
  renderTrades();
}
function posRow(p) {
  const side = String(p.side).toLowerCase().startsWith("l") ? 1 : -1;
  const tpUsd = p.tp ? (p.tp - p.entry) * p.qty * side : null, slUsd = p.sl ? (p.sl - p.entry) * p.qty * side : null;
  return `<div class="pos__row"><span>${p.symbol} <span class="${side > 0 ? "up" : "down"}">${side > 0 ? "Long" : "Short"}</span></span>
    <span>${money(p.position_size, 0)} USD</span><span>${money(p.margin ?? 0, 0)} USD</span><span>${px(p.entry)}</span>
    <span class="muted">${p.source === "bot" ? `Bot${p.setup ? " · " + p.setup : ""}` : "Manuell"}</span><span>${(p.leverage ?? 1).toFixed(0)}x</span>
    <div class="tpsl"><span class="up">${p.tp ? `${px(p.tp)} <small>(${signed(tpUsd, 0)} USD / ${pct(((p.tp - p.entry) / p.entry) * 100 * side)})</small>` : "–"}</span>
      <span class="down">${p.sl ? `${px(p.sl)} <small>(${signed(slUsd, 0)} USD / ${pct(((p.sl - p.entry) / p.entry) * 100 * side)})</small>` : "–"}</span></div>
    <span class="${(p.unrealized ?? 0) >= 0 ? "up" : "down"}">${signed(p.unrealized ?? 0)} USD${p.r_now !== undefined && p.r_now !== null ? ` <small class="muted">${(p.r_now).toFixed(2)} R</small>` : ""}</span>
    <span>${p.source === "manuell" ? `<button class="btn-link" data-close="${p.id}">Market</button>` : `<span class="muted" title="vom Bot geführt">Bot</span>`}</span></div>`;
}
function renderStrip() {
  const all = [...S.botPositions, ...S.positions];
  const sum = all.reduce((t, p) => t + (p.unrealized ?? 0), 0);
  $("#markt-open").innerHTML = all.length
    ? `<span>Offen: <b>${all.length}</b> · unrealisiert <b class="${sum >= 0 ? "up" : "down"}">${signed(sum)} USD</b> · ` + all.map((p) => `<button class="btn-link" data-goto="${p.symbol}">${p.symbol.replace("USDT", "")} <span class="${(p.unrealized ?? 0) >= 0 ? "up" : "down"}">${signed(p.unrealized ?? 0, 0)}</span></button>`).join(" ") + `</span><button class="btn-link" data-view="trades">alle Trades →</button>`
    : `<span class="muted">Keine offene Position. Der Bot entscheidet auf M15-Schluss.</span><button class="btn-link" data-view="trades">Trades →</button>`;
  $$("[data-goto]", $("#markt-open")).forEach((b) => b.addEventListener("click", () => { $("#sym").value = b.dataset.goto; $("#sym").dispatchEvent(new Event("change")); }));
  $$("[data-view]", $("#markt-open")).forEach((b) => b.addEventListener("click", () => setView("trades")));
}
function renderTrades() {
  if (S.view !== "trades") return;
  const all = [...S.botPositions, ...S.positions];
  $("#tr-open-hint").textContent = all.length ? `${all.length} Position${all.length > 1 ? "en" : ""} · unrealisiert ${signed(all.reduce((t, p) => t + (p.unrealized ?? 0), 0))} USD` : "nichts offen";
  $("#tr-open").innerHTML = all.length
    ? `<div class="pos__head"><span>Asset</span><span>Position Size</span><span>Margin</span><span>In</span><span>Quelle</span><span>LVG</span><span>TP / SL</span><span>Unrealized PNL</span><span>Close</span></div>` + all.map(posRow).join("")
    : `<p class="empty">Keine offene Position.</p>`;
  $$("button[data-close]", $("#tr-open")).forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true; b.textContent = "…";
    try { await api(`/api/terminal/positions/${b.dataset.close}/close`, { method: "POST" }); await tickPositions(); await tickHistory(); await tickAccount(); }
    catch (e) { b.disabled = false; b.textContent = "Market"; flash($("#m-msg"), e.message, "err"); }
  }));
  const al = S.alerts;
  $("#tr-alerts").innerHTML = `<p class="empty">Alarm setzen: im Markt das Glocken-Werkzeug wählen und in den Chart klicken, oder <button class="btn-link" id="al-add">beim aktuellen Kurs</button>.</p>` +
    (al.length ? `<div class="hist__head hist--al"><span>Asset</span><span>Preis</span><span>Zustand</span><span>gesetzt</span><span></span></div>` +
      al.map((a) => `<div class="hist__row hist--al"><span>${a.symbol}</span><span>${px(a.price)}</span><span class="${a.fired ? "up" : "muted"}">${a.fired ? `ausgelöst ${clock(a.firedAt)}` : "wartet"}</span><span class="muted">${day(a.created)}</span><button class="btn-link" data-al="${a.id}">x</button></div>`).join("") : "");
  $("#al-add")?.addEventListener("click", () => { if (S.head) addAlert(S.head.last); });
  $$("button[data-al]", $("#tr-alerts")).forEach((b) => b.addEventListener("click", () => { S.alerts = S.alerts.filter((a) => String(a.id) !== b.dataset.al); saveAlerts(); renderTrades(); }));
  const rows = S.history.filter((t) => S.histSrc === "alle" || t.source === S.histSrc);
  const sum = rows.reduce((t, r) => t + (r.net_pnl ?? 0), 0), wins = rows.filter((r) => (r.r_multiple ?? 0) > 0).length;
  $("#tr-hist-hint").textContent = rows.length ? `${rows.length} Trades · ${Math.round(wins / rows.length * 100)} % Treffer · ${signed(sum)} USD · ${signed(rows.reduce((t, r) => t + (r.r_multiple ?? 0), 0) / rows.length, 3)} R je Trade` : "";
  $("#tr-hist").innerHTML = rows.length
    ? `<div class="hist__head"><span>Asset</span><span>Mode</span><span>In</span><span>Out</span><span>Position Size</span><span>LVG</span><span>TP / SL</span><span>Realized PNL</span><span>Befund</span></div>` +
      rows.map((t) => { const side = String(t.side).toLowerCase().startsWith("l") ? 1 : -1; return `<div class="hist__row" title="${t.verdict ?? ""}">
        <span>${t.symbol} <span class="${side > 0 ? "up" : "down"}">${side > 0 ? "Long" : "Short"}</span></span><span class="muted">${t.source === "bot" ? `Bot${t.setup ? " · " + t.setup : ""}` : "Manuell"}</span>
        <span>${px(t.entry)}</span><span>${px(t.exit)}</span><span>${t.position_size ? `${money(t.position_size, 0)} USD` : "–"}</span><span>${t.leverage ? `${Number(t.leverage).toFixed(0)}x` : "–"}</span>
        <div class="tpsl"><span class="up">${t.tp ? px(t.tp) : "–"}</span><span class="down">${t.sl ? px(t.sl) : "–"}</span></div>
        <span class="${(t.net_pnl ?? 0) >= 0 ? "up" : "down"}">${signed(t.net_pnl ?? 0)} USD <small class="muted">${(t.r_multiple ?? 0).toFixed(2)} R</small></span>
        <span class="muted">${day(t.closed_ts)} · ${t.exit_reason ?? ""}${t.stopped_by_wick ? " · Docht" : ""}${t.max_favourable_r ? ` · best +${t.max_favourable_r.toFixed(2)} R` : ""}</span></div>`; }).join("")
    : `<p class="empty">Noch kein abgeschlossener Trade unter dieser Konfiguration.</p>`;
}

/* ------------------------------------------------------------ Konto -- */
async function tickAccount() {
  try {
    S.account = await api(`/api/terminal/account?range=${S.range}`);
    const a = S.account;
    $("#a-bal").textContent = `${money(a.balance, 0)} USD`;
    const p = $("#a-pnl"); p.innerHTML = `${signed(a.pnl_today, 0)} USD <small>${pct(a.pnl_today_pct, 1)}</small>`; p.className = `stat__value ${a.pnl_today >= 0 ? "up" : "down"}`;
    $("#a-dd").textContent = `${a.max_drawdown_pct.toFixed(0)}%`;
    $("#a-win").textContent = a.win_rate === null ? "–" : `${a.win_rate.toFixed(0)}%`;
    $("#a-acc").innerHTML = a.bot_accuracy === null ? "–" : `${a.bot_accuracy.toFixed(0)}% <small>n=${a.bot_accuracy_n}</small>`;
    $("#a-n").textContent = String(a.trades);
    $("#a-note").textContent = `${a.note} Zeitraum: ${a.range}. Start ${money(a.start, 0)} USD.`;
    if (S.view === "konto") drawEquity($("#a-chart"), a.series, a.range);
  } catch (e) { $("#a-note").textContent = `Konto: ${e.message}`; }
  renderRegeln();
}
function renderRegeln() {
  const s = S.settings; if (!s) return;
  $("#konto-regeln").innerHTML = [
    ["Größe", `${s.margin_pct.toFixed(0)} % des Kontos als Margin, Hebel ${s.leverage.toFixed(0)}× — Position ${money(s.initial_margin_usd * s.leverage, 0)} USD. Aufstockend: wächst das Konto, wächst die Position.`],
    ["Stop und Ziel", `Beide aus dem Setup (Struktur im Chart). Der Stop wird nicht nachgezogen — E14 hat gemessen, dass ein Einstands-Stop das Ergebnis monoton verschlechtert.`],
    ["Tore", `Kostentor und Chance-Risiko sind seit 20.10. 13:00 auf Anweisung offen. Gemessen auf 3.553 abgelehnten Signalen: −0.1464 R je Trade. Der Vergleich läuft (scripts/tore_vergleich.py).`],
    ["Plätze", `5 gleichzeitig, Margin bindet bei 3. Die vier Stops um 17:13 waren vier gleichgerichtete Longs — geplant nach E17: höchstens 2 je Richtung.`],
    ["Ausstieg", `Stop, Ziel oder Zeit. Ein Trail-Ausstieg („raus, sobald er dreht") ist als E22 vorregistriert und wird nach E17 gemessen, bevor er live geht.`],
  ].map(([k, v]) => `<div class="regel"><b>${k}</b><span>${v}</span></div>`).join("");
}

/* ------------------------------------------------------------ Verlauf -- */
async function tickVerlauf() {
  if (S.view !== "verlauf") return;
  try { S.curve = await api("/api/portfolio/curve"); } catch (e) { $("#v-stats").textContent = `Verlauf: ${e.message}`; return; }
  const pts = S.curve.points ?? [];
  if (!pts.length) { $("#v-stats").innerHTML = `<p class="empty">Noch kein abgeschlossener Trade.</p>`; return; }
  drawRCurve($("#v-chart"), pts);
  const rs = pts.map((p, i) => p.cumulative_r - (i ? pts[i - 1].cumulative_r : 0));
  const n = rs.length, mean = rs.reduce((a, b) => a + b, 0) / n;
  const sd = n > 1 ? Math.sqrt(rs.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1)) : 0;
  const se = n > 1 ? sd / Math.sqrt(n) : 0, lo = mean - 1.96 * se, hi = mean + 1.96 * se;
  const wins = rs.filter((r) => r > 0).length;
  $("#v-stats").innerHTML = `
    <div class="v-stat"><span>Trades</span><b>${n}</b></div>
    <div class="v-stat"><span>Summe</span><b class="${pts[n - 1].cumulative_r >= 0 ? "up" : "down"}">${signed(pts[n - 1].cumulative_r, 2)} R</b></div>
    <div class="v-stat"><span>je Trade</span><b class="${mean >= 0 ? "up" : "down"}">${signed(mean, 4)} R</b></div>
    <div class="v-stat"><span>95 %-Intervall</span><b>[${signed(lo, 3)}, ${signed(hi, 3)}]</b></div>
    <div class="v-stat"><span>Treffer</span><b>${Math.round(wins / n * 100)} %</b></div>
    <p class="muted v-note">${n < 30 ? `Unter 30 Trades wird nicht geurteilt — das Intervall ${lo <= 0 && hi >= 0 ? "schliesst null ein" : "liegt noch auf einer Seite, ist aber zu breit"}.` : (lo > 0 ? "Intervall über null." : hi < 0 ? "Intervall unter null." : "Intervall schliesst null ein: nicht entschieden.")} Eine Null in R ist nicht dasselbe wie null USD — die Größe wächst mit dem Konto.</p>`;
}

/* ------------------------------------------------------- Einstellungen -- */
async function loadSettings() {
  try {
    S.settings = await api("/api/terminal/bot-settings");
    const s = S.settings;
    $("#bs-margin").value = s.initial_margin_usd; $("#bs-margin-pct").value = s.margin_pct; $("#bs-margin-val").textContent = `${s.margin_pct}% von ${money(s.balance, 0)} USD`;
    $("#bs-maxlev").setAttribute("aria-checked", String(s.max_leverage)); $("#bs-lev").value = s.leverage;
    $("#bs-maxloss").value = s.max_loss_pct; $("#bs-minloss").value = s.min_loss_pct;
    $("#bs-maxrisk").setAttribute("aria-checked", String(s.always_max_risk));
    $("#bs-fixcrv").setAttribute("aria-checked", String(s.fix_crv)); $("#bs-crv").value = s.crv;
    $("#bs-rating").value = s.min_bot_rating; $("#bs-rating-note").textContent = s.wirkung.min_bot_rating;
    $("#m-avail").textContent = `Avlb: ${money(s.balance)} USD`;
    if (!$("#m-margin").value) { $("#m-margin").value = Math.round(s.balance * s.margin_pct / 100); $("#m-margin-pct").value = s.margin_pct; $("#m-lev").value = s.leverage; }
    renderDecisions(); renderRegeln(); renderReco(); updateManualSummary();
  } catch (e) { flash($("#bs-msg"), `Einstellungen: ${e.message}`, "err"); }
}
function settingsBody() {
  return {
    initial_margin_usd: Number($("#bs-margin").value), margin_pct: Number($("#bs-margin-pct").value),
    max_leverage: $("#bs-maxlev").getAttribute("aria-checked") === "true", leverage: Number($("#bs-lev").value),
    max_loss_pct: Number($("#bs-maxloss").value), min_loss_pct: Number($("#bs-minloss").value),
    always_max_risk: $("#bs-maxrisk").getAttribute("aria-checked") === "true",
    fix_crv: $("#bs-fixcrv").getAttribute("aria-checked") === "true", crv: Number($("#bs-crv").value),
    auto_trader: $("#bs-auto").getAttribute("aria-checked") === "true", min_bot_rating: Number($("#bs-rating").value),
  };
}
async function applySettings(btn, msgEl) {
  btn.setAttribute("aria-busy", "true"); const label = btn.textContent; btn.textContent = "Wird angewendet…";
  try { const r = await api("/api/terminal/bot-settings", { method: "POST", body: JSON.stringify(settingsBody()) }); flash(msgEl, `Angewendet. ${r.schritte.join(" ")} — Seite lädt in 30 s nach.`, "ok"); setTimeout(() => location.reload(), 30000); }
  catch (err) { flash(msgEl, err.message, "err"); }
  finally { btn.removeAttribute("aria-busy"); btn.textContent = label; }
}
function wireSettings() {
  $$(".switch").forEach((sw) => sw.addEventListener("click", () => sw.setAttribute("aria-checked", String(sw.getAttribute("aria-checked") !== "true"))));
  $("#bs-margin-pct").addEventListener("input", (e) => { const s = S.settings; if (!s) return; $("#bs-margin").value = Math.round(s.balance * e.target.value / 100); $("#bs-margin-val").textContent = `${e.target.value}% von ${money(s.balance, 0)} USD`; });
  $("#bs-margin").addEventListener("input", (e) => { const s = S.settings; if (!s) return; const p = Math.max(1, Math.min(100, Math.round(e.target.value / s.balance * 100))); $("#bs-margin-pct").value = p; $("#bs-margin-val").textContent = `${p}% von ${money(s.balance, 0)} USD`; });
  $("#bs-apply").addEventListener("click", (e) => applySettings(e.currentTarget, $("#bs-msg2")));
  // Auto Trader im Markt-Fenster: der eine Schalter, den man im Bot-Modus hat. Wirkt sofort.
  $("#bs-auto").addEventListener("click", async (e) => {
    const on = e.currentTarget.getAttribute("aria-checked") === "true";
    flash($("#bs-msg"), on ? "Händler wird gestartet…" : "Händler wird gestoppt…", "");
    try { await api("/api/terminal/bot-settings", { method: "POST", body: JSON.stringify({ ...settingsBody(), auto_trader: on }) }); flash($("#bs-msg"), on ? "Automatik läuft. Seite lädt in 30 s nach." : "Automatik gestoppt. Seite lädt in 30 s nach.", "ok"); setTimeout(() => location.reload(), 30000); }
    catch (err) { flash($("#bs-msg"), err.message, "err"); }
  });
}

/* --------------------------------------------------------- Manuell handeln -- */
function updateManualSummary() {
  const h = S.head; if (!h) return;
  const margin = Number($("#m-margin").value || 0), lev = Number($("#m-lev").value || 1);
  const pos = margin * lev, qty = pos / h.last, fees = pos * 0.0005;
  const tp = Number($("#m-tp").value), sl = Number($("#m-sl").value), side = S.side === "long" ? 1 : -1;
  $("#m-tp-pct").textContent = tp ? pct(((tp - h.last) / h.last) * 100 * side, 2) : "%";
  $("#m-sl-pct").textContent = sl ? pct(((sl - h.last) / h.last) * 100 * side, 2) : "%";
  $("#m-summary").innerHTML = `<span>Preis ${px(h.last)} · Margin ${money(margin, 0)} USD · Position ${money(pos, 0)} USD (${qty.toFixed(4)}) · Gebühren ${money(fees)} USD</span>` +
    (tp ? `<span class="up">TP ${px(tp)} → ${signed((tp - h.last) * qty * side, 0)} USD</span>` : "") + (sl ? `<span class="down">SL ${px(sl)} → ${signed((sl - h.last) * qty * side, 0)} USD (${(Math.abs(sl - h.last) * qty / (S.settings?.balance || 1) * 100).toFixed(1)} % des Kontos)</span>` : "");
  const btn = $("#m-submit"); btn.textContent = S.side === "long" ? "Kauf" : "Verkauf"; btn.className = `cta ${S.side === "long" ? "cta--buy" : "cta--sell"}`;
}
function wireManual() {
  $$(".ls button").forEach((b) => b.addEventListener("click", () => { S.side = b.dataset.side; $$(".ls button").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); updateManualSummary(); }));
  ["#m-margin", "#m-lev", "#m-tp", "#m-sl"].forEach((id) => $(id).addEventListener("input", updateManualSummary));
  $("#m-margin-pct").addEventListener("input", (e) => { if (S.settings) { $("#m-margin").value = Math.round(S.settings.balance * e.target.value / 100); $("#m-margin-val").textContent = `${e.target.value}%`; updateManualSummary(); } });
  $("#reco-apply").addEventListener("click", () => {
    const r = reco(); if (!r || r.side === "neutral") return;
    S.side = r.side; $$(".ls button").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.side === r.side)));
    $("#m-margin").value = Math.round(r.margin); $("#m-lev").value = r.lev; $("#m-tp").value = +r.tp.toFixed(4); $("#m-sl").value = +r.sl.toFixed(4);
    updateManualSummary();
  });
  $("#m-submit").addEventListener("click", async (e) => {
    const btn = e.currentTarget, msg = $("#m-msg");
    const body = { symbol: S.symbol, side: S.side, margin_usd: Number($("#m-margin").value), leverage: Number($("#m-lev").value),
      tp: $("#m-tp-on").getAttribute("aria-checked") === "true" && $("#m-tp").value ? Number($("#m-tp").value) : null,
      sl: $("#m-sl-on").getAttribute("aria-checked") === "true" && $("#m-sl").value ? Number($("#m-sl").value) : null };
    if (!(body.margin_usd > 0)) { flash(msg, "Margin fehlt.", "err"); $("#m-margin").focus(); return; }
    btn.setAttribute("aria-busy", "true");
    try { const r = await api("/api/terminal/order", { method: "POST", body: JSON.stringify(body) }); flash(msg, `Papier-Order gefüllt bei ${px(r.entry)} (${r.qty.toFixed(4)}).`, "ok"); await tickPositions(); }
    catch (err) { flash(msg, err.message, "err"); }
    finally { btn.removeAttribute("aria-busy"); }
  });
}

/* ---------------------------------------------------------------- Shell -- */
function flash(el, text, kind) { el.textContent = text; el.className = `msg ${kind}`; }
function setView(v) {
  S.view = v;
  $$("#views [data-view]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === v)));
  for (const id of ["markt", "konto", "trades", "verlauf"]) $(`#view-${id}`).classList.toggle("hidden", id !== v);
  document.body.dataset.view = v;
  if (v === "markt") { renderChart(); tickBook(); tickHeatmap(); }
  if (v === "konto") tickAccount();
  if (v === "trades") { renderTrades(); tickHistory(); }
  if (v === "verlauf") tickVerlauf();
}
function setCenter(c) {
  S.center = c; $$("#center-seg [data-center]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.center === c)));
  $("#view-chart").classList.toggle("hidden", c !== "chart"); $("#view-bot").classList.toggle("hidden", c !== "bot");
  $("#zoomhint").classList.toggle("hidden", c !== "chart");
  if (c === "chart") renderChart(); else tickScore();
}
function setMode(m) {
  S.mode = m; $$("[data-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === m)));
  $("#side-bot").classList.toggle("hidden", m !== "bot"); $("#side-manual").classList.toggle("hidden", m !== "manual");
  if (m === "manual") renderReco();
}
function wireShell() {
  $$("#views [data-view]").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
  $$("#center-seg [data-center]").forEach((b) => b.addEventListener("click", () => setCenter(b.dataset.center)));
  $$("[data-mode]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  $$("#hist-filter [data-src]").forEach((b) => b.addEventListener("click", () => { S.histSrc = b.dataset.src; $$("#hist-filter [data-src]").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); renderTrades(); }));
  $$("#tf [data-tf]").forEach((b) => b.addEventListener("click", () => { S.tf = b.dataset.tf; S.live = null; $$("#tf [data-tf]").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); loadMarket(); tickLive(); }));
  $$("#a-range [data-range]").forEach((b) => b.addEventListener("click", () => { S.range = b.dataset.range; $$("#a-range [data-range]").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); tickAccount(); }));
  $("#sym").addEventListener("change", (e) => { S.symbol = e.target.value; S.lastOb = null; S.live = null; S.book = null; S.heat = null; loadMarket(); tickLive(); tickHead(); tickBook(); tickHeatmap(); tickScore(); });
  new ResizeObserver(() => { if (S.view === "konto" && S.account) drawEquity($("#a-chart"), S.account.series, S.range); if (S.view === "verlauf" && S.curve) drawRCurve($("#v-chart"), S.curve.points ?? []); }).observe(document.body);
}

async function boot() {
  // Lesehaken fuer die Konsole: window.__dw.zoomBy zeigt, wie viele Kerzen je
  // Markt sichtbar sind. Nur lesen -- nichts hier drin steuert die Anzeige.
  window.__dw = S;
  const syms = await api("/api/market").catch(() => ["BTCUSDT"]);
  $("#sym").innerHTML = syms.map((s) => `<option value="${s}">${s.replace("USDT", "/USDT")}</option>`).join("");
  $("#sym").value = S.symbol;
  wireShell(); wireChart(); wireSettings(); wireManual();
  setView("markt"); setCenter("chart"); setMode("bot");
  await Promise.all([tickHead(), loadMarket(), tickLive(), tickBook(), tickCalendar(), tickHeatmap(), tickScore(), tickPositions(), tickHistory(), loadSettings(), tickAccount()]);
  setInterval(() => { tickHead(); tickBook(); checkAlerts(); }, 1000);
  setInterval(tickLive, 2000);
  setInterval(tickHeatmap, 5000);
  setInterval(() => { loadMarket(); tickPositions(); }, 15000);
  setInterval(() => { tickScore(); tickHistory(); if (S.view === "verlauf") tickVerlauf(); }, 30000);
  setInterval(tickCalendar, 15 * 60 * 1000);
  setInterval(() => { if (S.view === "konto") tickAccount(); }, 60000);
}
boot();
