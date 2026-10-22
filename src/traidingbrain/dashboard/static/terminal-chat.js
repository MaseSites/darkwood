/**
 * Darkwood Terminal -- Seitenfeld "Bot fragen".
 *
 * Claude antwortet in Worten; das Urteil kommt allein aus der Regelpruefung
 * des Servers. Darum stammt JEDE Zahl auf einer Karte aus der Karte selbst
 * (urteil.regeln, urteil.order, vorschlag) und nie aus Claudes Text.
 * "Ausfuehren" gibt es nur auf einer angenommenen Karte, solange sie gilt;
 * was danach passiert, sagt der Server, nicht diese Datei.
 *
 * Blick (Markt, Zeitebene): terminal.js feuert `terminal:blick` bei jedem
 * Laden des Charts; beim Start liest das Feld ihn aus der Kopfzeile.
 */
import { fmt } from "/static/terminal-chart.js";

const API = "/api/terminal/chat";
const STATUS_TAKT_MS = 60_000;

// Dieselben Formate wie in terminal.js (dort nicht exportiert).
const money = (v, d = 2) => (v ?? 0).toLocaleString("de-CH", { minimumFractionDigits: d, maximumFractionDigits: d });
const px = (v) => fmt(v ?? 0);
const uhrzeit = (ts) => new Date(ts).toLocaleTimeString("de-CH", { hour: "2-digit", minute: "2-digit" });

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const STATUS_SATZ = {
  bereit: "Claude bereit",
  nicht_angemeldet: "Claude nicht angemeldet",
  nicht_installiert: "Claude-CLI fehlt",
  unbekannt: "Status unbekannt",
  fehler: "Status nicht abrufbar",
};
const STATUS_HINWEIS = {
  nicht_angemeldet: "Claude ist auf diesem Rechner nicht angemeldet. Im Terminal einmal <code>claude</code> starten und anmelden. Bis dahin prüft das",
  nicht_installiert: "Die Claude-CLI ist auf diesem Rechner nicht installiert, Fragen an Claude gehen darum nicht. Einen Trade prüft trotzdem das",
  unbekannt: "Ob Claude antworten kann, ist nicht bekannt. Einen Trade prüft ohne Claude das",
  fehler: "Der Status von Claude ist nicht abrufbar. Einen Trade prüft ohne Claude das",
};
const ZEICHEN = { erfuellt: "✓", verletzt: "✕", unbekannt: "?" };

const C = {
  offen: false, symbol: "BTCUSDT", timeframe: "M15", modus: "chat", claude: null,
  ausstehend: 0, seite: "long", geladen: false, uhrTakt: null,
};

/* ------------------------------------------------------------ Abrufe -- */
async function rufe(pfad, opts = {}) {
  const r = await fetch(API + pfad, { headers: { "Content-Type": "application/json" }, ...opts });
  let body = null;
  try { body = await r.json(); } catch { /* kein JSON */ }
  if (!r.ok) {
    const fehler = new Error(typeof body?.detail === "string" ? body.detail : `Fehler ${r.status}`);
    fehler.status = r.status;
    throw fehler;
  }
  return body;
}
const sende = (pfad, daten) => rufe(pfad, { method: "POST", body: daten === undefined ? undefined : JSON.stringify(daten) });

/* -------------------------------------------------------------- Blick -- */
function blickAusKopfzeile() {
  const sym = $("#sym")?.value;
  const tf = $('#tf [aria-pressed="true"]')?.dataset.tf;
  if (sym) C.symbol = sym;
  if (tf) C.timeframe = tf;
}
function zeigeBlick() {
  const s = C.symbol.endsWith("USDT") ? `${C.symbol.slice(0, -4)}/USDT` : C.symbol;
  $("#chat-blick").innerHTML = `${esc(s)} · ${esc(C.timeframe)} <span class="muted">· Manuelles Papierkonto</span>`;
  const feld = $("#cf-symbol");
  if (feld && !feld.dataset.geaendert) feld.value = C.symbol;
}

/* ------------------------------------------------------------- Status -- */
async function ladeStatus() {
  let s;
  try { s = (await rufe("/status")).claude; } catch { s = "fehler"; }
  C.claude = s;
  const el = $("#chat-status");
  el.dataset.claude = s;
  $("#chat-status-text").textContent = STATUS_SATZ[s] ?? STATUS_SATZ.unbekannt;
  const hinweis = $("#chat-hinweis");
  if (s === "bereit") { hinweis.hidden = true; hinweis.innerHTML = ""; return; }
  hinweis.innerHTML = `${STATUS_HINWEIS[s] ?? STATUS_HINWEIS.unbekannt} <button type="button" class="btn-link" data-zum-formular>Formular</button> &ndash; mit denselben Regeln.`;
  hinweis.hidden = false;
}

/* ----------------------------------------------------------- Verlauf -- */
function leerePruefen() {
  const v = $("#chat-verlauf");
  const leer = $(".chat__leer", v);
  if (v.children.length > (leer ? 1 : 0)) leer?.remove();
}
function anhaengen(el) {
  const v = $("#chat-verlauf");
  const unten = v.scrollHeight - v.scrollTop - v.clientHeight < 40;
  v.append(el);
  leerePruefen();
  if (unten || el.classList.contains("msg-n")) v.scrollTop = v.scrollHeight;
}
function knoten(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}
function nutzerNachricht(text, ts) {
  return knoten(`<div class="msg-n">${esc(text)}<div class="msg__zeit">${uhrzeit(ts)}</div></div>`);
}
function bedenkenListe(bedenken) {
  if (!bedenken?.length) return "";
  return `<ul class="bedenken" aria-label="Bedenken">${bedenken.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>`;
}
function botNachricht({ text, fehler, bedenken, ts, mitBedenken = true }) {
  if (fehler) {
    // Nie als normale Antwort zeigen: was Claude schrieb, liess sich nicht lesen.
    const roh = text ? `\n${esc(text)}` : "";
    return knoten(`<div class="msg-b msg-b--fehler"><span class="msg__marke">Antwort nicht lesbar</span>${esc(fehler)}${roh}<div class="msg__zeit">${uhrzeit(ts)}</div></div>`);
  }
  if (!text) return null;
  return knoten(`<div class="msg-b"><span class="msg__marke">Bot</span>${esc(text)}${mitBedenken ? bedenkenListe(bedenken) : ""}<div class="msg__zeit">${uhrzeit(ts)}</div></div>`);
}
function systemZeile(text, fehler = false) {
  return knoten(`<p class="msg-s${fehler ? " err" : ""}" role="status">${esc(text)}</p>`);
}

/* ------------------------------------------------------------- Karte -- */
function vorschlagZeile(karte) {
  const o = karte.urteil?.order;
  const v = karte.vorschlag ?? {};
  const q = o ?? v;
  const seite = q.side === "short" ? `<span class="down">Short</span>` : `<span class="up">Long</span>`;
  const teile = [`<b>${esc(q.symbol ?? v.symbol)}</b>`, seite];
  teile.push(q.margin_usd != null ? `${money(q.margin_usd)} USD` : "Margin offen");
  teile.push(q.leverage != null ? `${money(q.leverage, 0)}x` : "Hebel offen");
  const stopVomBot = karte.urteil?.stop_vom_bot ? " (vom Bot)" : "";
  teile.push(q.sl != null ? `SL ${px(q.sl)}${stopVomBot}` : "ohne SL");
  if (q.tp != null) teile.push(`TP ${px(q.tp)}`);
  return teile.join(" · ");
}
function regelZeile(r, abgelehnt) {
  const hinweis = abgelehnt && r.status !== "erfuellt" && r.hinweis ? `<span class="regel-c__hinweis">${esc(r.hinweis)}</span>` : "";
  return `<li class="regel-c" data-status="${esc(r.status)}">
    <span class="regel-c__z" aria-label="${esc(r.status)}">${ZEICHEN[r.status] ?? "?"}</span>
    <span class="regel-c__name">${esc(r.nr)}. ${esc(r.name)}</span>
    <span class="regel-c__wert">${esc(r.wert)}</span>
    <span class="regel-c__grenze">Grenze ${esc(r.grenze)}</span>${hinweis}
  </li>`;
}
function karteKnoten(karte, bedenken = []) {
  const u = karte.urteil ?? {};
  const ja = !!u.angenommen;
  const regeln = [...(u.regeln ?? [])].sort((a, b) => a.nr - b.nr);
  const offen = regeln.filter((r) => r.status !== "erfuellt").length;
  const unter = ja ? "alle acht Regeln erfüllt" : `${offen} von ${regeln.length} Regeln nicht erfüllt`;
  const preis = u.preis != null ? `Kurs bei Prüfung <span class="num">${px(u.preis)}</span>` : "Kurs bei Prüfung unbekannt";
  const el = knoten(`<section class="karte" data-urteil="${ja ? "angenommen" : "abgelehnt"}" data-id="${esc(karte.id)}" aria-label="Prüfkarte">
    <div class="karte__vorschlag">${vorschlagZeile(karte)}<br>${preis}</div>
    <div class="karte__urteil"><span>${ja ? "Angenommen" : "Abgelehnt"}</span><small>${unter}</small></div>
    <ol class="regeln-c">${regeln.map((r) => regelZeile(r, !ja)).join("")}</ol>
    ${ja ? bedenkenListe(bedenken) : ""}
    ${ja ? `<div class="karte__fuss"><span class="karte__uhr" aria-live="off"></span><button type="button" class="karte__ausfuehren">Ausführen</button></div>` : ""}
    <p class="karte__ergebnis" aria-live="polite"></p>
  </section>`);
  if (ja) {
    el.dataset.ablauf = String(karte.laeuft_ab_ts);
    if (karte.ausgefuehrt_ts != null) {
      el.dataset.fertig = "true";
      const id = String(karte.order_id ?? "");
      if (id.startsWith("fehlgeschlagen")) zeigeErgebnis(el, { ok: false, html: `Order ${esc(id)}` });
      else if (!id || id === "ausstehend") zeigeErgebnis(el, { ok: false, html: "Ausführung begonnen, Ergebnis unbekannt" });
      else zeigeErgebnis(el, { ok: true, html: `Ausgeführt · Order <span class="num">${esc(id)}</span>` });
    }
    $(".karte__ausfuehren", el).addEventListener("click", () => ausfuehren(el));
    uhrStellen(el);
  }
  return el;
}
function zeigeErgebnis(el, { ok, html }) {
  const p = $(".karte__ergebnis", el);
  p.className = `karte__ergebnis ${ok ? "ok" : "err"}`;
  p.innerHTML = html;
}
function uhrStellen(el) {
  const knopf = $(".karte__ausfuehren", el);
  const uhr = $(".karte__uhr", el);
  if (!knopf || !uhr) return;
  if (el.dataset.fertig === "true") { knopf.disabled = true; uhr.textContent = ""; return; }
  const rest = Number(el.dataset.ablauf) - Date.now();
  if (rest <= 0) {
    knopf.disabled = true;
    uhr.textContent = "Abgelaufen";
    uhr.dataset.knapp = "false";
    return;
  }
  const s = Math.ceil(rest / 1000);
  uhr.textContent = `gilt noch ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  uhr.dataset.knapp = String(s <= 60);
  if (el.dataset.laeuft !== "true") knopf.disabled = false;
}
function uhrenTick() { $$("#chat .karte[data-ablauf]").forEach(uhrStellen); }

async function ausfuehren(el) {
  if (el.dataset.laeuft === "true" || el.dataset.fertig === "true") return;
  const knopf = $(".karte__ausfuehren", el);
  el.dataset.laeuft = "true";
  knopf.disabled = true;
  knopf.setAttribute("aria-busy", "true");
  knopf.textContent = "Wird ausgeführt …";
  try {
    const r = await sende(`/ausfuehren/${encodeURIComponent(el.dataset.id)}`);
    if (r.ausgefuehrt) {
      el.dataset.fertig = "true";
      const o = r.order ?? {};
      zeigeErgebnis(el, { ok: true, html: `Ausgeführt · Order <span class="num">${esc(o.id)}</span> · Einstieg <span class="num">${px(o.entry)}</span>` });
    } else {
      zeigeErgebnis(el, { ok: false, html: `Nicht ausgeführt: ${esc(r.grund ?? "ohne Grund")}` });
    }
  } catch (e) {
    // 409 schon ausgefuehrt / 410 abgelaufen / 502 Order gescheitert: die Karte
    // ist danach nicht mehr ausfuehrbar; 404 und Netzfehler ebenso wenig sicher.
    if ([409, 410, 502].includes(e.status)) el.dataset.fertig = "true";
    zeigeErgebnis(el, { ok: false, html: `Nicht ausgeführt: ${esc(e.message)}` });
  } finally {
    el.dataset.laeuft = "false";
    knopf.removeAttribute("aria-busy");
    knopf.textContent = "Ausführen";
    uhrStellen(el);
  }
}

/* ------------------------------------------------------------ Senden -- */
function denkt(delta) {
  C.ausstehend = Math.max(0, C.ausstehend + delta);
  $("#chat-denkt").hidden = C.ausstehend === 0;
}
async function frageClaude(text) {
  const ts = Date.now();
  const bubble = nutzerNachricht(text, ts);
  anhaengen(bubble);
  denkt(+1);
  try {
    const r = await sende("/nachricht", { text, symbol: C.symbol, timeframe: C.timeframe });
    const bot = botNachricht({ text: r.antwort, fehler: r.fehler, bedenken: r.bedenken, ts: Date.now(), mitBedenken: !r.karte });
    if (bot) anhaengen(bot);
    if (r.karte) anhaengen(karteKnoten(r.karte, r.bedenken));
    if (!bot && !r.karte) anhaengen(systemZeile("Keine Antwort erhalten."));
  } catch (e) {
    if (e.status === 409) {
      bubble.dataset.zurueck = "true";
      const feld = $("#chat-text");
      if (!feld.value) feld.value = text;
      anhaengen(systemZeile("Claude antwortet noch auf die vorige Frage. Die Nachricht steht wieder im Eingabefeld.", true));
    } else {
      anhaengen(systemZeile(`Nicht beantwortet: ${e.message}`, true));
    }
    if (e.status !== 409) ladeStatus();
  } finally {
    // Jede Anfrage zaehlt beim Senden +1 und bei ihrer Antwort -1, auch eine
    // mit 409. "Claude denkt" bleibt also nur an, solange eine Anfrage DIESER
    // Seite offen ist; laeuft die blockierende in einem anderen Fenster, zeigt
    // diese Seite sie nicht an.
    denkt(-1);
  }
}
function zahl(id) {
  const v = $(id).value.trim().replace(",", ".");
  return v === "" ? null : Number(v);
}
async function pruefeFormular(ev) {
  ev.preventDefault();
  const msg = $("#cf-msg");
  const daten = {
    symbol: $("#cf-symbol").value.trim() || C.symbol,
    side: C.seite,
    margin_usd: zahl("#cf-margin"),
    leverage: zahl("#cf-hebel"),
    sl: zahl("#cf-sl"),
    tp: zahl("#cf-tp"),
    timeframe: C.timeframe,
  };
  const kaputt = Object.entries(daten).find(([, v]) => typeof v === "number" && !Number.isFinite(v));
  if (kaputt) { msg.className = "msg err"; msg.textContent = "Bitte nur Zahlen eintragen."; return; }
  const knopf = $("#cf-pruefen");
  knopf.disabled = true;
  knopf.setAttribute("aria-busy", "true");
  msg.className = "msg";
  msg.textContent = "Wird geprüft …";
  try {
    const r = await sende("/pruefen", daten);
    msg.textContent = "";
    anhaengen(karteKnoten(r.karte));
    $("#chat-verlauf").scrollTop = $("#chat-verlauf").scrollHeight;
  } catch (e) {
    msg.className = "msg err";
    msg.textContent = `Nicht geprüft: ${e.message}`;
  } finally {
    knopf.disabled = false;
    knopf.removeAttribute("aria-busy");
  }
}

/* ------------------------------------------------------- Verlauf laden -- */
async function ladeVerlauf() {
  if (C.geladen) return;
  C.geladen = true;
  try {
    const zeilen = await rufe("/verlauf");
    for (const z of zeilen) {
      if (z.rolle === "nutzer") anhaengen(nutzerNachricht(z.text, z.ts));
      else {
        const b = botNachricht({ text: z.text, ts: z.ts });
        if (b) anhaengen(b);
      }
      if (z.karte) anhaengen(karteKnoten(z.karte));
    }
    const v = $("#chat-verlauf");
    v.scrollTop = v.scrollHeight;
  } catch (e) {
    C.geladen = false;
    anhaengen(systemZeile(`Verlauf nicht geladen: ${e.message}`, true));
  }
}

/* ------------------------------------------------------ Oeffnen/Modus -- */
function setzeModus(m) {
  C.modus = m;
  $$("#chat-modus [data-modus]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.modus === m)));
  $("#chat-form").hidden = m !== "chat";
  $("#chat-formular").hidden = m !== "formular";
  (m === "chat" ? $("#chat-text") : $("#cf-margin")).focus({ preventScroll: true });
}
function oeffne(an) {
  C.offen = an;
  const feld = $("#chat");
  feld.dataset.offen = String(an);
  feld.inert = !an;
  feld.setAttribute("aria-hidden", String(!an));
  $("#btn-chat").setAttribute("aria-expanded", String(an));
  if (an) {
    ladeStatus();
    ladeVerlauf();
    uhrenTick(); // sofort: keine abgelaufene Karte wirkt eine Sekunde lang ausfuehrbar
    if (!C.uhrTakt) C.uhrTakt = setInterval(uhrenTick, 1000);
    // visibility schaltet sofort um, darum laesst sich gleich fokussieren.
    (C.modus === "chat" ? $("#chat-text") : $("#cf-margin")).focus({ preventScroll: true });
  } else {
    clearInterval(C.uhrTakt);
    C.uhrTakt = null;
    $("#btn-chat").focus({ preventScroll: true });
  }
}

function verdrahte() {
  blickAusKopfzeile();
  zeigeBlick();
  document.addEventListener("terminal:blick", (e) => {
    if (e.detail?.symbol) C.symbol = e.detail.symbol;
    if (e.detail?.timeframe) C.timeframe = e.detail.timeframe;
    zeigeBlick();
  });

  $("#btn-chat").addEventListener("click", () => oeffne(!C.offen));
  $("#chat-zu").addEventListener("click", () => oeffne(false));
  $("#chat").addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); oeffne(false); } });

  $$("#chat-modus [data-modus]").forEach((b) => b.addEventListener("click", () => setzeModus(b.dataset.modus)));
  $("#chat-hinweis").addEventListener("click", (e) => { if (e.target.closest("[data-zum-formular]")) setzeModus("formular"); });

  const text = $("#chat-text");
  const hoehe = () => { text.style.height = "auto"; text.style.height = `${Math.min(text.scrollHeight + 2, 140)}px`; };
  text.addEventListener("input", hoehe);
  text.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#chat-form").requestSubmit(); }
  });
  $("#chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const t = text.value.trim();
    if (!t) return;
    text.value = "";
    hoehe();
    frageClaude(t);
  });

  $$("#chat-formular .ls [data-cseite]").forEach((b) => b.addEventListener("click", () => {
    C.seite = b.dataset.cseite;
    $$("#chat-formular .ls [data-cseite]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  }));
  $("#cf-symbol").addEventListener("input", (e) => { e.target.dataset.geaendert = "true"; });
  $("#chat-formular").addEventListener("submit", pruefeFormular);

  setInterval(() => { if (C.offen) ladeStatus(); }, STATUS_TAKT_MS);
}

verdrahte();
