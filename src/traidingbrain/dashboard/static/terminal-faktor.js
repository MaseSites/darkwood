/* Die Aufschlüsselung eines Faktors, als Markup.
 *
 * Reine Funktionen: hinein geht, was `/api/terminal/faktor/{symbol}/{key}`
 * liefert, heraus kommt HTML. Kein Zustand, kein Abruf, keine Rechnung — die
 * Gewichte kommen fertig aus der Engine, und diese Datei darf keine eigenen
 * erfinden. Jede Zahl, die hier entstünde, wäre eine zweite Wahrheit neben
 * dem Rating, das daneben steht.
 *
 * Der Grund für die eigene Datei: `terminal.js` hat 1 244 Zeilen, und die
 * Darstellung einer Tabelle braucht nichts davon.
 */

const SHELL = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => SHELL[c]);

const RICHTUNG_KLASSE = { long: "up", short: "down", neutral: "muted" };
const RICHTUNG_WORT = { long: "Long", short: "Short", neutral: "neutral" };

function sterne(n) {
  return `<span class="fakt__sterne" title="${n} von 5">${"★".repeat(n)}<span class="fakt__leer">${"★".repeat(5 - n)}</span></span>`;
}

/* Ein Gewichtsteil als Zeile. Der Wert steht vorn, der Grund daneben —
 * nicht als Tooltip: ein Grund, den man nur mit der Maus findet, ist für
 * jemanden mit Tastatur nicht da. */
function teil(t) {
  const auffaellig = Math.abs(t.wert - 1) > 0.001;
  return `<li class="fakt__teil${auffaellig ? " fakt__teil--wirkt" : ""}">
    <span class="fakt__teilname">${esc(t.name)}</span>
    <span class="fakt__teilwert">×${t.wert.toFixed(2)}</span>
    <span class="fakt__teilgrund">${esc(t.grund)}</span></li>`;
}

function unterfaktor(u, i) {
  const kl = RICHTUNG_KLASSE[u.richtung] ?? "muted";
  const id = `fkt-${i}`;
  const schwach = u.schwaechen.length
    ? `<ul class="fakt__schwach">${u.schwaechen.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>`
    : "";
  const abstand = u.abstand_atr != null ? ` · ${u.abstand_atr.toFixed(2)} ATR entfernt` : "";
  const alter = u.frische_kerzen != null ? ` · ${u.frische_kerzen} Kerzen alt` : "";
  return `<div class="fakt__zeile${u.zaehlt ? "" : " fakt__zeile--aus"}">
    <button class="fakt__kopf" aria-expanded="false" aria-controls="${id}">
      <span class="fakt__name">${esc(u.label)}</span>
      <span class="fakt__meta">${esc(u.familie)} · ${esc(u.zeitebene)}</span>
      ${sterne(u.sterne)}
      <span class="fakt__gewicht" title="Familie × Regime × Zeitebene × Unabhängigkeit × Frische">${u.gewicht.toFixed(3)}</span>
      <span class="fakt__richtung ${kl}">${RICHTUNG_WORT[u.richtung] ?? u.richtung}</span>
    </button>
    <div class="fakt__auf" id="${id}" hidden>
      <div class="fakt__wert">Messwert <b>${esc(u.wert)}</b> · Stärke ${(u.staerke * 100).toFixed(0)} %${abstand}${alter} · Quelle ${esc(u.quelle)}</div>
      ${u.grund_nicht ? `<p class="fakt__aus">${esc(u.grund_nicht)}</p>` : ""}
      <ul class="fakt__teile">${u.teile.map(teil).join("")}</ul>
      ${schwach ? `<div class="fakt__schwachkopf">Bekannte Schwächen dieser Messung</div>${schwach}` : ""}
    </div></div>`;
}

function familie(f) {
  const kl = RICHTUNG_KLASSE[f.richtung] ?? "muted";
  return `<tr class="${f.zerfallen ? "fakt__fam--aus" : ""}">
    <td>${esc(f.familie)}</td>
    <td class="${kl}">${RICHTUNG_WORT[f.richtung] ?? f.richtung}</td>
    <td>${(f.staerke * 100).toFixed(0)} %</td>
    <td>${(f.einigkeit * 100).toFixed(0)} %</td>
    <td>${(f.ebenen_einigkeit * 100).toFixed(0)} %</td>
    <td>${f.mitglieder}</td>
    <td>${f.grundgewicht.toFixed(2)}${f.regime_faktor !== 1 ? ` <span class="fakt__mod">× ${f.regime_faktor.toFixed(2)}</span>` : ""}</td>
    <td class="${f.beitrag > 0 ? "up" : f.beitrag < 0 ? "down" : "muted"}">${f.beitrag.toFixed(3)}</td>
    <td class="fakt__famgrund">${esc(f.grund)}</td></tr>`;
}

export function faktorHtml(d) {
  if (!d.gemessen && !d.unterfaktoren.length) {
    return `<div class="fakt__box"><div class="fakt__titel">${esc(d.label)}</div>
      <p class="fakt__erkl">${esc(d.erklaerung)}</p>
      <p class="fakt__keine">${esc(d.hinweis)}</p></div>`;
  }

  const famTabelle = d.familien.length
    ? `<table class="fakt__fam"><thead><tr>
        <th>Familie</th><th>Richtung</th><th>Stärke</th><th>Einigkeit</th>
        <th>Ebenen</th><th>Mitglieder</th><th>Gewicht</th><th>Beitrag</th><th>Begründung</th>
      </tr></thead><tbody>${d.familien.map(familie).join("")}</tbody></table>`
    : "";

  const kontext = d.kontext.length
    ? `<div class="fakt__kontextkopf">Gemessen, aber ohne Stimme</div>
       <ul class="fakt__kontext">${d.kontext.map((k) =>
         `<li><b>${esc(k.label)}</b> ${esc(k.wert)} <span class="muted">(${esc(k.zeitebene)})</span> — ${esc(k.grund)}</li>`).join("")}</ul>`
    : "";

  return `<div class="fakt__box">
    <div class="fakt__titel">${esc(d.label)}${d.regime ? ` <span class="fakt__regime">Regime ${esc(d.regime)}</span>` : ""}
      <button class="fakt__zu" aria-label="Aufschlüsselung schließen">×</button></div>
    <p class="fakt__erkl">${esc(d.erklaerung)}</p>
    ${d.rechenweg ? `<p class="fakt__weg">${esc(d.rechenweg)}</p>` : ""}
    ${famTabelle}
    <div class="fakt__listekopf">${esc(d.hinweis)}</div>
    <div class="fakt__liste">${d.unterfaktoren.map(unterfaktor).join("")}</div>
    ${kontext}</div>`;
}

/* Klicks innerhalb der Aufschlüsselung. Delegiert, weil die Liste bei jedem
 * Faktorwechsel neu entsteht — ein Handler auf den Knöpfen selbst wäre nach
 * dem ersten Wechsel an abgetrennten Knoten hängen geblieben. Genau dieser
 * Fehler hat am 20.10. das Ebenen-Panel bei jedem Klick geschlossen. */
export function wireFaktor(box, beimSchliessen) {
  box.addEventListener("click", (e) => {
    const zu = e.target.closest(".fakt__zu");
    if (zu) { beimSchliessen(); return; }
    const kopf = e.target.closest(".fakt__kopf");
    if (!kopf) return;
    const auf = box.querySelector(`#${kopf.getAttribute("aria-controls")}`);
    if (!auf) return;
    const offen = kopf.getAttribute("aria-expanded") === "true";
    kopf.setAttribute("aria-expanded", String(!offen));
    auf.hidden = offen;
  });
}
