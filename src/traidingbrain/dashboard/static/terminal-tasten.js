/**
 * Tastatur, Rechtsklick und die kleinen Eingabefenster -- TradingViews
 * Kuerzel, damit die Hand nicht umlernen muss.
 *
 * **Zwei bewusste Abweichungen von TradingView.** Ziffern wechseln dort die
 * Zeitebene; hier wechseln 1/2/3 seit jeher die Ansicht (Markt/Konto/Trades),
 * und das bleibt. Die Zeitebene kommt ueber das Komma -- das ist bei
 * TradingView die zweite Belegung derselben Funktion. Und Buchstaben
 * oeffnen nicht die Symbolsuche (m/b schalten den Modus); dafuer Strg+K.
 */

const KUERZEL = [
  ["Chart", [
    ["← / →", "eine Kerze verschieben"],
    ["Strg + ← / →", "ein Viertel des Fensters verschieben"],
    ["Strg + ↑ / ↓", "hinein / heraus zoomen"],
    ["Rad", "zoomen (rechter Rand bleibt)"],
    ["Strg + Rad", "zum Mauszeiger zoomen"],
    ["Umschalt + Rad", "seitwärts verschieben"],
    ["Preisachse ziehen", "Skala strecken; Doppelklick = auto"],
    ["Zeitachse ziehen", "Zeit strecken"],
    ["Alt + R", "Chart zurücksetzen"],
    ["Alt + G", "gehe zu Datum"],
    [",", "Zeitebene eingeben (15, 1h, 4h, d, w)"],
    ["Strg + K", "Markt suchen"],
    ["/", "Indikatoren"],
  ]],
  ["Skala", [
    ["Alt + L", "logarithmisch"],
    ["Alt + P", "Prozent"],
    ["Alt + I", "umdrehen"],
  ]],
  ["Zeichnen", [
    ["Alt + T", "Trendlinie"],
    ["Alt + H", "horizontale Linie"],
    ["Alt + V", "vertikale Linie"],
    ["Alt + C", "Kreuzlinie"],
    ["Alt + F", "Fibonacci"],
    ["Alt + Umschalt + R", "Rechteck"],
    ["Alt + A", "Preisalarm setzen"],
    ["Umschalt (2. Punkt)", "Trendlinie auf 0/45/90°"],
    ["Strg + Z / Strg + Y", "rückgängig / wiederholen"],
    ["Strg + Alt + H", "alle Zeichnungen aus/ein"],
    ["Esc", "zurück zum Fadenkreuz"],
  ]],
  ["Ansicht", [
    ["1 / 2 / 3", "Markt / Konto / Trades"],
    ["M / B", "Manual / Bot"],
    ["Umschalt + F", "Vollbild"],
    ["Alt + S", "Screenshot speichern"],
    ["Umschalt + →", "Replay: nächste Kerze"],
    ["?", "diese Übersicht"],
  ]],
];

const ZEICHEN_KUERZEL = { t: "trend", h: "hline", v: "vline", c: "kreuz", f: "fib", a: "alert" };

/** Die Zeitebene aus einer Eingabe wie TradingView sie annimmt. */
export function zeitebeneAus(text) {
  const t = String(text).trim().toLowerCase().replace(/\s+/g, "");
  const tabelle = {
    15: "M15", "15m": "M15", m15: "M15",
    60: "H1", 1: "H1", "1h": "H1", h: "H1", h1: "H1",
    240: "H4", 4: "H4", "4h": "H4", h4: "H4",
    d: "D1", "1d": "D1", d1: "D1", t: "D1", "1t": "D1",
    w: "W1", "1w": "W1", w1: "W1",
  };
  return tabelle[t] ?? null;
}

/** "21.10.2026 14:00", "21.10. 14:00", "2026-10-21", "21.10" -> ms (Ortszeit). */
export function datumAus(text) {
  const t = String(text).trim();
  let m = t.match(/^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?$/);
  if (m) return new Date(+m[1], +m[2] - 1, +m[3], +(m[4] ?? 0), +(m[5] ?? 0)).getTime();
  m = t.match(/^(\d{1,2})\.(\d{1,2})\.?(\d{2,4})?(?:\s+(\d{1,2}):(\d{2}))?$/);
  if (m) {
    const jahr = m[3] ? (m[3].length === 2 ? 2000 + +m[3] : +m[3]) : new Date().getFullYear();
    return new Date(jahr, +m[2] - 1, +m[1], +(m[4] ?? 0), +(m[5] ?? 0)).getTime();
  }
  return null;
}

/** Die Uebersicht der Kuerzel (?). */
export function hilfeMarkup() {
  return `<div class="hilfe__kasten" role="document">
    <div class="hilfe__kopf"><h2 id="hilfe-titel">Tastenkürzel</h2>
      <button type="button" class="hilfe__zu" data-hilfe-zu aria-label="Schliessen">Esc</button></div>
    <div class="hilfe__spalten">
      ${KUERZEL.map(([gruppe, zeilen]) => `<section><h3>${gruppe}</h3><dl>
        ${zeilen.map(([k, was]) => `<div><dt>${k.split(" + ").map((x) => `<kbd>${x}</kbd>`).join(" + ")}</dt><dd>${was}</dd></div>`).join("")}
      </dl></section>`).join("")}
    </div></div>`;
}

/**
 * Ein kleines Eingabefenster. Gibt den Text zurueck oder null (Esc).
 * Ersetzt `prompt()`, das im dunklen Terminal als weisser Systemdialog
 * aufblendet und den Fokus wegnimmt.
 */
export function frage({ titel, hinweis = "", vorgabe = "", pruefe }) {
  const box = document.querySelector("#eingabe");
  const feld = box.querySelector("#eingabe-feld");
  box.querySelector("#eingabe-titel").textContent = titel;
  const hin = box.querySelector("#eingabe-hinweis");
  hin.textContent = hinweis; hin.classList.remove("down");
  feld.value = vorgabe;
  box.hidden = false;
  feld.focus(); feld.select();
  return new Promise((fertig) => {
    const ende = (wert) => { box.hidden = true; feld.removeEventListener("keydown", taste); box.removeEventListener("click", klick); fertig(wert); };
    const taste = (e) => {
      if (e.key === "Escape") { e.preventDefault(); ende(null); }
      if (e.key === "Enter") {
        e.preventDefault();
        const fehler = pruefe?.(feld.value);
        if (fehler) { hin.textContent = fehler; hin.classList.add("down"); return; }
        ende(feld.value);
      }
    };
    const klick = (e) => { if (e.target === box) ende(null); };
    feld.addEventListener("keydown", taste);
    box.addEventListener("click", klick);
  });
}

/** Das Rechtsklick-Menue. `eintraege`: [{label, kuerzel, an, aktion}] oder "-". */
export function zeigeMenu(x, y, eintraege) {
  const m = document.querySelector("#ktx");
  m.innerHTML = eintraege.map((e, i) => e === "-"
    ? '<div class="ktx__trenner" role="separator"></div>'
    : `<button type="button" role="${e.an === undefined ? "menuitem" : "menuitemcheckbox"}" data-i="${i}"
         ${e.an === undefined ? "" : `aria-checked="${e.an}"`}>
         <span class="ktx__haken" aria-hidden="true">${e.an ? "✓" : ""}</span>
         <span>${e.label}</span><kbd>${e.kuerzel ?? ""}</kbd></button>`).join("");
  m.hidden = false;
  const r = m.getBoundingClientRect();
  m.style.left = `${Math.min(x, window.innerWidth - r.width - 6)}px`;
  m.style.top = `${Math.min(y, window.innerHeight - r.height - 6)}px`;
  m.querySelector("button")?.focus();
  const zu = () => { m.hidden = true; document.removeEventListener("pointerdown", aussen, true); document.removeEventListener("keydown", taste, true); };
  const aussen = (e) => { if (!m.contains(e.target)) zu(); };
  const taste = (e) => {
    const knoepfe = [...m.querySelectorAll("button")];
    const i = knoepfe.indexOf(document.activeElement);
    if (e.key === "Escape") { e.preventDefault(); zu(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); knoepfe[(i + 1) % knoepfe.length]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); knoepfe[(i - 1 + knoepfe.length) % knoepfe.length]?.focus(); }
  };
  m.onclick = (e) => {
    const b = e.target.closest("button[data-i]"); if (!b) return;
    zu(); eintraege[+b.dataset.i].aktion?.();
  };
  document.addEventListener("pointerdown", aussen, true);
  document.addEventListener("keydown", taste, true);
}

/**
 * Alle Kuerzel an einer Stelle. `T` sind die Handgriffe aus terminal.js.
 * Gibt true zurueck, wenn die Taste verbraucht wurde.
 */
export function taste(e, T) {
  const imFeld = ["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName) || e.target.isContentEditable;
  if (imFeld) return false;
  if (!document.querySelector("#eingabe").hidden || !document.querySelector("#ktx").hidden) return false;
  const hilfe = document.querySelector("#hilfe");
  if (!hilfe.hidden) {
    if (e.key === "Escape" || e.key === "?") { hilfe.hidden = true; e.preventDefault(); return true; }
    return false;
  }
  const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  const strg = e.ctrlKey || e.metaKey;

  if (e.key === "?") { T.hilfe(); return true; }
  if (strg && !e.altKey && k === "k") { T.symbolsuche(); return true; }
  if (strg && !e.altKey && k === "z" && !e.shiftKey) { T.rueckgaengig(); return true; }
  if (strg && !e.altKey && (k === "y" || (k === "z" && e.shiftKey))) { T.wiederholen(); return true; }
  if (strg && e.altKey && k === "h") { T.ausblenden(); return true; }
  if (e.shiftKey && !strg && !e.altKey && k === "f") { T.vollbild(); return true; }

  if (T.ansicht() !== "markt") return false;

  if (e.altKey && !strg) {
    if (e.shiftKey && k === "r") { T.werkzeug("rect"); return true; }
    if (k === "r") { T.zuruecksetzen(); return true; }
    if (k === "g") { T.gehezu(); return true; }
    if (k === "l") { T.skala("log"); return true; }
    if (k === "p") { T.skala("prozent"); return true; }
    if (k === "i") { T.skala("invert"); return true; }
    if (k === "s") { T.foto(); return true; }
    if (ZEICHEN_KUERZEL[k]) { T.werkzeug(ZEICHEN_KUERZEL[k]); return true; }
    return false;
  }
  if (e.shiftKey && e.key === "ArrowRight" && T.replaySchritt()) return true;
  if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
    T.schiebe(e.key === "ArrowLeft" ? -1 : 1, strg);
    return true;
  }
  if (strg && (e.key === "ArrowUp" || e.key === "ArrowDown")) { T.zoome(e.key === "ArrowUp" ? 1 / 1.25 : 1.25); return true; }
  if (e.key === "," && !strg) { T.zeitebene(); return true; }
  if (e.key === "/" && !strg) { T.indikatoren(); return true; }
  if (e.key === "Escape") { T.werkzeug("cross"); return false; }
  return false;
}
