/**
 * Darstellung des Charts und die Leiste darunter -- die TradingView-Bedienung,
 * die nur das Aussehen aendert und nie eine Zahl.
 *
 *   - Charttyp, Gitter, Sitzungswechsel, Countdown, Hoch/Tief  (Fenster "Darstellung")
 *   - Preisskala: Prozent, Log, Invertiert, Auto              (Fussleiste rechts)
 *   - Bereichsknoepfe 1T .. 5J                                (Fussleiste links)
 *   - Seitenleisten einklappen, Vollbild, Screenshot          (Kopf der Mitte)
 *   - Vergleich mit einem zweiten Markt                       (Fenster "Darstellung")
 *
 * Alles wird in localStorage gemerkt; faellt der aus (privates Fenster),
 * startet die Ansicht mit den Vorgaben und nichts bricht.
 */

const SPEICHER = "dw-ansicht";

export const VORGABE = {
  typ: "kerzen", gitter: true, sitzungen: true, countdown: true, hochTief: false,
  magnet: false, dauerZeichnen: false, vergleich: "",
  skala: { modus: "normal", invert: false },
  links: true, rechts: true,
};

export const TYPEN = {
  kerzen: "Kerzen", hohl: "Hohle Kerzen", balken: "Balken (OHLC)", ha: "Heikin-Ashi",
  linie: "Linie", flaeche: "Fläche", baseline: "Baseline",
};

//: Die Bereichsknoepfe: welche Zeitebene und wie viele Kerzen. Begrenzt auf
//: die Ebenen, die das Projekt speichert (W1 bis M15) und auf die 600
//: Kerzen, die der Chart laedt.
export const BEREICHE = {
  "1T": { tf: "M15", kerzen: 96, name: "1 Tag" },
  "5T": { tf: "H1", kerzen: 120, name: "5 Tage" },
  "1M": { tf: "H4", kerzen: 180, name: "1 Monat" },
  "3M": { tf: "D1", kerzen: 92, name: "3 Monate" },
  "1J": { tf: "D1", kerzen: 365, name: "1 Jahr" },
  "5J": { tf: "W1", kerzen: 260, name: "5 Jahre" },
};

export const TF_MS = { M15: 900_000, H1: 3_600_000, H4: 14_400_000, D1: 86_400_000, W1: 604_800_000 };

/** Wann die laufende Kerze dieser Ebene schliesst (UTC-Gitter, Wochen ab Montag). */
export function naechsterSchluss(tf, jetzt = Date.now()) {
  const takt = TF_MS[tf]; if (!takt) return null;
  const versatz = tf === "W1" ? 4 * 86_400_000 : 0;
  return (Math.floor((jetzt - versatz) / takt) + 1) * takt + versatz;
}

export function ladeAnsicht() {
  try {
    const roh = JSON.parse(localStorage.getItem(SPEICHER) || "{}") || {};
    return { ...VORGABE, ...roh, skala: { ...VORGABE.skala, ...(roh.skala ?? {}) } };
  } catch { return structuredClone(VORGABE); }
}

export function merkeAnsicht(A) {
  try { localStorage.setItem(SPEICHER, JSON.stringify(A)); } catch { /* egal */ }
}

const schalter = (key, label, an, hinweis = "") =>
  `<button type="button" class="lay" role="checkbox" data-an="${key}" aria-checked="${an}">
     <span class="lay__box" aria-hidden="true"></span><span>${label}${hinweis ? ` <small class="muted">${hinweis}</small>` : ""}</span></button>`;

/** Inhalt des Fensters "Darstellung". Neu gebaut nur beim Oeffnen. */
export function darstellungMarkup(A, maerkte) {
  return `
    <div class="pop__gruppe"><div class="pop__titel">Charttyp</div>
      <div class="typwahl" role="radiogroup" aria-label="Charttyp">
        ${Object.entries(TYPEN).map(([k, n]) =>
          `<button type="button" role="radio" data-typ="${k}" aria-checked="${A.typ === k}">${n}</button>`).join("")}
      </div>
      ${A.typ === "ha" ? `<p class="pop__hinweis">Heikin-Ashi glättet nur die Darstellung. Preisschild, Linien und Indikatoren rechnen mit echten Kursen.</p>` : ""}
    </div>
    <div class="pop__gruppe"><div class="pop__titel">Anzeige</div>
      ${schalter("gitter", "Gitterlinien", A.gitter)}
      ${schalter("sitzungen", "Sitzungswechsel", A.sitzungen, "UTC-Tag / Woche")}
      ${schalter("countdown", "Countdown bis Kerzenschluss", A.countdown)}
      ${schalter("hochTief", "Hoch / Tief im Fenster", A.hochTief)}
    </div>
    <div class="pop__gruppe"><div class="pop__titel">Zeichnen</div>
      ${schalter("magnet", "Magnet", A.magnet, "rastet auf O/H/L/C")}
      ${schalter("dauerZeichnen", "Werkzeug aktiv lassen", A.dauerZeichnen)}
    </div>
    <div class="pop__gruppe"><div class="pop__titel">Vergleich</div>
      <label class="pop__feld"><span>Markt</span>
        <select data-vergleich aria-label="Vergleichsmarkt">
          <option value="">— keiner —</option>
          ${maerkte.map((m) => `<option value="${m}" ${A.vergleich === m ? "selected" : ""}>${m.replace("USDT", "/USDT")}</option>`).join("")}
        </select></label>
      <p class="pop__hinweis">Auf den ersten sichtbaren Schluss normiert: beide starten am selben Punkt.</p>
    </div>`;
}

/** Fussleiste: Bereichsknoepfe, Zur-Echtzeit, Uhr, Skalenschalter. */
export function fussMarkup() {
  return `
    <div class="fuss__links" role="group" aria-label="Zeitbereich">
      ${Object.entries(BEREICHE).map(([k, b]) =>
        `<button type="button" data-bereich="${k}" title="${b.name} (${b.tf})">${k}</button>`).join("")}
    </div>
    <button type="button" class="fuss__echtzeit" id="zur-echtzeit" hidden title="Zur letzten Kerze (Alt+R setzt alles zurück)">Zur Echtzeit
      <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3 2.5 6.5 6 3 9.5M7.5 2.5 11 6 7.5 9.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
    <span class="fuss__uhr" id="fuss-uhr" title="Ortszeit des Browsers">–</span>
    <div class="fuss__rechts" role="group" aria-label="Preisskala">
      <button type="button" data-skala="prozent" title="Prozent-Skala (Alt+P)">%</button>
      <button type="button" data-skala="log" title="Logarithmische Skala (Alt+L)">log</button>
      <button type="button" data-skala="invert" title="Skala umdrehen (Alt+I)">inv</button>
      <button type="button" data-skala="auto" title="Automatische Skala; Preisachse ziehen streckt, Doppelklick auf die Achse setzt zurück">auto</button>
    </div>`;
}

/** Zustand der Fussleiste setzen (Knoepfe gedrueckt / nicht). */
export function fussZeigen(A, streckung, verschoben) {
  const fuss = document.querySelector("#chart-fuss"); if (!fuss) return;
  for (const b of fuss.querySelectorAll("[data-skala]")) {
    const k = b.dataset.skala;
    const an = k === "auto" ? (streckung ?? 1) === 1
      : k === "invert" ? !!A.skala.invert : A.skala.modus === k;
    b.setAttribute("aria-pressed", String(an));
  }
  const echt = fuss.querySelector("#zur-echtzeit");
  if (echt) echt.hidden = !verschoben;
}

/** Uhr in der Fussleiste, mit Zeitzone -- wie bei TradingView. */
export function uhrTick() {
  const el = document.querySelector("#fuss-uhr"); if (!el) return;
  const d = new Date();
  const off = -d.getTimezoneOffset() / 60;
  const zwei = (v) => String(v).padStart(2, "0");
  el.textContent = `${zwei(d.getHours())}:${zwei(d.getMinutes())}:${zwei(d.getSeconds())} (UTC${off >= 0 ? "+" : ""}${off})`;
}

/** Seitenleisten ein-/ausklappen. Ueber Custom Properties am Raster. */
export function seitenZeigen(A) {
  const term = document.querySelector("#view-markt"); if (!term) return;
  // Offen = Eigenschaft entfernen, damit die Spaltenbreite der jeweiligen
  // Bildschirmbreite aus dem Stylesheet gilt (300 / 250-280 px).
  for (const [k, an] of [["--links", A.links], ["--rechts", A.rechts]]) {
    if (an) term.style.removeProperty(k); else term.style.setProperty(k, "0px");
  }
  term.toggleAttribute("data-links-zu", !A.links);
  term.toggleAttribute("data-rechts-zu", !A.rechts);
  for (const [sel, an] of [["#btn-links", A.links], ["#btn-rechts", A.rechts]]) {
    const b = document.querySelector(sel);
    if (b) { b.setAttribute("aria-pressed", String(!an)); b.title = `${an ? "Ausblenden" : "Einblenden"}: ${sel === "#btn-links" ? "linke" : "rechte"} Seitenleiste`; }
  }
}

/** Vollbild fuer die Markt-Ansicht (TradingView: Umschalt+F). */
export async function vollbild() {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.documentElement.requestFullscreen();
  } catch { /* Browser verweigert -- dann eben nicht */ }
}

/**
 * Screenshot des Charts als PNG, mit Kopfzeile (Markt, Ebene, Zeit).
 * Die HTML-Ueberlagerungen (Legende, Linienschilder) sind nicht auf der
 * Leinwand; die Kopfzeile ersetzt das Wichtigste davon.
 */
export function screenshot(canvas, symbol, tf, legende) {
  const ratio = window.devicePixelRatio || 1;
  const kopf = 28 * ratio;
  const bild = document.createElement("canvas");
  bild.width = canvas.width; bild.height = canvas.height + kopf;
  const ctx = bild.getContext("2d");
  ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--ground").trim() || "#07090d";
  ctx.fillRect(0, 0, bild.width, bild.height);
  ctx.drawImage(canvas, 0, kopf);
  ctx.scale(ratio, ratio);
  ctx.font = '600 13px "Segoe UI", system-ui, sans-serif';
  ctx.fillStyle = "#e8edf5"; ctx.textBaseline = "middle";
  const zeit = new Date().toLocaleString("de-CH");
  ctx.fillText(`${symbol.replace("USDT", "/USDT")} · ${tf} · ${zeit}`, 10, 14);
  ctx.font = '11px ui-monospace, Menlo, monospace'; ctx.fillStyle = "#9aa7bb";
  ctx.fillText(legende.slice(0, 140), 260, 14);
  bild.toBlob((blob) => {
    if (!blob) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    const d = new Date(), zwei = (v) => String(v).padStart(2, "0");
    a.download = `${symbol}-${tf}-${d.getFullYear()}${zwei(d.getMonth() + 1)}${zwei(d.getDate())}-${zwei(d.getHours())}${zwei(d.getMinutes())}.png`;
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }, "image/png");
}
