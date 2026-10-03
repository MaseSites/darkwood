/* traidingBrain — confirmation surface.
 *
 * No build step and no framework. This is an internal instrument with one screen
 * and one decision on it; a bundler and a component tree would be more machinery
 * than the thing they serve.
 *
 * Two behaviours carry the safety argument:
 *
 * The confirm button must be *held*, not clicked. An order that cannot be undone
 * should not be reachable by a stray click or a double-tap, and the 1.2 seconds
 * are long enough that the hand notices what it is doing.
 *
 * The token is fetched at the moment the hold completes, never earlier. The server
 * re-prices against the live market before issuing one, so a proposal that has
 * gone stale refuses at exactly the point where it matters instead of having been
 * quietly pre-authorised while the user was reading.
 */

import { drawChart, candleReadout } from "/static/chart.js";

const HOLD_MS = 1200;
const POLL_MS = 4000;

const state = {
  proposals: [],
  /* The score, and which symbol and bar it belongs to.
   *
   * Kept beside the chart rather than inside it because it arrives later: the
   * indicator bank over five timeframes takes about ten seconds the first time
   * a market is opened, and waiting for it would put the chart behind it. The
   * two stamps are how a late answer for a market nobody is looking at any
   * more gets thrown away instead of drawn. */
  score: null,
  scoreFor: null,
  system: null,
  notices: new Map(),
  changed: new Map(),
  /* True while a confirm button is being held.
   *
   * The poll re-renders the list, which replaces the button element and kills
   * the hold timer with it. Found by actually holding the button: a poll landing
   * inside the 1.2 seconds silently cancelled the gesture, so roughly one
   * confirmation in three would have done nothing and the user would have held
   * it again. Deferring one poll is the cheaper side of that trade. */
  holding: false,
  /* The result of the last confirmation, kept outside the proposal list.
   *
   * A confirmed proposal stops being pending, so it leaves the list -- and an
   * outcome attached to it would leave with it. Holding a button for over a
   * second and then watching the ticket silently vanish is the worst possible
   * feedback for an irreversible action. */
  outcome: null,
  /* Chart payloads, keyed by proposal id and timeframe.
   *
   * Cached because they cannot change: the bars end at the decision and the
   * levels were captured with it. Re-fetching on every four-second poll would
   * re-read a parquet file to redraw an identical picture -- and switching back
   * to a timeframe already looked at should be instant, because that is what
   * comparing two of them means. */
  charts: new Map(),
  /* Which timeframe each proposal is currently being viewed on. Kept out of the
   * DOM so the four-second poll does not throw away the one the user chose. */
  timeframe: new Map(),
  /* The market view: which symbol and timeframe, and the payload.
   *
   * Kept beside the proposals rather than inside them, because it outlives
   * them -- the market is there whether or not anything was proposed. */
  symbols: null,
  /* When the current analysis started, or null when nothing is loading.
   * Only used to print elapsed seconds: a wait somebody can see the length of
   * is a different wait from one that might be broken. */
  loadingSince: null,
  symbol: null,
  marketTimeframe: null,
  market: null,
  /* Which proposal's chart the pointer is over, and where. Kept out of the DOM
   * so a re-render does not lose it mid-inspection.
   *
   * deliberate-ignore no-active-state -- the checker reads source rather than
   * rendered CSS and matches this identifier as a `:hover` rule. Every pressable
   * element here has an `:active`: app.css styles .stepper button, .btn and
   * .chart__tab on press. Checked, not waived. */
  hover: null,
};

const fmt = {
  price(value) {
    const digits = value >= 1000 ? 2 : value >= 1 ? 4 : 6;
    return value.toLocaleString("en-US", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  },
  money(value) {
    return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
  },
  pct(value) {
    return `${(value * 100).toFixed(2)}%`;
  },
  qty(value) {
    return value.toLocaleString("en-US", { maximumFractionDigits: 6 });
  },
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = response.status === 204 ? null : await response.json();
  if (!response.ok) {
    throw new Error(body?.detail ?? `request failed (${response.status})`);
  }
  return body;
}

/* ------------------------------------------------------------ the ladder -- */

/**
 * The price axis, with a broken scale.
 *
 * The first version was linear over the whole range, and it did not work. Because
 * leverage is derived to keep liquidation several stop-distances away, the trade
 * itself occupies about one percent of price while liquidation sits ten percent
 * below. On one linear scale the three levels that matter collapse into a smudge
 * and their labels overlap, which defeats the only reason the drawing exists.
 *
 * So the axis is broken, the way an engineering drawing breaks a long shaft: the
 * trade zone is drawn to scale in the upper region, a visible break marks the
 * discontinuity, and liquidation sits below it with its real distance printed.
 * The break is drawn rather than hidden, because a silently compressed axis is a
 * chart that lies about proportion -- and this particular proportion is the whole
 * question.
 */
function ladder(p) {
  const H = 260;
  const axisX = 40;
  const top = 18;
  const breakAt = 176;
  const liqY = 232;

  const trade = [p.entry, p.stop, p.target];
  const hi = Math.max(...trade);
  const lo = Math.min(...trade);
  const pad = (hi - lo) * 0.28 || 1;
  const ceiling = hi + pad;
  const floor = lo - pad;

  // Linear, but only across the trade itself, where proportion is readable.
  const y = (price) => top + ((ceiling - price) / (ceiling - floor)) * (breakAt - top);

  const marks = [
    { price: p.target, colour: "var(--long)", label: "target", y: y(p.target) },
    { price: p.entry, colour: "var(--text)", label: "entry", y: y(p.entry) },
    { price: p.stop, colour: "var(--short)", label: "stop", y: y(p.stop) },
  ];

  const band = (from, to, colour) =>
    `<line class="band" x1="${axisX}" x2="${axisX}" y1="${y(from)}" y2="${y(
      to
    )}" stroke="${colour}" />`;

  // Labels sit above or below their mark depending on room, so a tight stop and
  // entry do not print on top of each other.
  const rows = marks
    .map((m, i) => {
      const next = marks[i + 1];
      const crowded = next && next.y - m.y < 26;
      const dy = crowded ? -4 : 4;
      return `
      <line class="mark" x1="${axisX - 8}" x2="${axisX + 8}" y1="${m.y}" y2="${
        m.y
      }" stroke="${m.colour}" />
      <text class="value" x="${axisX + 14}" y="${m.y + dy}" fill="${m.colour}">${fmt.price(
        m.price
      )}</text>
      <text x="${axisX + 14}" y="${m.y + dy + 12}">${m.label}</text>`;
    })
    .join("");

  const gap = fmt.pct(Math.abs(p.stop - p.liquidation_price) / p.stop);

  return `
    <svg class="ladder" viewBox="0 0 200 ${H}" role="img"
         aria-label="Price ladder. Target ${fmt.price(p.target)}, entry ${fmt.price(
    p.entry
  )}, stop ${fmt.price(p.stop)}. Liquidation ${fmt.price(
    p.liquidation_price
  )}, ${p.liquidation_buffer_r.toFixed(1)} stop distances beyond the stop.">
      ${band(p.entry, p.target, "var(--long)")}
      ${band(p.stop, p.entry, "var(--short)")}
      <line class="axis" x1="${axisX}" x2="${axisX}" y1="${top}" y2="${breakAt}" />
      ${rows}

      <!-- The break: the axis is not continuous here, and says so. -->
      <path class="axis-break" d="M${axisX - 7} ${breakAt + 6} l14 -5 M${axisX - 7} ${
        breakAt + 13
      } l14 -5" />
      <text class="gap" x="${axisX + 14}" y="${breakAt + 14}">${gap} of room</text>

      <line class="axis dashed" x1="${axisX}" x2="${axisX}" y1="${breakAt + 20}" y2="${liqY}" />
      <line class="mark" x1="${axisX - 8}" x2="${axisX + 8}" y1="${liqY}" y2="${liqY}"
            stroke="var(--liq)" />
      <text class="value" x="${axisX + 14}" y="${liqY + 4}" fill="var(--liq)">${fmt.price(
        p.liquidation_price
      )}</text>
      <text x="${axisX + 14}" y="${liqY + 16}">liquidation</text>
    </svg>`;
}

/* -------------------------------------------------------------- figures -- */

function figure(label, value, sub, modifier, changed) {
  return `
    <div class="figure ${modifier ? `figure--${modifier}` : ""}" data-changed="${changed ? "true" : "false"}">
      <dt>${label}</dt>
      <dd>${value}${sub ? `<small>${sub}</small>` : ""}</dd>
    </div>`;
}


/* ------------------------------------------------------- the market view -- */

/**
 * The market, drawn whether or not there is a trade in it.
 *
 * The ticket below answers "is this a good trade". This answers "what is
 * happening", which is the question someone actually spends time with -- most
 * hours have no setup, and a screen only worth opening when one appears is a
 * screen nobody learns the market on.
 *
 * It reuses the same renderer as the proposal chart on purpose. Two drawings of
 * one market would disagree eventually, and the disagreement would be invisible:
 * both would look plausible, and this screen would quietly teach a different
 * reading than the one the trades are made on.
 */
function marketPanel() {
  const view = state.market;
  if (view === "unavailable") {
    return `<div class="placeholder"><h2>Keine Marktdaten</h2>
      <p>Für die verfolgten Märkte ist noch nichts geladen.</p>
      <p class="placeholder__fix">Holen mit: <code>python scripts/backfill.py BTCUSDT --since 2023-01-01</code></p></div>`;
  }
  if (!view) {
    // A wait somebody can see the length of is a different wait. The first read
    // of a symbol builds five timeframes of structure, zones and gaps, and
    // saying so turns twenty silent seconds into twenty explained ones.
    const seconds = state.loadingSince
      ? Math.round((Date.now() - state.loadingSince) / 1000)
      : 0;
    return `<div class="placeholder">
      <span class="pulse"></span>
      <p>Analysiere ${escapeHtml(short(state.symbol ?? ""))} über fünf Zeitebenen&hellip;</p>
      <p class="placeholder__fix">Struktur, Zonen, Fair Value Gaps und Liquidität.
        Beim ersten Mal pro Markt etwa 25 Sekunden &mdash; danach sofort.
        ${seconds > 2 ? `<b>${seconds}s</b>` : ""}</p>
    </div>`;
  }

  const change =
    view.candles.length > 1
      ? ((view.candles.at(-1).close - view.candles[0].open) / view.candles[0].open) * 100
      : 0;

  return `
  <header class="market__head">
    <span class="market__price num">${fmt.price(view.price)}</span>
    <span class="market__change num ${change >= 0 ? "up" : "down"}">
      ${change >= 0 ? "+" : ""}${change.toFixed(2)}%
    </span>
    <span class="market__atr">ATR ${(view.atr_pct * 100).toFixed(2)}%</span>

    ${freshness(view)}
    ${ratingChip()}

    <span class="head-spacer"></span>

    <span class="chart__tabs" role="tablist" aria-label="Timeframe">
      ${(view.available_timeframes ?? [])
        .map(
          (tf) => `<button type="button" role="tab" data-act="mtf" data-tf="${tf}"
                     aria-selected="${tf === view.timeframe}"
                     class="chart__tab${tf === view.timeframe ? " chart__tab--on" : ""}">${tf}</button>`
        )
        .join("")}
    </span>
  </header>

  <figure class="chart chart--market">
    <figcaption class="chart__head">
      <span class="chart__readout" data-readout="market">${escapeHtml(
        candleReadout(view, view.candles.length - 1)
      )}</span>
      ${view.levels_hidden ? `<span class="chart__hidden">${view.levels_hidden} weitere nicht gezeichnet</span>` : ""}
    </figcaption>
    <canvas class="chart__canvas" data-canvas="market"
            role="img"
            aria-label="Candlestick chart of ${escapeHtml(view.symbol)} on ${escapeHtml(
              view.timeframe
            )}, with the levels and structural events the analysis found."></canvas>
  </figure>

  ${scorePanel()}
  ${setupPanel(view.setups)}
  ${gatePanel(view.gate)}
  ${frameTable(view)}

  <p class="chart__note">${escapeHtml(view.note)}</p>`;
}

/**
 * Which of the guide's setups fire on this bar.
 *
 * Above the gate, because when one fires this is the answer and the gate is the
 * working. Each row carries the whole trade: a screen that says "Setup C fired"
 * and not where the stop goes has given away the interesting half and kept the
 * half that decides whether to take it.
 *
 * Nothing here is an instruction. Two setups can fire at once and disagree, and
 * the guide is explicit that they are separate models rather than one strategy,
 * so they are listed rather than ranked.
 */
function setupPanel(setups) {
  if (!setups?.length) return "";
  const rows = setups
    .map(
      (s) => `<li class="setup setup--${escapeHtml(s.side)}${
        s.economic === false ? " setup--costly" : ""
      }">
        <span class="setup__key">${escapeHtml(s.key)}</span>
        <span class="setup__name">${escapeHtml(s.name)}
          <span class="setup__source">${escapeHtml(s.source)}</span></span>
        <span class="setup__side">${escapeHtml(s.side)}</span>
        <dl class="setup__plan">
          <div><dt>Entry</dt><dd class="num">${fmt.price(s.entry)}</dd></div>
          <div><dt>Stop</dt><dd class="num down">${fmt.price(s.stop)}</dd></div>
          <div><dt>Ziel</dt><dd class="num up">${fmt.price(s.target)}</dd></div>
          <div><dt>CRV</dt><dd class="num">${s.reward_risk.toFixed(2)}</dd></div>
        </dl>
        ${
          s.economic === false
            ? `<p class="setup__block">Stop nur ${(s.stop_distance * 100).toFixed(2)} % entfernt
                 &mdash; Gebühren fressen mehr vom Risiko als erlaubt. Wird nicht gehandelt.</p>`
            : ""
        }
        <ul class="setup__why">${(s.reasons ?? [])
          .map((r) => `<li>${escapeHtml(r)}</li>`)
          .join("")}</ul>
      </li>`
    )
    .join("");

  return `
  <section class="setups" aria-live="polite">
    <h2 class="setups__head">${setups.length === 1 ? "Ein Setup" : `${setups.length} Setups`} nach deinen Regeln</h2>
    <ul class="setups__list">${rows}</ul>
  </section>`;
}

/**
 * Why there is no trade right now.
 *
 * The point of the whole screen. Most hours have no setup, and a screen that
 * simply stays quiet through them cannot be told apart from a broken one — so
 * the conditions are read out on every poll, with the numbers behind each.
 *
 * Passing conditions are stated as plainly as failing ones. A panel that only
 * listed what refused would make the gate look like an obstacle course rather
 * than a description of the market, and the useful information is usually how
 * close the bar came.
 */
/**
 * Every indicator at once, reconciled into something a person can read.
 *
 * Two numbers rather than one, because the difference between them destroys
 * the part that matters: a market where a strong bullish read is fighting a
 * strong bearish one, and a quiet market with a mild lean, produce the same
 * subtraction and are not the same trade.
 *
 * Each family shows what every timeframe said underneath it. Without that row
 * a family reading near zero is unreadable -- "barely leaning" and "the week
 * is up while the hour is down" look identical, and only the second is a
 * reason to wait rather than to shrug.
 */
/**
 * The overall number, in the market header where it is always on screen.
 *
 * It rates how clear the picture is, never how likely a win -- so the
 * direction has to sit next to it or the number reads as a forecast. Ninety
 * pointing down is a clean short, and a chip showing only "90" would be read
 * as ninety per cent of something.
 */
/**
 * How old the newest analysed bar is.
 *
 * This exists because a frozen screen and a working one looked identical. The
 * collector runs on a machine that is sometimes off, the dashboard reads what
 * is on disk, and for an hour the only way to find out that nothing had
 * arrived since Tuesday was to ask. A number that does not move is either a
 * quiet market or a broken pipe, and the screen owes an answer to which.
 *
 * Silent while the data is current. A badge that is always lit is furniture.
 */
function freshness(view) {
  if (!view.stale) return "";
  return `<span class="stale" role="status">
    Daten ${ago(view.behind_ms)} alt &mdash; nichts Neues kommt an</span>`;
}

function ago(ms) {
  const minutes = Math.round(ms / 60000);
  if (minutes < 90) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h`;
  return `${Math.round(hours / 24)} Tage`;
}

function ratingChip() {
  const score = state.score;
  if (!score || score === "unavailable") {
    return `<span class="rating rating--waiting" title="wird berechnet">
      <b class="num">&mdash;</b><span class="rating__of">/100</span></span>`;
  }
  return `<span class="rating rating--${ratingTone(score.rating)}"
     title="Wie eindeutig das Bild ist &mdash; keine Wahrscheinlichkeit">
    <b class="num">${score.rating}</b><span class="rating__of">/100</span>
    <span class="rating__band">${escapeHtml(score.band)}</span>
  </span>`;
}

function ratingTone(value) {
  if (value >= 60) return "high";
  if (value >= 40) return "mid";
  return "low";
}

function scorePanel() {
  const score = state.score;
  if (score === "unavailable") return "";
  if (!score) {
    return `<section class="score score--waiting">
      <h3 class="score__head">Gesamtbild <span class="pulse"></span></h3>
      <p class="score__wait">Rechne 42 Indikatoren über fünf Zeitebenen&hellip;</p>
    </section>`;
  }

  const total = score.bullish + score.bearish;
  const upShare = total > 0 ? (score.bullish / total) * 100 : 50;
  // Bars are scaled against the loudest family rather than against a fixed
  // maximum. The absolute numbers are small by design -- a family has to clear
  // two kinds of disagreement before it contributes anything -- and a fixed
  // scale would draw every honest reading as a flat line.
  const loudest = Math.max(0.05, ...score.families.map((f) => Math.abs(f.contribution)));

  const families = score.families
    .map((f) => {
      const share = Math.abs(f.contribution) / loudest;
      const side = f.contribution >= 0 ? "up" : "down";
      const frames = f.frames
        .map(
          (frame) => `<span class="score__frame ${frame.lean >= 0 ? "up" : "down"}"
             title="${escapeHtml(frame.label)}">${escapeHtml(frame.label)}
             <b class="num">${frame.lean >= 0 ? "+" : ""}${frame.lean.toFixed(2)}</b></span>`
        )
        .join("");
      return `<li class="score__family${f.silent ? " score__family--silent" : ""}">
        <span class="score__fam">${escapeHtml(f.label)}
          <span class="score__members">${f.members}</span></span>
        <span class="score__gauge" aria-hidden="true">
          <i class="score__fill score__fill--${side}"
             style="--share:${share.toFixed(3)}"></i>
        </span>
        <span class="score__num num ${side}">${f.contribution >= 0 ? "+" : ""}${f.contribution.toFixed(
          3
        )}</span>
        <span class="score__frames">${frames}</span>
        ${f.reason ? `<span class="score__reason">${escapeHtml(f.reason)}</span>` : ""}
      </li>`;
    })
    .join("");

  const parts = score.parts
    .map(
      (p) => `<li class="score__part${p.weakest ? " score__part--weak" : ""}">
        <span class="score__part-label">${escapeHtml(p.label)}</span>
        <span class="score__part-gauge" aria-hidden="true">
          <i style="--share:${p.value.toFixed(3)}"></i></span>
        <span class="score__part-num num">${Math.round(p.value * 100)}</span>
      </li>`
    )
    .join("");
  const weakest = score.parts.find((p) => p.weakest);

  return `
  <section class="score" aria-live="polite">
    <h3 class="score__head">Gesamtbild
      <span class="score__regime">${escapeHtml(score.regime)}</span></h3>

    <div class="score__verdict">
      <p class="score__big num rating--${ratingTone(score.rating)}">
        ${score.rating}<span class="score__big-of">/100</span></p>
      <p class="score__verdict-text">
        <b>${escapeHtml(score.band)}</b>, Richtung ${escapeHtml(score.direction)}.
        ${
          weakest
            ? `Am schwächsten: <b>${escapeHtml(weakest.label)}</b>.`
            : ""
        }
        <span class="score__caveat">Bewertet, wie eindeutig das Bild ist &mdash;
          nicht, wie wahrscheinlich ein Gewinn. Keine Wahrscheinlichkeit.</span>
      </p>
      <ul class="score__parts">${parts}</ul>
    </div>

    <p class="score__headline">${escapeHtml(score.headline)}</p>

    <p class="score__sides">
      <span class="up">${Math.round(upShare)} % sprechen für <b>aufwärts</b></span>
      <span class="down"><b>abwärts</b>: ${Math.round(100 - upShare)} %</span>
    </p>
    <div class="score__split" role="img"
         aria-label="Belege dafür ${score.bullish}, dagegen ${score.bearish}">
      <span class="score__side score__side--up" style="width:${upShare.toFixed(1)}%"></span>
      <span class="score__side score__side--down" style="width:${(100 - upShare).toFixed(1)}%"></span>
    </div>

    <p class="score__meta">${score.breadth} Familien mit Meinung &middot;
      ${score.readings} Messwerte &middot;
      Widerspruch ${(score.conflict * 100).toFixed(0)} %
      <span class="score__raw" title="Rohe Gewichtssummen, ohne Einheit">
        (${score.bullish.toFixed(2)} / ${score.bearish.toFixed(2)})</span></p>

    <ul class="score__families">${families}</ul>

    ${
      score.context.length
        ? `<p class="score__context">Ohne Richtung: ${score.context
            .map(escapeHtml)
            .join(" &middot; ")}</p>`
        : ""
    }
    ${
      // Which families had nothing to say at all, said out loud. Without it
      // "5 Familien" reads as "everything was weighed", and half the families
      // this build knows about do not feed the score yet.
      score.missing.length
        ? `<p class="score__missing">Noch nicht im Gesamtbild:
             ${score.missing.map(escapeHtml).join(", ")}
             &mdash; diese Familien liefern noch keine Befunde.</p>`
        : ""
    }
  </section>`;
}

function gatePanel(gate) {
  if (!gate) return "";
  const rows = (gate.checks ?? [])
    .map(
      (c) => `<li class="gate__check${c.passed ? "" : " gate__check--no"}${
        c.blocking ? " gate__check--stop" : ""
      }">
        <span class="gate__mark" aria-hidden="true"></span>
        <span class="gate__label">${escapeHtml(c.label)}</span>
        <span class="gate__detail">${escapeHtml(c.detail)}</span>
      </li>`
    )
    .join("");

  return `
  <section class="gate${gate.would_ask ? " gate--on" : ""}" aria-live="polite">
    <p class="gate__headline">${escapeHtml(gate.headline)}</p>
    <ul class="gate__checks">${rows}</ul>
  </section>`;
}

/**
 * What each timeframe says, side by side.
 *
 * The single most useful thing on this screen, and the reason a chart alone is
 * not enough: a setup that reads well on the hour while the week is in a
 * downtrend is a different proposition, and a row of regimes shows that in one
 * glance where four charts would take four readings.
 */
/* Engine vocabulary onto reading vocabulary.
 *
 * A lookup rather than a translation of the enum values themselves: the enum is
 * what the backtest reports, the log records and the tests assert on, and
 * renaming it to suit a screen would make every stored result unreadable. A
 * missing entry falls through to the raw value, which is visible and fixable. */
const WORDS = {
  trend_up: "Aufwärtstrend",
  trend_down: "Abwärtstrend",
  range: "Seitwärts",
  manipulation: "Manipulation",
  unknown: "unklar",
  bullish: "bullisch",
  bearish: "bärisch",
  neutral: "neutral",
  low: "tief",
  normal: "normal",
  high: "hoch",
  extreme: "extrem",
  new_longs: "neue Longs",
  new_shorts: "neue Shorts",
  greed: "Gier",
  fear: "Angst",
  extreme_greed: "extreme Gier",
  extreme_fear: "extreme Angst",
};

function word(value) {
  return WORDS[value] ?? String(value ?? "").replace(/_/g, " ");
}

function frameTable(view) {
  if (!view.frames?.length) return "";
  const marks = (f) =>
    [
      f.bos ? "BOS" : "",
      f.choch ? "CHoCH" : "",
      f.sweep_up ? "Hoch geholt" : "",
      f.sweep_down ? "Tief geholt" : "",
    ]
      .filter(Boolean)
      .join(" · ");

  return `
  <table class="frames">
    <thead>
      <tr><th>Ebene</th><th>Regime</th><th>Trend</th><th>Vola</th><th>Swings</th><th>Ereignisse</th></tr>
    </thead>
    <tbody>
      ${view.frames
        .map(
          (f) => `<tr>
        <th scope="row">${escapeHtml(f.timeframe)}</th>
        <td class="frames__regime frames__regime--${escapeHtml(f.regime)}">${escapeHtml(
          word(f.regime)
        )}</td>
        <td class="frames__trend frames__trend--${escapeHtml(f.trend)}">${escapeHtml(
          word(f.trend)
        )}</td>
        <td>${escapeHtml(word(f.volatility))}</td>
        <td class="num frames__swings">${escapeHtml(f.sequence || "—")}</td>
        <td class="frames__events">${escapeHtml(marks(f))}</td>
      </tr>`
        )
        .join("")}
    </tbody>
  </table>
  ${marketContext(view)}`;
}

function marketContext(view) {
  const bits = [];
  if (view.session) bits.push(`Sitzung <b>${escapeHtml(view.session)}</b>`);
  if (view.positioning) bits.push(`Positionierung <b>${escapeHtml(word(view.positioning))}</b>`);
  if (view.sentiment) bits.push(`Stimmung <b>${escapeHtml(view.sentiment)}</b>`);
  for (const item of view.upcoming ?? []) bits.push(escapeHtml(item));
  return bits.length ? `<p class="market__context">${bits.join(" &middot; ")}</p>` : "";
}

async function loadMarket() {
  // The symbol list is one cheap call and the chart is a slow one. Awaiting
  // both before drawing anything meant the asset rail did not appear for the
  // twenty-odd seconds a cold analysis takes -- so the first thing anybody
  // wants to do was the last thing that became possible.
  if (!state.symbols) {
    try {
      state.symbols = await api("/api/market");
    } catch {
      state.symbols = [];
    }
    renderRail();
  }
  const symbol = state.symbol ?? state.symbols[0];
  if (!symbol) {
    state.market = "unavailable";
    return;
  }
  state.symbol = symbol;
  state.loadingSince = state.loadingSince ?? Date.now();
  renderMarket();

  const tf = state.marketTimeframe ? `?timeframe=${state.marketTimeframe}` : "";
  try {
    state.market = await api(`/api/market/${symbol}/chart${tf}`);
  } catch {
    state.market = "unavailable";
  }
  state.loadingSince = null;
}

/**
 * Fetch the score, after the chart and never in front of it.
 *
 * Only when it would say something new: a different market, or the same market
 * on a newer bar. The reading does not depend on which timeframe the chart is
 * showing -- it reads all of them -- so switching the chart's tab must not
 * throw it away and spend ten seconds rebuilding the same answer.
 *
 * A late reply for a market nobody is looking at any more is discarded rather
 * than drawn. Clicking through four assets while the first is still computing
 * would otherwise paint the first one's score under the fourth one's chart.
 */
async function loadScore() {
  const view = state.market;
  if (!view || view === "unavailable") return;
  const wanted = view.symbol;
  if (state.scoreFor === wanted && state.score && state.score !== "unavailable") {
    if (state.score.as_of_ts === view.as_of_ts) return;
  }
  if (state.scoreFor !== wanted) {
    state.score = null;
    state.scoreFor = wanted;
  }
  let answer;
  try {
    answer = await api(`/api/market/${wanted}/score`);
  } catch {
    answer = "unavailable";
  }
  if (state.symbol !== wanted) return;
  state.score = answer;
}

function paintMarket() {
  const canvas = document.querySelector('[data-canvas="market"]');
  const view = state.market;
  if (!canvas || !view || view === "unavailable") return;
  drawChart(canvas, view, state.hover?.id === "market" ? state.hover : null);
}

/* ----------------------------------------------------- the factor table -- */

/**
 * The arithmetic behind the confidence number, laid out so it can be checked.
 *
 * The number on its own invites either blind trust or blind dismissal. Showing
 * the model's read on each factor, how sure it was of that read, the weight the
 * configuration gives it, and the points that produced — and having the points
 * sum to the number above — turns a claim into something a person can disagree
 * with specifically.
 *
 * Contributions are drawn as bars from a centre line rather than printed alone,
 * because the thing worth seeing is which factor actually moved the answer.
 * Usually one did and the rest are noise, and that is invisible in a column of
 * numbers.
 */
function factorTable(p) {
  if (!p.factors?.length) return "";
  const widest = Math.max(...p.factors.map((f) => Math.abs(f.contribution)), 1);

  const rows = p.factors
    .map((f) => {
      const share = (Math.abs(f.contribution) / widest) * 50;
      const positive = f.contribution >= 0;
      return `
      <tr>
        <th scope="row">${escapeHtml(f.factor)}</th>
        <td class="factor-bar">
          <span class="factor-bar__track">
            <span class="factor-bar__fill factor-bar__fill--${positive ? "for" : "against"}"
                  style="width:${share.toFixed(1)}%; ${positive ? "left:50%" : `right:50%`}"></span>
          </span>
        </td>
        <td class="num factor-points">${f.contribution >= 0 ? "+" : ""}${f.contribution.toFixed(1)}</td>
        <td class="factor-weight num">${(f.weight * 100).toFixed(0)}%</td>
        <td class="factor-why">${escapeHtml(f.reasoning || "")}</td>
      </tr>`;
    })
    .join("");

  const total = p.factors.reduce((sum, f) => sum + f.contribution, 0);
  const raw = p.confidence_raw || p.confidence;
  /* The sum has to reconcile with the number shown above it, or the reader
   * assumes they misread rather than that something intervened. When a cap
   * changed the answer, the cap is part of the arithmetic and is stated. */
  const capped = p.confidence_cap_reason && Math.abs(raw - p.confidence) > 0.05;
  const sum = `50 baseline ${total >= 0 ? "+" : "−"} ${Math.abs(total).toFixed(
    1
  )} from the factors = <b class="num">${raw.toFixed(1)}</b>`;
  return `
  <table class="factors">
    <caption>
      ${sum}
      ${
        capped
          ? `<span class="factors__cap">held down to
             <b class="num">${p.confidence.toFixed(0)}</b> &mdash;
             ${escapeHtml(p.confidence_cap_reason)}</span>`
          : ""
      }
    </caption>
    <thead class="sr-only">
      <tr><th>Factor</th><th>Direction</th><th>Points</th><th>Weight</th><th>Reason</th></tr>
    </thead>
    <tbody>${rows}</tbody>
  </table>`;
}

/* ------------------------------------------------------------- the chart -- */

function chartKey(id) {
  return `${id}@${state.timeframe.get(id) ?? ""}`;
}

function timeframeTabs(p, view) {
  const current = view.timeframe;
  if (!view.available_timeframes?.length) return "";
  return `<span class="chart__tabs" role="tablist" aria-label="Timeframe">
    ${view.available_timeframes
      .map(
        (tf) => `<button type="button" role="tab" data-act="tf" data-tf="${tf}"
                   aria-selected="${tf === current}"
                   class="chart__tab${tf === current ? " chart__tab--on" : ""}">${tf}</button>`
      )
      .join("")}
  </span>`;
}

function chartPanel(p) {
  const view = state.charts.get(chartKey(p.id));
  if (view === "unavailable") return "";
  if (!view) {
    return `<div class="chart chart--loading" data-chart="${p.id}">
      <span class="pulse"></span><p>Lade die Kerzen, auf denen das entschieden wurde&hellip;</p>
    </div>`;
  }
  const hidden = view.levels_hidden
    ? `<span class="chart__hidden">${view.levels_hidden} more level${
        view.levels_hidden === 1 ? "" : "s"
      } not drawn</span>`
    : "";
  return `
  <figure class="chart" data-chart="${p.id}">
    <figcaption class="chart__head">
      <span class="chart__tf">${escapeHtml(view.symbol)}</span>
      ${timeframeTabs(p, view)}
      <span class="chart__readout" data-readout="${p.id}">${escapeHtml(
        candleReadout(view, view.candles.length - 1)
      )}</span>
      ${hidden}
    </figcaption>
    <canvas class="chart__canvas" data-canvas="${p.id}"
            role="img"
            aria-label="Candlestick chart of ${escapeHtml(view.symbol)} ending at the bar this
                        trade was decided on, with the entry, stop, target and the named levels
                        the analysis used drawn on it."></canvas>
    <figcaption class="chart__note">${escapeHtml(view.note)}</figcaption>
  </figure>`;
}

/**
 * Fetch each visible proposal's chart once, then redraw.
 *
 * Failures are recorded as "unavailable" rather than retried. A proposal built
 * before charts existed, or a symbol with nothing backfilled, will not start
 * working on the next poll, and retrying every four seconds would turn one
 * missing file into a steady stream of requests.
 */
async function loadCharts() {
  const missing = state.proposals.filter((p) => !state.charts.has(chartKey(p.id)));
  if (!missing.length) return;
  await Promise.all(
    missing.map(async (p) => {
      const tf = state.timeframe.get(p.id);
      const key = chartKey(p.id);
      try {
        state.charts.set(
          key,
          await api(`/api/proposals/${p.id}/chart${tf ? `?timeframe=${tf}` : ""}`)
        );
      } catch {
        state.charts.set(key, "unavailable");
      }
    })
  );
  render();
  paintCharts();
  document.querySelectorAll("[data-canvas]").forEach(wireChartHover);
}

/* A canvas has no intrinsic size: it learns one from CSS and has to be told to
 * redraw when that changes, or it is drawn once at whatever width the window
 * happened to be and stretched from then on. Re-observing an element already
 * being watched is a no-op, so this is safe to call after every render. */
/* The market canvas is painted from its own state, so a resize has to call
 * both — `paintCharts` looks proposals up by id and finds nothing for it, which
 * left the market chart drawn at whatever width the window opened at and
 * stretched from then on. */
const sizeWatcher = new ResizeObserver(() => {
  paintCharts();
  paintMarket();
});

/* Re-point the watcher at the canvases that exist now.
 *
 * Both renders replace their markup wholesale, so every four seconds the old
 * canvas elements are discarded and new ones take their place. A ResizeObserver
 * keeps a strong reference to what it observes, so observing the new ones
 * without dropping the old leaves the detached nodes alive — a few thousand of
 * them over a day at the desk, each one firing a repaint as it is removed. */
function watchCanvases() {
  sizeWatcher.disconnect();
  document.querySelectorAll("[data-canvas]").forEach((canvas) => sizeWatcher.observe(canvas));
}

/**
 * Show this proposal on a different timeframe.
 *
 * The chart is redrawn from a cached payload when there is one, so flipping back
 * and forth between the hour and the week is instant. That matters more than it
 * sounds: comparing two timeframes means looking at one, then the other, then
 * the first again, and a spinner on every switch turns a comparison into three
 * separate readings.
 */
async function switchTimeframe(id, timeframe) {
  if (state.timeframe.get(id) === timeframe) return;
  state.timeframe.set(id, timeframe);
  state.hover = null;
  render();
  paintCharts();
  await loadCharts();
}

function paintCharts() {
  document.querySelectorAll("[data-canvas]").forEach((canvas) => {
    const id = canvas.dataset.canvas;
    const view = state.charts.get(chartKey(id));
    if (!view || view === "unavailable") return;
    const hover = state.hover?.id === id ? state.hover : null;
    drawChart(canvas, view, hover);
  });
}

function wireChartHover(canvas) {
  const id = canvas.dataset.canvas;
  const view = state.charts.get(chartKey(id));
  if (!view || view === "unavailable") return;

  const readout = document.querySelector(`[data-readout="${id}"]`);
  const move = (event) => {
    const box = canvas.getBoundingClientRect();
    state.hover = { id, x: event.clientX - box.left, y: event.clientY - box.top };
    const geometry = drawChart(canvas, view, state.hover);
    if (geometry && readout) {
      const index = Math.max(
        0,
        Math.min(view.candles.length - 1, Math.floor((state.hover.x - geometry.plotLeft) / geometry.slot))
      );
      readout.textContent = candleReadout(view, index);
    }
  };

  canvas.addEventListener("pointermove", move);
  canvas.addEventListener("pointerleave", () => {
    state.hover = null;
    drawChart(canvas, view, null);
    if (readout) readout.textContent = candleReadout(view, view.candles.length - 1);
  });
}

function ticket(p) {
  const changed = state.changed.get(p.id) ?? new Set();
  const notice = state.notices.get(p.id);
  const halted = state.system?.kill_switch_engaged;
  const side = p.side === "long" ? "long" : "short";
  const secondsLeft = Math.max(0, Math.round((p.expires_ts - Date.now()) / 1000));

  return `
  <article class="ticket" data-id="${p.id}">
    <header class="ticket__head">
      <span class="side side--${side}">${p.side.toUpperCase()}</span>
      <span class="symbol">${p.symbol}</span>
      <span class="head-spacer"></span>
      <span class="confidence">confidence <b class="num">${p.confidence.toFixed(0)}</b></span>
      <span class="countdown num" data-urgent="${secondsLeft < 120}"
            data-expires="${p.expires_ts}">${secondsLeft}s übrig</span>
    </header>

    <div class="ticket__body">
      ${ladder(p)}

      <dl class="figures">
        ${figure("Entry", fmt.price(p.entry), null, null, changed.has("entry"))}
        ${figure(
          "Stop",
          fmt.price(p.stop),
          `${fmt.pct(p.stop_distance_pct)} entfernt`,
          "short",
          changed.has("stop")
        )}
        ${figure("Ziel", fmt.price(p.target), `CRV ${p.reward_risk.toFixed(2)}`, "long", changed.has("target"))}
        ${figure(
          "Liquidation",
          fmt.price(p.liquidation_price),
          `${p.liquidation_buffer_r.toFixed(1)}× Stop-Abstand dahinter`,
          "liq",
          changed.has("liquidation_price")
        )}
        ${figure("Grösse", fmt.qty(p.qty), `${fmt.money(p.notional)} Volumen`, null, changed.has("qty"))}
        ${figure("Hebel", `${p.leverage}×`, `${fmt.money(p.margin)} Margin`, null, changed.has("leverage"))}
        ${figure(
          "Im Risiko",
          fmt.money(p.risk_amount),
          `${fmt.pct(p.risk_pct)} von ${fmt.money(p.equity)}`,
          null,
          changed.has("risk_amount")
        )}
        ${figure("Eingeschätztes Risiko", p.risk_level, p.bias, null, false)}

        <div class="reasoning">
          <h3>Warum</h3>
          ${factorTable(p)}
          <ul>${p.reasoning.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>
          ${
            p.invalidation_note
              ? `<p class="invalidation"><b>Falsch, wenn</b> ${escapeHtml(p.invalidation_note)}</p>`
              : ""
          }
        </div>
      </dl>
    </div>

    ${chartPanel(p)}

    <footer class="ticket__foot">
      <div class="dial">
        <label for="lev-${p.id}">Hebel</label>
        <span class="stepper">
          <button type="button" data-act="lev-down" aria-label="Hebel senken"
                  ${p.leverage <= 1 ? "disabled" : ""}>&minus;</button>
          <output id="lev-${p.id}">${p.leverage}×</output>
          <button type="button" data-act="lev-up" disabled
                  title="Hebel erhöhen rückt die Liquidation näher an den Stop — das ist ein anderer Trade"
                  aria-label="Hebel erhöhen ist nicht erlaubt">+</button>
        </span>
      </div>

      <div class="dial">
        <label>Risiko</label>
        <span class="stepper">
          <button type="button" data-act="risk-down" aria-label="Risiko halbieren">&frac12;</button>
          <output>${fmt.pct(p.risk_pct)}</output>
        </span>
      </div>

      <span class="foot-spacer"></span>

      <button class="btn" type="button" data-act="decline">Ablehnen</button>
      <button class="btn commit" type="button" data-act="commit"
              ${halted ? "disabled" : ""}
              aria-describedby="commit-help-${p.id}">
        <span class="commit__fill"></span>
        <span class="commit__label">${halted ? "Angehalten" : "Zum Senden halten"}</span>
      </button>
      <span id="commit-help-${p.id}" hidden>Etwas über eine Sekunde gedrückt halten, um diese Order zu senden.</span>

      ${notice ? `<div class="notice notice--${notice.kind}">${escapeHtml(notice.text)}</div>` : ""}
    </footer>
  </article>`;
}

function escapeHtml(text) {
  const node = document.createElement("span");
  node.textContent = String(text);
  return node.innerHTML;
}

/* --------------------------------------------------------------- render -- */

function render() {
  const sys = state.system;
  document.getElementById("strip").innerHTML = sys
    ? `
      <span>Kapital <b class="num">${fmt.money(sys.equity)}</b></span>
      <span>offen <b class="num">${sys.open_positions}</b></span>
      <span class="flag ${sys.testnet ? "flag--testnet" : "flag--armed"}">
        ${sys.testnet ? "Testnetz" : "echtes Geld"}
      </span>
      ${sys.execution_connected ? "" : '<span class="flag">keine Börse verbunden</span>'}
      ${sys.kill_switch_engaged ? '<span class="flag flag--halted">angehalten</span>' : ""}`
    : '<span class="pulse"></span>';

  const banners = document.getElementById("banners");
  let html = "";
  if (state.outcome) {
    html += `<div class="banner banner--${state.outcome.kind === "ok" ? "sent" : "blocked"}"
                  role="status">
      <h2>${state.outcome.kind === "ok" ? "Gesendet" : "Nicht gesendet"}</h2>
      <p>${escapeHtml(state.outcome.text)}</p>
    </div>`;
  }
  if (sys?.kill_switch_engaged) {
    html += `<div class="banner banner--halt">
      <h2>Handel ist angehalten</h2>
      <p>${escapeHtml(sys.kill_switch_reason)} &mdash; es wird nichts gesendet, bis das von Hand aufgehoben wird.</p>
    </div>`;
  } else if (sys && !sys.limits_allow_trading && sys.limit_blockers.length) {
    html += `<div class="banner banner--blocked">
      <h2>A risk limit is blocking new trades</h2>
      <p>${sys.limit_blockers.map(escapeHtml).join("; ")}</p>
    </div>`;
  }
  banners.innerHTML = html;

  const list = document.getElementById("list");
  if (state.proposals === null) {
    list.innerHTML = `<div class="placeholder"><span class="pulse"></span><p>Lade&hellip;</p></div>`;
    return;
  }
  if (!state.proposals.length) {
    list.innerHTML = `<div class="placeholder">
      <h2>Nichts zu entscheiden</h2>
      <p>Die meisten Kerzen sind kein Setup. Dieser Bereich bleibt leer, bis die
         Analyse etwas findet, das Geld wert ist &mdash; und das ist der Normalzustand.</p>
    </div>`;
    return;
  }
  list.innerHTML = state.proposals.map(ticket).join("");
}

function tickCountdowns() {
  document.querySelectorAll(".countdown").forEach((node) => {
    const left = Math.max(0, Math.round((Number(node.dataset.expires) - Date.now()) / 1000));
    node.textContent = `${left}s left`;
    node.dataset.urgent = String(left < 120);
  });
}

/* ------------------------------------------------------------ behaviour -- */

function markChanged(before, after) {
  const fields = new Set();
  for (const key of ["entry", "stop", "target", "qty", "leverage", "risk_amount", "liquidation_price"]) {
    if (before[key] !== after[key]) fields.add(key);
  }
  state.changed.set(after.id, fields);
}

async function adjust(id, body) {
  const before = state.proposals.find((p) => p.id === id);
  try {
    const after = await api(`/api/proposals/${id}/adjust`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    markChanged(before, after);
    state.proposals = state.proposals.map((p) => (p.id === id ? after : p));
    state.notices.delete(id);
  } catch (error) {
    state.notices.set(id, { kind: "error", text: error.message });
  }
  render();
}

async function send(id) {
  try {
    const { token } = await api(`/api/proposals/${id}/token`, { method: "POST" });
    const result = await api(`/api/proposals/${id}/confirm`, {
      method: "POST",
      body: JSON.stringify({ token }),
    });
    state.outcome = {
      kind: result.sent ? "ok" : "error",
      text: result.sent
        ? `Order sent as ${result.reference}.`
        : `Nothing was sent — ${result.reason}. The proposal is closed.`,
      at: Date.now(),
    };
  } catch (error) {
    state.outcome = { kind: "error", text: error.message, at: Date.now() };
    state.notices.set(id, { kind: "error", text: error.message });
  }
  await refresh();
}

/* The hold gesture.
 *
 * Pointer capture so the hold survives the finger sliding off the button, and a
 * cancel on leave so sliding away *deliberately* aborts it. Both matter: the
 * first prevents accidental cancellation, the second preserves the escape hatch. */
function wireHold(button, onComplete) {
  let timer = null;

  const start = (event) => {
    if (button.disabled) return;
    event.preventDefault();
    button.setPointerCapture?.(event.pointerId);
    button.dataset.holding = "true";
    state.holding = true;
    timer = setTimeout(() => {
      button.dataset.holding = "false";
      button.disabled = true;
      button.querySelector(".commit__label").textContent = "Sending…";
      state.holding = false;
      onComplete();
    }, HOLD_MS);
  };

  const abort = () => {
    clearTimeout(timer);
    timer = null;
    state.holding = false;
    button.dataset.holding = "false";
  };

  button.addEventListener("pointerdown", start);
  button.addEventListener("pointerup", abort);
  button.addEventListener("pointercancel", abort);
  button.addEventListener("lostpointercapture", abort);

  // Keyboard users hold the key instead. Without this the safety gesture would
  // simply be unavailable to them, which is not an acceptable trade.
  button.addEventListener("keydown", (event) => {
    if ((event.key === " " || event.key === "Enter") && !event.repeat) {
      start(event);
    }
  });
  button.addEventListener("keyup", abort);
  button.addEventListener("blur", abort);
}

document.addEventListener("click", (event) => {
  const action = event.target.closest("[data-act]");
  if (!action) return;
  const id = action.closest(".ticket")?.dataset.id;
  if (!id) return;
  const proposal = state.proposals.find((p) => p.id === id);

  switch (action.dataset.act) {
    case "lev-down":
      adjust(id, { leverage: Math.max(1, proposal.leverage - 1) });
      break;
    case "risk-down":
      adjust(id, { risk_pct: proposal.risk_pct / 2 });
      break;
    case "decline":
      api(`/api/proposals/${id}/reject`, { method: "POST" }).then(refresh);
      break;
    case "tf":
      switchTimeframe(id, action.dataset.tf);
      break;
    default:
      break;
  }
});

document.addEventListener("click", (event) => {
  const action = event.target.closest('[data-act="sym"], [data-act="mtf"]');
  if (!action) return;
  if (action.dataset.act === "sym") {
    if (state.symbol === action.dataset.sym) return;
    state.symbol = action.dataset.sym;
  } else {
    if (state.marketTimeframe === action.dataset.tf) return;
    state.marketTimeframe = action.dataset.tf;
  }
  state.market = null;
  state.score = null;
  state.hover = null;
  renderMarket();
  loadMarket()
    .then(renderMarket)
    .then(loadScore)
    .then(renderMarket);
});

/**
 * The asset rail in the masthead.
 *
 * Rendered separately from the market panel and on its own schedule, because it
 * must stay clickable while the panel behind it is rebuilding. A rail that
 * disappears for twenty seconds during a cold analysis is a rail you cannot use
 * to escape a slow asset.
 */
function renderRail() {
  const rail = document.getElementById("rail");
  if (!rail) return;
  // Not loaded yet and loaded-and-empty are different answers. Saying "no
  // markets configured" during the first second of a cold start is a lie that
  // sends somebody to edit a config file that is fine.
  if (state.symbols === null || state.symbols === undefined) {
    rail.innerHTML = `<span class="rail__loading">Märkte&hellip;</span>`;
    return;
  }
  const symbols = state.symbols;
  if (!symbols.length) {
    rail.innerHTML = `<span class="rail__loading">keine Märkte konfiguriert</span>`;
    return;
  }
  const current = state.symbol ?? symbols[0];
  rail.innerHTML = symbols
    .map(
      (s) => `<button type="button" data-act="sym" data-sym="${s}"
                aria-current="${s === current ? "true" : "false"}"
                class="rail__tab${s === current ? " rail__tab--on" : ""}">${short(s)}</button>`
    )
    .join("");
}

/** BTCUSDT reads as BTC on a tab. The pair is in the chart header anyway. */
function short(symbol) {
  return symbol.replace(/USDT$|USD$/, "");
}

function renderMarket() {
  const host = document.getElementById("market");
  if (!host) return;
  renderRail();
  host.innerHTML = marketPanel();
  paintMarket();
  const canvas = host.querySelector("[data-canvas]");
  if (canvas) wireMarketHover(canvas);
  watchCanvases();
}

/* The market canvas keeps its own hover wiring: it is redrawn on its own
 * schedule, and reusing the ticket path would look up a proposal id that does
 * not exist. */
function wireMarketHover(canvas) {
  const readout = document.querySelector('[data-readout="market"]');
  const move = (event) => {
    const view = state.market;
    if (!view || view === "unavailable") return;
    const box = canvas.getBoundingClientRect();
    state.hover = { id: "market", x: event.clientX - box.left, y: event.clientY - box.top };
    const geometry = drawChart(canvas, view, state.hover);
    if (geometry && readout) {
      const index = Math.max(
        0,
        Math.min(
          view.candles.length - 1,
          Math.floor((state.hover.x - geometry.plotLeft) / geometry.slot)
        )
      );
      readout.textContent = candleReadout(view, index);
    }
  };
  canvas.addEventListener("pointermove", move);
  canvas.addEventListener("pointerleave", () => {
    const view = state.market;
    state.hover = null;
    if (view && view !== "unavailable") {
      drawChart(canvas, view, null);
      if (readout) readout.textContent = candleReadout(view, view.candles.length - 1);
    }
  });
}

async function refresh() {
  // Never re-render underneath a hold in progress.
  if (state.holding) return;
  try {
    const [system, proposals] = await Promise.all([
      api("/api/state"),
      api("/api/proposals"),
    ]);
    state.system = system;
    state.proposals = proposals;
  } catch (error) {
    state.system = null;
    document.getElementById("banners").innerHTML = `<div class="banner banner--halt">
      <h2>Cannot reach the engine</h2><p>${escapeHtml(error.message)}</p></div>`;
  }
  render();
  document.querySelectorAll(".commit").forEach((button) => {
    const id = button.closest(".ticket").dataset.id;
    wireHold(button, () => send(id));
  });
  paintCharts();
  document
    .querySelectorAll("[data-canvas]:not([data-canvas='market'])")
    .forEach(wireChartHover);
  watchCanvases();
  loadCharts();
  /* The market is refreshed on the same poll but rendered separately: it has no
   * hold gesture to interrupt, so it never has to wait for one. The score
   * follows it rather than racing it, so the chart is never held up. */
  loadMarket()
    .then(renderMarket)
    .then(loadScore)
    .then(renderMarket);
}

document.getElementById("halt").addEventListener("click", async () => {
  if (state.system?.kill_switch_engaged) {
    await api("/api/kill", { method: "DELETE" });
  } else {
    const reason = prompt("Why are you stopping? (recorded with the switch)");
    if (!reason) return;
    await api("/api/kill", { method: "POST", body: JSON.stringify({ reason }) });
  }
  refresh();
});

state.proposals = null;
render();
renderMarket();
refresh();
setInterval(refresh, POLL_MS);
setInterval(tickCountdowns, 1000);
/* The elapsed seconds in the analysis placeholder only move if something
 * redraws it. One second is the resolution it is printed at. */
setInterval(() => {
  if (state.loadingSince) renderMarket();
}, 1000);

/* ---------------------------------------------------- the paper trading log */

/* Read from the trader's own files through `/api/paper`, which means this works
 * whether or not the trader is running — and says which. An account last
 * settled six hours ago renders identically to a working one unless something
 * prints the age, and that exact mistake has already cost an hour here on the
 * score panel. So staleness gets a colour, a line of text, and a reason.
 *
 * On its own poll, slower than the ticket's. These trades last hours to days;
 * four seconds would be redrawing an unchanged table fifteen times a minute. */
const PAPER_POLL_MS = 20000;

function paperClock(ms) {
  if (!ms) return "—";
  return new Date(ms).toLocaleString("de-CH", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function paperAccount(account) {
  const position = account.position;
  const side = position ? (position.side === "long" ? "long" : "short") : null;
  const classes = ["paper__account"];
  if (side) classes.push(`paper__account--${side}`);
  if (account.stale) classes.push("paper__account--stale");

  let body;
  if (position) {
    const direction = side === "long" ? "up" : "down";
    const word = side === "long" ? "Long" : "Short";
    const label = account.setup ? `Setup ${escapeHtml(account.setup)}` : "Position";
    const frame = account.setup_timeframe ? ` auf ${escapeHtml(account.setup_timeframe)}` : "";
    body = `
      <p class="paper__state">${label}${frame} &middot; ${word} seit ${paperClock(
        position.opened_ts
      )}${position.stop_moved ? " &middot; Stop auf Einstand" : ""}</p>
      <dl class="paper__plan">
        <div><dt>Entry</dt><dd>${fmt.price(position.entry)}</dd></div>
        <div><dt>Stop</dt><dd>${fmt.price(position.stop)}</dd></div>
        <div><dt>Ziel</dt><dd>${fmt.price(position.target)}</dd></div>
      </dl>
      <p class="paper__open ${position.unrealised >= 0 ? "up" : "down"}">
        ${position.unrealised >= 0 ? "+" : ""}${fmt.money(position.unrealised)} offen
      </p>`;
  } else if (account.resting_at) {
    body = `<p class="paper__state">Order liegt bei ${fmt.price(
      account.resting_at
    )} und wartet auf den Kurs.</p>`;
  } else {
    /* "Flach" alone cannot say whether the market offered nothing or whether
     * every setup was refused, and those call for opposite responses. The
     * sentence comes from the trader's own counters. */
    body = `<p class="paper__state">Flach &mdash; ${escapeHtml(
      account.activity || "wartet auf ein Setup"
    )}</p>`;
  }

  /* Why it is stale matters more than that it is: the trader not running and
   * the exchange being unreachable call for different things. This says the
   * fact and the command; the cause is in the runner's own error list. */
  const stale = account.stale
    ? `<p class="paper__stale">Seit ${account.behind_minutes} Min. nichts verbucht &mdash;
         läuft <code>scripts/papertrade.py</code> noch?</p>`
    : "";

  return `
    <li class="${classes.join(" ")}">
      <div class="paper__sym">
        <span>${escapeHtml(account.symbol)}</span>
        <span class="paper__equity">${fmt.money(account.equity)}</span>
      </div>
      ${body}
      ${stale}
    </li>`;
}

function paperTrade(trade) {
  const won = trade.r_multiple >= 0;
  return `
    <tr>
      <td>${paperClock(trade.closed_ts)}</td>
      <td>${escapeHtml(trade.symbol.replace("USDT", ""))}</td>
      <td>${escapeHtml(trade.setup)} ${escapeHtml(trade.setup_timeframe)}</td>
      <td>${trade.side === "long" ? "Long" : "Short"}</td>
      <td class="paper__r ${won ? "up" : "down"}">${won ? "+" : ""}${trade.r_multiple.toFixed(
        2
      )} R</td>
      <td>${escapeHtml(trade.exit_reason)}</td>
      <td class="paper__verdict">${escapeHtml(trade.verdict)}</td>
    </tr>`;
}

function renderPaper(readout) {
  const host = document.getElementById("paper");
  const hint = document.getElementById("paper-hint");
  if (!host) return;

  if (readout === "unavailable") {
    host.innerHTML = `<p class="paper__state">Konten nicht lesbar.</p>`;
    return;
  }
  if (!readout.accounts.length) {
    host.innerHTML = `<p class="paper__state">
      Noch kein Konto. Starte den Papertrader:
      <code>python scripts/papertrade.py</code></p>`;
    return;
  }

  /* The headline carries the one number that decides whether any of this is
   * worth anything, and carries it with its sample size. A mean over nine
   * trades is not an edge and the screen should not let it look like one. */
  if (hint) {
    hint.innerHTML = readout.trades
      ? `${readout.trades} Trades vorwärts &middot; Mittel ${
          readout.mean_r >= 0 ? "+" : ""
        }${readout.mean_r.toFixed(3)} R${
          readout.trades < 30 ? " (noch zu wenige für eine Aussage)" : ""
        }`
      : "Noch kein abgeschlossener Trade — die ersten brauchen Stunden bis Tage";
  }

  const trades = readout.recent.length
    ? `<table class="paper__trades">
         <thead>
           <tr>
             <th>Geschlossen</th><th>Markt</th><th>Setup</th><th>Richtung</th>
             <th class="paper__r">Ergebnis</th><th>Grund</th><th>Was passiert ist</th>
           </tr>
         </thead>
         <tbody>${readout.recent.map(paperTrade).join("")}</tbody>
       </table>`
    : "";

  const totals = readout.trades
    ? `<p class="paper__totals">
         <span>Treffer <b>${Math.round((100 * readout.wins) / readout.trades)}%</b></span>
         <span>Summe <b>${fmt.money(readout.total_net)}</b></span>
         <span>Trades <b>${readout.trades}</b></span>
       </p>`
    : "";

  host.innerHTML = `
    <ul class="paper__accounts">${readout.accounts.map(paperAccount).join("")}</ul>
    ${trades}
    ${totals}`;
}

async function loadPaper() {
  try {
    renderPaper(await api("/api/paper"));
  } catch {
    renderPaper("unavailable");
  }
}

loadPaper();
setInterval(loadPaper, PAPER_POLL_MS);

/* ------------------------------------------------------- the four views -- */

/* Four places, not four tabs. Each answers a different question, and only the
 * market view is live -- the other three are records and hold still, so they
 * load when you open them rather than polling in the background. A ledger that
 * redrew itself every four seconds while you read it would be worse than one
 * that did not.
 *
 * Routing is the URL hash and nothing else. No framework, no history
 * manipulation: the address bar says which page you are on, reloading keeps
 * you there, and the back button works because it was never taken away.
 */

const VIEWS = ["markt", "konto", "trades", "verlauf"];
const DEFAULT_VIEW = "markt";

/* Which kind of trade each record page is showing. Forward and replayed are
 * never mixed and never averaged, so this is per-page state rather than a
 * global: looking at replayed trades on one page should not silently change
 * what the other one means. */
const sources = { trades: "live", verlauf: "live" };

function currentView() {
  const raw = (location.hash || "").replace(/^#\/?/, "");
  return VIEWS.includes(raw) ? raw : DEFAULT_VIEW;
}

function showView(name) {
  for (const view of VIEWS) {
    const node = document.getElementById(`view-${view}`);
    if (node) node.hidden = view !== name;
  }
  document.querySelectorAll(".views__item").forEach((item) => {
    if (item.dataset.view === name) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  /* Which view is open is written on <body> and the rest is CSS. Setting
   * `hidden` on the rail here did not survive: the market poll rebuilds that
   * element every few seconds and the attribute went with it, so the market
   * picker sat on the account page looking like a control you could use. An
   * attribute on an ancestor nothing re-renders cannot be clobbered that way. */
  document.body.dataset.view = name;

  if (name === "konto") loadKonto();
  if (name === "trades") loadLedger();
  if (name === "verlauf") loadCurve();
}

function money(value) {
  return value.toLocaleString("de-CH", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function signed(value, digits = 2) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
}

function viewClock(ms) {
  if (!ms) return "—";
  return new Date(ms).toLocaleString("de-CH", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/* ------------------------------------------------------------- Konto ----- */

function kontoCard(account) {
  const classes = ["konto__card"];
  if (account.stale) classes.push("konto__card--stale");
  else if (account.change > 0) classes.push("konto__card--up");
  else if (account.change < 0) classes.push("konto__card--down");

  const direction = account.change > 0 ? "up" : account.change < 0 ? "down" : "";
  const open = account.has_position
    ? `<p class="konto__state">Position offen &middot; ${money(
        account.open_risk
      )} CHF im Risiko &middot; ${signed(account.unrealised)} CHF unrealisiert</p>`
    : "";

  return `
    <li class="${classes.join(" ")}">
      <div class="konto__sym">
        <span>${escapeHtml(account.symbol)}</span>
        <span class="konto__value">${money(account.equity)}</span>
      </div>
      <p class="konto__delta ${direction}">
        ${signed(account.change)} CHF &middot; ${signed(account.change_pct, 2)} %
        <span style="color: var(--dimmer)">von ${money(account.start_equity)}</span>
      </p>
      ${open}
      <p class="konto__state">${escapeHtml(account.activity)}</p>
      <div class="konto__actions">
        <input class="konto__amount" type="number" min="1" step="50" value="500"
               aria-label="Betrag in Franken" data-amount="${escapeHtml(account.symbol)}" />
        <button class="btn" type="button" data-topup="${escapeHtml(account.symbol)}">
          Einzahlen
        </button>
        <button class="btn" type="button" data-reset="${escapeHtml(account.symbol)}">
          Zurücksetzen
        </button>
      </div>
    </li>`;
}

function renderKonto(portfolio) {
  const host = document.getElementById("konto");
  if (!host) return;
  if (portfolio === "unavailable") {
    host.innerHTML = `<p class="konto__state">Konten nicht lesbar.</p>`;
    return;
  }

  const direction =
    portfolio.total_change > 0 ? "up" : portfolio.total_change < 0 ? "down" : "";
  const hit = portfolio.trades
    ? `${Math.round((100 * portfolio.wins) / portfolio.trades)} % Treffer`
    : "noch kein abgeschlossener Trade";

  host.innerHTML = `
    <div class="total">
      <span class="total__value">${money(portfolio.total_equity)}</span>
      <span class="total__change ${direction}">
        ${signed(portfolio.total_change)} CHF &middot; ${signed(portfolio.total_change_pct, 2)} %
      </span>
      <span class="total__meta">
        ${portfolio.trades} Trades vorwärts &middot; ${hit}<br />
        ${money(portfolio.open_risk)} CHF gerade im Risiko
      </span>
    </div>
    <ul class="konto__grid">${portfolio.accounts.map(kontoCard).join("")}</ul>`;

  host.querySelectorAll("[data-topup]").forEach((button) => {
    button.addEventListener("click", async () => {
      const symbol = button.dataset.topup;
      const field = host.querySelector(`[data-amount="${symbol}"]`);
      const amount = Number(field?.value ?? 0);
      if (!(amount > 0)) return;
      await api(`/api/portfolio/${symbol}/topup`, {
        method: "POST",
        body: JSON.stringify({ amount }),
      });
      loadKonto();
    });
  });

  host.querySelectorAll("[data-reset]").forEach((button) => {
    button.addEventListener("click", async () => {
      const symbol = button.dataset.reset;
      /* A reset throws away a balance that took trades to produce, so it asks.
       * The journal is untouched either way -- what happened happened. */
      if (!confirm(`${symbol} auf den Startbetrag zurücksetzen?\n\nDie Trades im Journal bleiben.`))
        return;
      await api(`/api/portfolio/${symbol}/reset`, { method: "POST" });
      loadKonto();
    });
  });
}

function renderSettings(settings) {
  const host = document.getElementById("einstellungen");
  if (!host) return;
  if (settings === "unavailable") {
    host.innerHTML = `<p class="konto__state">Einstellungen nicht lesbar.</p>`;
    return;
  }

  const rows = [
    ["Startkapital je Markt", `${money(settings.initial_equity)} CHF`, "bei Zurücksetzen"],
    [
      "Risiko je Trade",
      `${(settings.risk_pct_floor * 100).toFixed(2)} %`,
      `das sind ${money(settings.initial_equity * settings.risk_pct_floor)} CHF`,
    ],
    ["Hebel höchstens", `${settings.max_leverage}×`, "so gewählt, dass die Liquidation hinter dem Stop liegt"],
    ["Mindest-CRV", `${settings.min_reward_risk}`, "Gewinn muss mindestens so viel wie das Risiko sein"],
    [
      "Gebührendecke",
      `${(settings.max_cost_fraction_of_risk * 100).toFixed(0)} %`,
      "Gebühren dürfen höchstens so viel vom Risiko fressen",
    ],
    ["Slippage", `${settings.slippage_bps} bp`, "wird immer gegen uns gerechnet"],
    ["Setups aktiv", settings.setups_on.join(" · "), "D und E fehlen deine Regeln"],
    [
      "Zeitebenen",
      settings.searched_timeframes.join(" · "),
      `Entscheidung auf ${settings.signal_timeframe}-Schluss`,
    ],
  ];

  host.innerHTML = `
    <div class="settings__grid">
      ${rows
        .map(
          ([label, value, note]) => `
        <dl class="settings__row">
          <dt>${escapeHtml(label)}</dt>
          <dd>${escapeHtml(String(value))}<small>${escapeHtml(note)}</small></dd>
        </dl>`
        )
        .join("")}
    </div>
    <p class="settings__note">${escapeHtml(settings.note)}</p>`;
}

async function loadKonto() {
  try {
    const [portfolio, settings] = await Promise.all([
      api("/api/portfolio"),
      api("/api/portfolio/settings"),
    ]);
    renderKonto(portfolio);
    renderSettings(settings);
  } catch {
    renderKonto("unavailable");
    renderSettings("unavailable");
  }
}

/* ------------------------------------------------------------ Trades ----- */

function ledgerRow(row) {
  const won = row.r_multiple >= 0;
  const flag = row.agreed_with_score
    ? ""
    : `<span class="ledger__flag" title="Das Gesamtbild zeigte in die andere Richtung">Bild dagegen</span>`;
  return `
    <tr>
      <td>${viewClock(row.closed_ts)}</td>
      <td>${escapeHtml(row.symbol.replace("USDT", ""))}</td>
      <td>${escapeHtml(row.setup)} ${escapeHtml(row.setup_timeframe)}</td>
      <td>${row.side === "long" ? "Long" : "Short"}</td>
      <td class="ledger__num ${won ? "up" : "down"}">${signed(row.r_multiple)} R</td>
      <td class="ledger__num optional ${won ? "up" : "down"}">${signed(row.net_pnl)}</td>
      <td class="optional">${escapeHtml(row.exit_reason)}</td>
      <td class="ledger__num optional">${row.rating}${flag}</td>
      <td class="ledger__why">${escapeHtml(row.verdict)}</td>
    </tr>`;
}

function renderLedger(ledger, source) {
  const host = document.getElementById("trades");
  const hint = document.getElementById("trades-hint");
  if (!host) return;

  document.querySelectorAll("#trades-source .segmented__item").forEach((item) => {
    item.setAttribute("aria-pressed", String(item.dataset.source === source));
  });

  if (ledger === "unavailable") {
    host.innerHTML = `<p class="konto__state">Journal nicht lesbar.</p>`;
    return;
  }
  if (!ledger.rows.length) {
    host.innerHTML = `<p class="konto__state">
      ${
        source === "live"
          ? "Noch kein Trade vorwärts abgeschlossen. Die ersten brauchen Stunden bis Tage."
          : "Keine nachgespielten Trades im Journal."
      }</p>`;
    if (hint) hint.textContent = "";
    return;
  }

  const sum = ledger.rows.reduce((total, row) => total + row.r_multiple, 0);
  const wins = ledger.rows.filter((row) => row.r_multiple > 0).length;
  if (hint) {
    hint.textContent =
      `${ledger.total} Trades${ledger.truncated ? ` (die neuesten ${ledger.rows.length} gezeigt)` : ""}` +
      ` · ${Math.round((100 * wins) / ledger.rows.length)} % Treffer · ${signed(sum, 1)} R`;
  }

  host.innerHTML = `
    <div class="scroller">
      <table class="ledger">
        <thead>
          <tr>
            <th>Geschlossen</th><th>Markt</th><th>Setup</th><th>Richtung</th>
            <th class="ledger__num">Ergebnis</th>
            <th class="ledger__num optional">CHF</th>
            <th class="optional">Grund</th>
            <th class="ledger__num optional">Bewertung</th>
            <th>Was passiert ist</th>
          </tr>
        </thead>
        <tbody>${ledger.rows.map(ledgerRow).join("")}</tbody>
      </table>
    </div>`;
}

async function loadLedger() {
  const source = sources.trades;
  try {
    renderLedger(await api(`/api/portfolio/ledger?source=${source}`), source);
  } catch {
    renderLedger("unavailable", source);
  }
}

/* ----------------------------------------------------------- Verlauf ----- */

/* An SVG line, drawn from the points rather than by a chart library. The shape
 * is one path and two labels; a dependency for that would be more code than
 * the code.
 *
 * In R, not francs. A trade's result in money depends on the size of the
 * account it was taken on, and that account has changed size -- a franc curve
 * across the boundary shows a cliff that no trade caused. */
function curveSvg(points) {
  if (points.length < 2) return "";
  const width = 1000;
  const height = 260;
  const pad = { top: 16, right: 48, bottom: 20, left: 8 };

  const values = points.map((p) => p.cumulative_r);
  let low = Math.min(0, ...values);
  let high = Math.max(0, ...values);
  if (high === low) high = low + 1;
  const span = high - low;

  const x = (i) =>
    pad.left + (i / (points.length - 1)) * (width - pad.left - pad.right);
  const y = (v) =>
    pad.top + ((high - v) / span) * (height - pad.top - pad.bottom);

  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.cumulative_r).toFixed(1)}`).join("");
  const final = values[values.length - 1];
  const zeroY = y(0).toFixed(1);

  return `
    <svg class="curve" viewBox="0 0 ${width} ${height}" role="img"
         aria-label="Summenkurve in R über ${points.length} Trades, am Ende ${signed(final, 2)} R">
      <line class="curve__zero" x1="${pad.left}" y1="${zeroY}" x2="${width - pad.right}" y2="${zeroY}" />
      <text class="curve__label" x="${width - pad.right + 6}" y="${zeroY + 3}">0</text>
      <path class="curve__line curve__line--${final >= 0 ? "up" : "down"}" d="${path}" />
      <text class="curve__label" x="${width - pad.right + 6}" y="${(y(final) + 3).toFixed(1)}">
        ${signed(final, 1)}
      </text>
    </svg>`;
}

function breakdown(title, table) {
  const entries = Object.entries(table).sort((a, b) => b[1] - a[1]);
  if (!entries.length) return "";
  const widest = Math.max(...entries.map(([, v]) => Math.abs(v)), 0.001);
  const rows = entries
    .map(([name, value]) => {
      const share = (Math.abs(value) / widest) * 50;
      const left = value >= 0 ? 50 : 50 - share;
      return `
        <li class="breakdown__row">
          <span class="breakdown__name">${escapeHtml(name.replace("USDT", ""))}</span>
          <span class="breakdown__track">
            <span class="breakdown__fill ${value >= 0 ? "up" : "down"}"
                  style="left:${left}%;width:${share}%"></span>
          </span>
          <span class="breakdown__value">${signed(value, 1)} R</span>
        </li>`;
    })
    .join("");
  return `
    <h3 class="panel__head">${escapeHtml(title)}</h3>
    <ul class="breakdown">${rows}</ul>`;
}

function renderCurve(curve, source) {
  const host = document.getElementById("verlauf");
  if (!host) return;

  document.querySelectorAll("#verlauf-source .segmented__item").forEach((item) => {
    item.setAttribute("aria-pressed", String(item.dataset.source === source));
  });

  if (curve === "unavailable") {
    host.innerHTML = `<p class="konto__state">Verlauf nicht lesbar.</p>`;
    return;
  }
  if (!curve.points.length) {
    host.innerHTML = `<p class="konto__state">Noch nichts abgeschlossen.</p>`;
    return;
  }

  const total = curve.points[curve.points.length - 1].cumulative_r;
  const count = curve.points.length;
  const mean = total / count;
  const warning =
    source === "live" && count < 30
      ? `<p class="figure__note">Zu wenige Trades für eine Aussage. Unter dreissig sagt
         ein Mittelwert mehr über den Zufall als über die Regeln.</p>`
      : "";

  host.innerHTML = `
    ${curveSvg(curve.points)}
    <div class="figures">
      <div>
        <div class="figure__label">Summe</div>
        <div class="figure__value ${total >= 0 ? "up" : "down"}">${signed(total, 1)} R</div>
        <div class="figure__note">über ${count} Trades</div>
      </div>
      <div>
        <div class="figure__label">Je Trade</div>
        <div class="figure__value ${mean >= 0 ? "up" : "down"}">${signed(mean, 3)} R</div>
        ${warning}
      </div>
      <div>
        <div class="figure__label">Grösster Rückgang</div>
        <div class="figure__value down">−${curve.drawdown_r.toFixed(1)} R</div>
        <div class="figure__note">vom eigenen Höchststand</div>
      </div>
      <div>
        <div class="figure__label">Bester / schlechtester</div>
        <div class="figure__value">${signed(curve.best_r, 1)} / ${signed(curve.worst_r, 1)}</div>
        <div class="figure__note">einzelner Trade</div>
      </div>
    </div>
    ${breakdown("Nach Markt", curve.by_symbol)}
    ${breakdown("Nach Setup", curve.by_setup)}`;
}

async function loadCurve() {
  const source = sources.verlauf;
  try {
    renderCurve(await api(`/api/portfolio/curve?source=${source}`), source);
  } catch {
    renderCurve("unavailable", source);
  }
}

/* --------------------------------------------------------------- wire ---- */

document.querySelectorAll("#trades-source .segmented__item").forEach((item) => {
  item.addEventListener("click", () => {
    sources.trades = item.dataset.source;
    loadLedger();
  });
});

document.querySelectorAll("#verlauf-source .segmented__item").forEach((item) => {
  item.addEventListener("click", () => {
    sources.verlauf = item.dataset.source;
    loadCurve();
  });
});

window.addEventListener("hashchange", () => showView(currentView()));
showView(currentView());
