/**
 * Darkwood Terminal -- der Controller.
 *
 * Eine Seite, drei Hauptansichten (Chart, Bot, Account), ein rechtes Fenster
 * mit zwei Modi (Manual, Bot), ein unteres mit drei Reitern (Positions,
 * Alerts, Trade History). Alles liest ECHTE Daten; nichts hier erfindet eine
 * Zahl. Wo das Projekt eine Zahl noch nicht hat, steht das dabei.
 *
 * Takt: Kopfzeile und Orderbuch jede Sekunde, Chart alle 15 s, Score alle 30 s,
 * Kalender alle 15 min. Ein Takt, der ausfaellt, laesst den alten Wert stehen
 * und markiert ihn -- ein leerer Bildschirm sieht aus wie "nichts los", und
 * das ist die falsche Botschaft bei einem Netzfehler.
 */
/* deliberate-ignore no-active-state -- diese Datei traegt keine Stile; `S.hover`
   ist der Fadenkreuz-Zustand des Charts. Alle :active-Zustaende stehen in
   terminal.css, je Knopf. */
import { drawTerminalChart, drawEquity } from "/static/terminal-chart.js";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const api = async (path, opts) => {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) {
    let msg = `${r.status}`;
    try { const j = await r.json(); msg = j.detail ?? JSON.stringify(j); } catch { /* text */ }
    throw new Error(msg);
  }
  return r.json();
};
const money = (v, d = 2) => (v ?? 0).toLocaleString("de-CH", { minimumFractionDigits: d, maximumFractionDigits: d });
// Preise nach Groessenordnung: 82'115.5, 104.63, 1.1938. Eine feste Stelle
// liess DOT, XRP und ATOM als "1.2 -> 1.2" erscheinen -- Einstieg und Ausstieg gleich.
const px = (v) => { const a = Math.abs(v ?? 0); return money(v, a >= 1000 ? 1 : a >= 10 ? 2 : 4); };
const signed = (v, d = 2) => (v >= 0 ? "+" : "") + money(v, d);
const pct = (v, d = 2) => (v >= 0 ? "+" : "") + (v ?? 0).toFixed(d) + "%";
const clock = (ts) => { const d = new Date(ts); return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };
const day = (ts) => { const d = new Date(ts); return `${d.getDate()}.${d.getMonth() + 1}. ${clock(ts)}`; };

const S = {
  symbol: "BTCUSDT", tf: "M15", view: "chart", mode: "bot", page: "trade", tab: "positions",
  market: null, head: null, score: null, positions: [], botPositions: [], history: [], calendar: null,
  settings: null, side: "long", indicators: true, hover: null, lines: [], drawings: [], tool: "cross",
  alerts: JSON.parse(localStorage.getItem("dw-alerts") || "[]"), lastOb: null, range: "month", account: null,
};

/* ------------------------------------------------------------- Sterne -- */
function stars(n) {
  const tpl = $("#star-tpl").content;
  const wrap = document.createElement("span"); wrap.className = "stars"; wrap.setAttribute("aria-label", `${n} von 5 Sternen`);
  for (let i = 0; i < 5; i++) { const s = tpl.firstElementChild.cloneNode(true); if (i < n) s.classList.add("on"); wrap.appendChild(s); }
  return wrap.outerHTML;
}

/* ------------------------------------------------------------ Kopfzeile -- */
async function tickHead() {
  try {
    S.head = await api(`/api/terminal/head/${S.symbol}`);
    const h = S.head;
    $("#hd-price").textContent = money(h.last, h.last >= 100 ? 1 : 4);
    const chg = $("#hd-chg"); chg.textContent = pct(h.change_pct); chg.className = `topbar__chg ${h.change_pct >= 0 ? "up" : "down"}`;
    const fund = h.funding_rate !== null ? `Funding ${(h.funding_rate * 100).toFixed(4)}%` : "";
    $("#hd-meta").textContent = `H ${money(h.high, 1)} · T ${money(h.low, 1)} · Vol ${(h.quote_volume / 1e9).toFixed(2)}B · ${fund}`;
    updateManualSummary();
  } catch (e) { $("#hd-meta").textContent = `Kopfzeile: ${e.message}`; }
}

/* ------------------------------------------------------------ Orderbuch -- */
async function tickBook() {
  try {
    const ob = await api(`/api/terminal/orderbook/${S.symbol}?depth=10`);
    const host = $("#ob");
    const maxQ = Math.max(...ob.bids.map((b) => b[1]), ...ob.asks.map((a) => a[1]), 1e-9);
    const rows = ob.bids.map((b, i) => {
      const a = ob.asks[i] ?? [0, 0];
      const changed = S.lastOb && (S.lastOb.bids[i]?.[1] !== b[1] || S.lastOb.asks[i]?.[1] !== a[1]);
      return `<div class="ob__row${changed ? " flash" : ""}">
        <div class="ob__cell ob__bid" style="--w:${(b[1] / maxQ) * 100}%"><span>${money(b[0], b[0] >= 100 ? 1 : 4)} <small class="muted">${b[1].toFixed(3)}</small></span></div>
        <div class="ob__cell ob__ask" style="--w:${(a[1] / maxQ) * 100}%"><span><small class="muted">${a[1].toFixed(3)}</small> ${money(a[0], a[0] >= 100 ? 1 : 4)}</span></div>
      </div>`;
    }).join("");
    host.innerHTML = rows + `<div class="ob__spread">Spread ${ob.spread_bp.toFixed(2)} bp</div>`;
    $("#ob-sum").innerHTML = `<span class="${ob.bid_share_pct >= 50 ? "up" : "down"}">${ob.bid_share_pct.toFixed(0)}%</span> <span class="muted">(${(Math.abs(ob.bid_share_pct - 50) * 2).toFixed(0)}%)</span>`;
    S.lastOb = ob;
    setTimeout(() => $$(".ob__row.flash").forEach((r) => r.classList.remove("flash")), 260);
  } catch (e) { $("#ob-sum").textContent = "–"; }
}

/* ------------------------------------------------------------- Kalender -- */
async function tickCalendar() {
  try {
    S.calendar = await api("/api/terminal/calendar");
    const k = S.calendar;
    const top = k.events.slice(0, 5);
    $("#cal").innerHTML = top.length ? top.map((e) => `
      <div class="cal__row" data-impact="${e.impact}" title="${e.title} · Prognose ${e.forecast || "–"} · zuvor ${e.previous || "–"}">
        <div><div class="cal__title">${e.country} ${e.title}</div><div class="cal__when">${day(e.ts)} · in ${e.hours_away.toFixed(1)} h</div></div>
        ${stars({ High: 5, Medium: 3, Low: 1, Holiday: 0 }[e.impact] ?? 1)}
      </div>`).join("") : `<p class="empty">Keine Termine diese Woche.</p>`;
    $("#cal-sum").innerHTML = `<span class="${k.risk_pct < 30 ? "up" : "down"}">${(100 - k.risk_pct).toFixed(0)}%</span> <span class="muted">(${k.high_within_24h} schwer/24h)</span>`;
  } catch (e) { $("#cal").innerHTML = `<p class="empty">Kalender nicht erreichbar: ${e.message}</p>`; }
}

/* ----------------------------------------------------------------- Chart -- */
async function loadMarket() {
  try {
    // `timeframe`, nicht `tf`: der Chart-Endpunkt heisst den Parameter so, und
    // ein falscher Name wird still ignoriert -- die Vorgabeebene kommt zurueck,
    // und die EMA 200 bleibt leer, weil 180 Kerzen nicht reichen.
    S.market = await api(`/api/market/${S.symbol}/chart?timeframe=${S.tf}&candles=400`);
  } catch (e) { S.market = null; $("#legend").innerHTML = `<span class="down">Chart: ${e.message}</span>`; }
  renderChart();
}

function positionLines() {
  const lines = [];
  for (const p of [...S.botPositions, ...S.positions]) {
    if (p.symbol !== S.symbol) continue;
    const qty = p.qty ?? 0;
    const side = String(p.side).toLowerCase().startsWith("l") ? 1 : -1;
    lines.push({ price: p.entry, colour: "#e8edf5", dash: [2, 3], width: 1, label: `Einstieg ${px(p.entry)}`, id: `${p.id}-e` });
    if (p.tp) lines.push({ price: p.tp, colour: "#22c55e", label: `${signed((p.tp - p.entry) * qty * side, 0)} USD`, id: `${p.id}-tp`, closable: p.source === "manuell", pid: p.id, kind: "tp" });
    if (p.sl) lines.push({ price: p.sl, colour: "#ef4444", label: `${signed((p.sl - p.entry) * qty * side, 0)} USD`, id: `${p.id}-sl`, closable: p.source === "manuell", pid: p.id, kind: "sl" });
  }
  for (const d of S.drawings) if (d.symbol === S.symbol && d.type === "hline") lines.push({ price: d.price, colour: "#f59e0b", dash: [1, 0], width: 1, label: px(d.price), id: d.id, closable: true, drawing: true });
  for (const a of S.alerts) if (a.symbol === S.symbol) lines.push({ price: a.price, colour: "#facc15", dash: [8, 4], width: 1, label: `Alarm ${px(a.price)}`, id: `al-${a.id}`, closable: true, alert: true });
  return lines;
}

function renderChart() {
  const canvas = $("#chart");
  if (!S.market || S.market === "unavailable") return;
  const setup = S.market.setups?.[0];
  const g = drawTerminalChart(canvas, S.market, {
    lines: positionLines(), indicators: S.indicators, hover: S.hover,
    signalIndex: setup ? S.market.candles.length - 1 : undefined,
  });
  if (!g) return;
  const last = S.market.candles[S.market.candles.length - 1];
  $("#legend").innerHTML = S.indicators
    ? `<span><b style="color:#ef4444">EMA 200</b> ${g.e200 ? money(g.e200, 1) : "–"}</span><span><b style="color:#60a5fa">EMA 20</b> ${g.e20 ? money(g.e20, 1) : "–"}</span>`
    : "";
  // atr_pct ist ein Bruch (0.0023), kein Prozentwert -- dieselbe Umrechnung wie im alten Dashboard.
  if (!S.hover) $("#readout").textContent = `${day(last.ts)}  O ${money(last.open, 1)}  H ${money(last.high, 1)}  L ${money(last.low, 1)}  C ${money(last.close, 1)}  ATR ${S.market.atr_pct !== undefined ? (S.market.atr_pct * 100).toFixed(2) : "–"}%`;
  const boxes = $("#lineboxes");
  boxes.innerHTML = g.boxes.map((b) => `<div class="linebox" style="top:${b.y}px;color:${b.colour}"><span>${b.label}</span>${b.closable ? `<button data-line="${b.id}" title="entfernen">x</button>` : ""}</div>`).join("");
}

function wireChart() {
  const canvas = $("#chart");
  canvas.addEventListener("pointermove", (e) => {
    const box = canvas.getBoundingClientRect();
    S.hover = { x: e.clientX - box.left, y: e.clientY - box.top };
    const g = drawTerminalChart(canvas, S.market, { lines: positionLines(), indicators: S.indicators, hover: S.hover });
    if (g && S.market) {
      const i = Math.max(0, Math.min(g.count - 1, Math.floor((S.hover.x - g.pL) / g.slot)));
      const k = S.market.candles[g.offset + i];
      if (k) $("#readout").textContent = `${day(k.ts)}  O ${money(k.open, 1)}  H ${money(k.high, 1)}  L ${money(k.low, 1)}  C ${money(k.close, 1)}  ${pct(((k.close - k.open) / k.open) * 100)}`;
    }
  });
  canvas.addEventListener("pointerleave", () => { S.hover = null; renderChart(); });
  canvas.addEventListener("click", (e) => {
    if (!S.market) return;
    const box = canvas.getBoundingClientRect();
    const g = drawTerminalChart(canvas, S.market, { lines: positionLines(), indicators: S.indicators });
    const price = g.lo + ((g.pB - (e.clientY - box.top)) / (g.pB - g.pT)) * (g.hi - g.lo);
    if (S.tool === "hline") { S.drawings.push({ id: `d${Date.now()}`, type: "hline", symbol: S.symbol, price }); renderChart(); }
    if (S.tool === "alert") addAlert(price);
  });
  $("#lineboxes").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-line]"); if (!b) return;
    const id = b.dataset.line;
    if (id.startsWith("al-")) { S.alerts = S.alerts.filter((a) => `al-${a.id}` !== id); saveAlerts(); renderChart(); renderBottom(); return; }
    if (id.startsWith("d")) { S.drawings = S.drawings.filter((d) => d.id !== id); renderChart(); return; }
    const line = positionLines().find((l) => l.id === id);
    if (line?.pid) {
      const p = S.positions.find((x) => x.id === line.pid);
      try {
        await api(`/api/terminal/positions/${line.pid}/tpsl?${line.kind === "tp" ? `sl=${p.sl ?? ""}` : `tp=${p.tp ?? ""}`}`, { method: "POST" });
        await tickPositions();
      } catch (err) { flash($("#m-msg"), err.message, "err"); }
    }
  });
  $$(".tools button").forEach((b) => b.addEventListener("click", () => {
    const t = b.dataset.tool;
    if (t === "clear") { S.drawings = []; renderChart(); return; }
    S.tool = t; $$(".tools button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  }));
  new ResizeObserver(() => renderChart()).observe($("#chartwrap"));
  $("#btn-indicators").addEventListener("click", (e) => { S.indicators = !S.indicators; e.currentTarget.setAttribute("aria-pressed", String(S.indicators)); renderChart(); });
  $("#btn-settings").addEventListener("click", () => { setMode("bot"); });
}

/* ----------------------------------------------------------------- Alerts -- */
function saveAlerts() { localStorage.setItem("dw-alerts", JSON.stringify(S.alerts)); }
function addAlert(price) {
  S.alerts.push({ id: Date.now(), symbol: S.symbol, price, created: Date.now(), fired: false });
  saveAlerts(); renderChart(); renderBottom();
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
    S.score = await api(`/api/terminal/score/${S.symbol}`);
    renderScore();
  } catch (e) { $("#score-head").textContent = `Score: ${e.message}`; }
}
function card(k) {
  const dirClass = k.direction === "long" ? "up" : k.direction === "short" ? "down" : "neutral";
  const word = k.direction === "long" ? "Long" : k.direction === "short" ? "Short" : "Neutral";
  const label = ["chart", "liquiditaet", "entry"].includes(k.key) ? word : (k.pct >= 0 ? "Positiv" : "Negativ");
  return `<div class="card" data-key="${k.key}" data-measured="${k.measured}" title="${k.text}">
    <div class="card__label">${k.label}</div>${stars(k.stars)}
    <div class="card__val ${dirClass}">${k.measured ? `${label} (${k.pct >= 0 ? "+" : ""}${k.pct.toFixed(0)}%)` : "noch keine Messung"}</div>
    <div class="card__text">${k.text}</div></div>`;
}
function renderScore() {
  const s = S.score; if (!s) return;
  const dir = $("#score-dir"); dir.textContent = s.direction === "long" ? "Long" : s.direction === "short" ? "Short" : "Neutral";
  dir.className = `score__dir ${s.direction === "long" ? "up" : s.direction === "short" ? "down" : "muted"}`;
  $("#score-head").textContent = `${s.headline} · Deutlichkeit ${s.rating}/100 (${s.band})`;
  $("#score-long").style.width = `${s.long_pct}%`; $("#score-long").textContent = `${s.long_pct.toFixed(0)}%`;
  $("#score-short").style.width = `${s.short_pct}%`; $("#score-short").textContent = `${s.short_pct.toFixed(0)}%`;
  $("#cards").innerHTML = s.cards.map(card).join("");
  $("#chart-cards").innerHTML = s.chart_cards.map(card).join("");
  // Bot-Rating im manuellen Fenster: dieselbe Zahl, keine zweite Rechnung.
  $("#r-long").style.width = `${s.long_pct}%`; $("#r-long").textContent = `${s.long_pct.toFixed(0)}%`;
  $("#r-short").style.width = `${s.short_pct}%`; $("#r-short").textContent = `${s.short_pct.toFixed(0)}%`;
  const hint = $("#r-hint"); hint.textContent = s.direction === "long" ? "Buy" : s.direction === "short" ? "Sell" : "Abwarten";
  hint.className = `rating__hint ${s.direction === "long" ? "up" : s.direction === "short" ? "down" : "muted"}`;
}

/* ------------------------------------------------------ Positionen & Co. -- */
async function tickPositions() {
  try {
    const [man, bot] = await Promise.all([api("/api/terminal/positions"), api("/api/portfolio/open")]);
    S.positions = man;
    S.botPositions = bot.map((p) => ({
      id: `bot-${p.symbol}`, symbol: p.symbol, side: p.side, qty: p.qty, entry: p.entry_price ?? p.entry, leverage: p.leverage,
      margin: p.margin, tp: p.target, sl: p.stop, opened_ts: p.opened_ts, last: p.last_price ?? p.last, unrealized: p.unrealised ?? p.unrealized ?? 0,
      position_size: (p.qty ?? 0) * (p.entry_price ?? p.entry ?? 0), source: "bot",
    }));
  } catch (e) { /* alte Werte bleiben */ }
  renderBottom(); renderChart();
}
async function tickHistory() {
  try { S.history = await api("/api/terminal/history?limit=50"); } catch (e) { /* bleibt */ }
  if (S.tab === "history") renderBottom();
}
function renderBottom() {
  const host = $("#btable");
  if (S.tab === "positions") {
    const all = [...S.botPositions, ...S.positions];
    if (!all.length) { host.innerHTML = `<p class="empty">Keine offene Position. Der Bot entscheidet auf M15-Schluss; manuell: rechts „Manual“.</p>`; return; }
    host.innerHTML = `<div class="pos__head"><span>Asset</span><span>Position Size</span><span>Margin</span><span>In</span><span>Quelle</span><span>LVG</span><span>TP / SL</span><span>Unrealized PNL</span><span>Close</span></div>` +
      all.map((p) => {
        const side = String(p.side).toLowerCase().startsWith("l") ? 1 : -1;
        const tpUsd = p.tp ? (p.tp - p.entry) * p.qty * side : null, slUsd = p.sl ? (p.sl - p.entry) * p.qty * side : null;
        return `<div class="pos__row">
          <span>${p.symbol} <span class="${side > 0 ? "up" : "down"}">${side > 0 ? "Long" : "Short"}</span></span>
          <span>${money(p.position_size, 0)} USD</span><span>${money(p.margin ?? 0, 0)} USD</span><span>${px(p.entry)}</span>
          <span class="muted">${p.source === "bot" ? "Bot" : "Manuell"}</span><span>${(p.leverage ?? 1).toFixed(0)}x</span>
          <div class="tpsl"><span class="up">${p.tp ? `${px(p.tp)} <small>(${signed(tpUsd, 0)} USD / ${pct(((p.tp - p.entry) / p.entry) * 100 * side)})</small>` : "–"}</span>
            <span class="down">${p.sl ? `${px(p.sl)} <small>(${signed(slUsd, 0)} USD / ${pct(((p.sl - p.entry) / p.entry) * 100 * side)})</small>` : "–"}</span></div>
          <span class="${(p.unrealized ?? 0) >= 0 ? "up" : "down"}">${signed(p.unrealized ?? 0)} USD</span>
          <span>${p.source === "manuell" ? `<button class="btn-link" data-close="${p.id}">Market</button>` : `<span class="muted" title="vom Bot gefuehrt">Bot</span>`}</span>
        </div>`;
      }).join("");
    $$("button[data-close]", host).forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true; b.textContent = "…";
      try { await api(`/api/terminal/positions/${b.dataset.close}/close`, { method: "POST" }); await tickPositions(); await tickHistory(); await tickAccount(); }
      catch (e) { b.disabled = false; b.textContent = "Market"; flash($("#m-msg"), e.message, "err"); }
    }));
  } else if (S.tab === "alerts") {
    const mine = S.alerts.filter((a) => true);
    host.innerHTML = `<p class="empty">Preisalarm: Werkzeug „Messen“ wählen und in den Chart klicken, oder <button class="btn-link" id="al-add">beim aktuellen Kurs setzen</button>. Benachrichtigung im Browser, wenn der Kurs die Linie kreuzt.</p>` +
      (mine.length ? `<div class="hist__head" style="grid-template-columns:110px 120px 1fr 120px 60px"><span>Asset</span><span>Preis</span><span>Zustand</span><span>gesetzt</span><span></span></div>` +
        mine.map((a) => `<div class="hist__row" style="grid-template-columns:110px 120px 1fr 120px 60px"><span>${a.symbol}</span><span>${px(a.price)}</span><span class="${a.fired ? "up" : "muted"}">${a.fired ? `ausgelöst ${clock(a.firedAt)}` : "wartet"}</span><span class="muted">${day(a.created)}</span><button class="btn-link" data-al="${a.id}">x</button></div>`).join("") : "");
    $("#al-add")?.addEventListener("click", () => { if (S.head) addAlert(S.head.last); if ("Notification" in window && Notification.permission === "default") Notification.requestPermission(); });
    $$("button[data-al]", host).forEach((b) => b.addEventListener("click", () => { S.alerts = S.alerts.filter((a) => String(a.id) !== b.dataset.al); saveAlerts(); renderBottom(); renderChart(); }));
  } else {
    if (!S.history.length) { host.innerHTML = `<p class="empty">Noch kein abgeschlossener Trade unter dieser Konfiguration.</p>`; return; }
    host.innerHTML = `<div class="hist__head"><span>Asset</span><span>Mode</span><span>In</span><span>Out</span><span>Position Size</span><span>LVG</span><span>TP / SL</span><span>Realized PNL</span><span>Befund</span></div>` +
      S.history.map((t) => {
        const side = String(t.side).toLowerCase().startsWith("l") ? 1 : -1;
        return `<div class="hist__row" title="${t.verdict ?? ""}">
          <span>${t.symbol} <span class="${side > 0 ? "up" : "down"}">${side > 0 ? "Long" : "Short"}</span></span>
          <span class="muted">${t.source === "bot" ? "Bot" : "Manuell"}</span><span>${px(t.entry)}</span><span>${px(t.exit)}</span>
          <span>${t.position_size ? `${money(t.position_size, 0)} USD` : "–"}</span><span>${t.leverage ? `${Number(t.leverage).toFixed(0)}x` : "–"}</span>
          <div class="tpsl"><span class="up">${t.tp ? px(t.tp) : "–"}</span><span class="down">${t.sl ? px(t.sl) : "–"}</span></div>
          <span class="${(t.net_pnl ?? 0) >= 0 ? "up" : "down"}">${signed(t.net_pnl ?? 0)} USD <small class="muted">${(t.r_multiple ?? 0).toFixed(2)} R</small></span>
          <span class="muted">${t.exit_reason ?? ""}${t.stopped_by_wick ? " · Docht" : ""}${t.max_favourable_r ? ` · best +${t.max_favourable_r.toFixed(2)} R` : ""}</span>
        </div>`;
      }).join("");
  }
}

/* ------------------------------------------------------------ Account -- */
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
    drawEquity($("#a-chart"), a.series, a.range);
  } catch (e) { $("#a-note").textContent = `Konto: ${e.message}`; }
}

/* ------------------------------------------------------- Bot-Einstellungen -- */
async function loadSettings() {
  try {
    S.settings = await api("/api/terminal/bot-settings");
    const s = S.settings;
    $("#bs-margin").value = s.initial_margin_usd; $("#bs-margin-pct").value = s.margin_pct; $("#bs-margin-val").textContent = `${s.margin_pct}% von ${money(s.balance, 0)} USD`;
    $("#bs-maxlev").setAttribute("aria-checked", String(s.max_leverage)); $("#bs-lev").value = s.leverage;
    $("#bs-maxloss").value = s.max_loss_pct; $("#bs-minloss").value = s.min_loss_pct;
    $("#bs-maxrisk").setAttribute("aria-checked", String(s.always_max_risk));
    $("#bs-fixcrv").setAttribute("aria-checked", String(s.fix_crv)); $("#bs-crv").value = s.crv;
    $("#bs-auto").setAttribute("aria-checked", String(s.auto_trader));
    $("#bs-rating").value = s.min_bot_rating; $("#bs-rating-note").textContent = s.wirkung.min_bot_rating;
    $("#m-avail").textContent = `Avlb: ${money(s.balance)} USD`;
    if (!$("#m-margin").value) { $("#m-margin").value = Math.round(s.balance); $("#m-margin-pct").value = 100; }
    updateManualSummary();
  } catch (e) { flash($("#bs-msg"), `Einstellungen: ${e.message}`, "err"); }
}
function wireSettings() {
  $$(".switch").forEach((sw) => sw.addEventListener("click", () => sw.setAttribute("aria-checked", String(sw.getAttribute("aria-checked") !== "true"))));
  $("#bs-margin-pct").addEventListener("input", (e) => { const s = S.settings; if (!s) return; $("#bs-margin").value = Math.round(s.balance * e.target.value / 100); $("#bs-margin-val").textContent = `${e.target.value}% von ${money(s.balance, 0)} USD`; });
  $("#bs-margin").addEventListener("input", (e) => { const s = S.settings; if (!s) return; const p = Math.max(1, Math.min(100, Math.round(e.target.value / s.balance * 100))); $("#bs-margin-pct").value = p; $("#bs-margin-val").textContent = `${p}% von ${money(s.balance, 0)} USD`; });
  $("#bs-apply").addEventListener("click", async (e) => {
    const btn = e.currentTarget; btn.setAttribute("aria-busy", "true"); btn.textContent = "Wird angewendet…";
    const body = {
      initial_margin_usd: Number($("#bs-margin").value), margin_pct: Number($("#bs-margin-pct").value),
      max_leverage: $("#bs-maxlev").getAttribute("aria-checked") === "true", leverage: Number($("#bs-lev").value),
      max_loss_pct: Number($("#bs-maxloss").value), min_loss_pct: Number($("#bs-minloss").value),
      always_max_risk: $("#bs-maxrisk").getAttribute("aria-checked") === "true",
      fix_crv: $("#bs-fixcrv").getAttribute("aria-checked") === "true", crv: Number($("#bs-crv").value),
      auto_trader: $("#bs-auto").getAttribute("aria-checked") === "true", min_bot_rating: Number($("#bs-rating").value),
    };
    try { const r = await api("/api/terminal/bot-settings", { method: "POST", body: JSON.stringify(body) }); flash($("#bs-msg"), `Angewendet. ${r.schritte.join(" ")}`, "ok"); await loadSettings(); }
    catch (err) { flash($("#bs-msg"), err.message, "err"); }
    finally { btn.removeAttribute("aria-busy"); btn.textContent = "Apply"; }
  });
}

/* --------------------------------------------------------- Manuell handeln -- */
function updateManualSummary() {
  const h = S.head; if (!h) return;
  const margin = Number($("#m-margin").value || 0), lev = Number($("#m-lev").value || 1);
  const pos = margin * lev, qty = pos / h.last, fees = pos * 0.0005;
  $("#m-lev-badge").textContent = `${lev}X`;
  const tp = Number($("#m-tp").value), sl = Number($("#m-sl").value), side = S.side === "long" ? 1 : -1;
  $("#m-tp-pct").textContent = tp ? pct(((tp - h.last) / h.last) * 100 * side, 2) : "%";
  $("#m-sl-pct").textContent = sl ? pct(((sl - h.last) / h.last) * 100 * side, 2) : "%";
  $("#m-summary").innerHTML = `<span>Price: ${px(h.last)} USD</span><span>Margin: ${money(margin, 0)} USD</span><span>Position: ${money(pos, 0)} USD (${qty.toFixed(4)})</span><span>Fees: ${money(fees)} USD</span>` +
    (tp ? `<span class="up">TP ${px(tp)} → ${signed((tp - h.last) * qty * side, 0)} USD</span>` : "") + (sl ? `<span class="down">SL ${px(sl)} → ${signed((sl - h.last) * qty * side, 0)} USD</span>` : "");
  const btn = $("#m-submit"); btn.textContent = S.side === "long" ? "Kauf" : "Verkauf"; btn.className = `cta ${S.side === "long" ? "cta--buy" : "cta--sell"}`;
}
function wireManual() {
  $$(".ls button").forEach((b) => b.addEventListener("click", () => { S.side = b.dataset.side; $$(".ls button").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); updateManualSummary(); }));
  ["#m-margin", "#m-lev", "#m-tp", "#m-sl"].forEach((id) => $(id).addEventListener("input", updateManualSummary));
  $("#m-margin-pct").addEventListener("input", (e) => { if (S.settings) { $("#m-margin").value = Math.round(S.settings.balance * e.target.value / 100); $("#m-margin-val").textContent = `${e.target.value}%`; updateManualSummary(); } });
  $("#m-submit").addEventListener("click", async (e) => {
    const btn = e.currentTarget; const msg = $("#m-msg");
    const body = {
      symbol: S.symbol, side: S.side, margin_usd: Number($("#m-margin").value), leverage: Number($("#m-lev").value),
      tp: $("#m-tp-on").getAttribute("aria-checked") === "true" && $("#m-tp").value ? Number($("#m-tp").value) : null,
      sl: $("#m-sl-on").getAttribute("aria-checked") === "true" && $("#m-sl").value ? Number($("#m-sl").value) : null,
    };
    if (!(body.margin_usd > 0)) { flash(msg, "Margin fehlt.", "err"); $("#m-margin").focus(); return; }
    btn.setAttribute("aria-busy", "true");
    try { const r = await api("/api/terminal/order", { method: "POST", body: JSON.stringify(body) }); flash(msg, `Papier-Order gefüllt bei ${px(r.entry)} (${r.qty.toFixed(4)}).`, "ok"); await tickPositions(); S.tab = "positions"; syncTabs(); }
    catch (err) { flash(msg, err.message, "err"); }
    finally { btn.removeAttribute("aria-busy"); }
  });
}

/* ---------------------------------------------------------------- Shell -- */
function flash(el, text, kind) { el.textContent = text; el.className = `msg ${kind}`; }
function setView(v) {
  S.view = v;
  $$("[data-view]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === v)));
  $("#view-chart").classList.toggle("hidden", v !== "chart");
  $("#view-bot").classList.toggle("hidden", v !== "bot");
  $("#view-account").classList.toggle("hidden", v !== "account");
  if (v === "chart") renderChart();
  if (v === "bot") tickScore();
  if (v === "account") tickAccount();
}
function setMode(m) {
  S.mode = m; $$("[data-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === m)));
  $("#side-bot").classList.toggle("hidden", m !== "bot"); $("#side-manual").classList.toggle("hidden", m !== "manual");
}
function syncTabs() { $$("#btabs [data-tab]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.tab === S.tab))); renderBottom(); }
function wireShell() {
  $$("[data-view]").forEach((b) => b.addEventListener("click", () => { setView(b.dataset.view); if (S.page !== "trade") setPage("trade", false); }));
  $$("[data-mode]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  $$("[data-page]").forEach((b) => b.addEventListener("click", () => setPage(b.dataset.page)));
  $$("#btabs [data-tab]").forEach((b) => b.addEventListener("click", () => { S.tab = b.dataset.tab; syncTabs(); }));
  $$("#tf [data-tf]").forEach((b) => b.addEventListener("click", () => { S.tf = b.dataset.tf; $$("#tf [data-tf]").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); loadMarket(); }));
  $$("#a-range [data-range]").forEach((b) => b.addEventListener("click", () => { S.range = b.dataset.range; $$("#a-range [data-range]").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); tickAccount(); }));
  $("#sym").addEventListener("change", (e) => { S.symbol = e.target.value; S.lastOb = null; loadMarket(); tickHead(); tickBook(); tickScore(); renderBottom(); });
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    if (e.key === "1") setView("chart"); if (e.key === "2") setView("bot"); if (e.key === "3") setPage("account");
    if (e.key === "m") setMode("manual"); if (e.key === "b") setMode("bot");
  });
}
function setPage(p, toggleView = true) {
  S.page = p; $$("[data-page]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.page === p)));
  if (p === "account") setView("account"); else if (toggleView) setView("chart");
}

async function boot() {
  const syms = await api("/api/market").catch(() => ["BTCUSDT"]);
  $("#sym").innerHTML = syms.map((s) => `<option value="${s}">${s.replace("USDT", "/USDT")}</option>`).join("");
  $("#sym").value = S.symbol;
  wireShell(); wireChart(); wireSettings(); wireManual();
  setView("chart"); setMode("bot"); syncTabs();
  await Promise.all([tickHead(), loadMarket(), tickBook(), tickCalendar(), tickScore(), tickPositions(), tickHistory(), loadSettings()]);
  setInterval(() => { tickHead(); tickBook(); checkAlerts(); }, 1000);
  setInterval(() => { loadMarket(); tickPositions(); }, 15000);
  setInterval(() => { tickScore(); tickHistory(); }, 30000);
  setInterval(tickCalendar, 15 * 60 * 1000);
  setInterval(() => { if (S.view === "account") tickAccount(); }, 60000);
}
boot();
