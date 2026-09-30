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
    return `<div class="placeholder"><h2>No market data</h2>
      <p>Nothing is backfilled for the followed symbols yet.</p></div>`;
  }
  if (!view) {
    return `<div class="placeholder"><span class="pulse"></span><p>Reading the market&hellip;</p></div>`;
  }

  const change =
    view.candles.length > 1
      ? ((view.candles.at(-1).close - view.candles[0].open) / view.candles[0].open) * 100
      : 0;

  return `
  <header class="market__head">
    <span class="market__symbols" role="tablist" aria-label="Symbol">
      ${(state.symbols ?? [])
        .map(
          (s) => `<button type="button" role="tab" data-act="sym" data-sym="${s}"
                    aria-selected="${s === view.symbol}"
                    class="chart__tab${s === view.symbol ? " chart__tab--on" : ""}">${s}</button>`
        )
        .join("")}
    </span>

    <span class="market__price num">${fmt.price(view.price)}</span>
    <span class="market__change num ${change >= 0 ? "up" : "down"}">
      ${change >= 0 ? "+" : ""}${change.toFixed(2)}%
    </span>
    <span class="market__atr">ATR ${(view.atr_pct * 100).toFixed(2)}%</span>

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
      ${view.levels_hidden ? `<span class="chart__hidden">${view.levels_hidden} more not drawn</span>` : ""}
    </figcaption>
    <canvas class="chart__canvas" data-canvas="market"
            role="img"
            aria-label="Candlestick chart of ${escapeHtml(view.symbol)} on ${escapeHtml(
              view.timeframe
            )}, with the levels and structural events the analysis found."></canvas>
  </figure>

  ${frameTable(view)}

  <p class="chart__note">${escapeHtml(view.note)}</p>`;
}

/**
 * What each timeframe says, side by side.
 *
 * The single most useful thing on this screen, and the reason a chart alone is
 * not enough: a setup that reads well on the hour while the week is in a
 * downtrend is a different proposition, and a row of regimes shows that in one
 * glance where four charts would take four readings.
 */
function frameTable(view) {
  if (!view.frames?.length) return "";
  const marks = (f) =>
    [
      f.bos ? "BOS" : "",
      f.choch ? "CHoCH" : "",
      f.sweep_up ? "swept high" : "",
      f.sweep_down ? "swept low" : "",
    ]
      .filter(Boolean)
      .join(" · ");

  return `
  <table class="frames">
    <thead>
      <tr><th>Frame</th><th>Regime</th><th>Trend</th><th>Vol</th><th>Swings</th><th>Events</th></tr>
    </thead>
    <tbody>
      ${view.frames
        .map(
          (f) => `<tr>
        <th scope="row">${escapeHtml(f.timeframe)}</th>
        <td class="frames__regime frames__regime--${escapeHtml(f.regime)}">${escapeHtml(
          f.regime.replace("_", " ")
        )}</td>
        <td class="frames__trend frames__trend--${escapeHtml(f.trend)}">${escapeHtml(f.trend)}</td>
        <td>${escapeHtml(f.volatility)}</td>
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
  if (view.session) bits.push(`session <b>${escapeHtml(view.session)}</b>`);
  if (view.positioning) bits.push(`positioning <b>${escapeHtml(view.positioning.replace("_", " "))}</b>`);
  if (view.sentiment) bits.push(`sentiment <b>${escapeHtml(view.sentiment)}</b>`);
  for (const item of view.upcoming ?? []) bits.push(escapeHtml(item));
  return bits.length ? `<p class="market__context">${bits.join(" &middot; ")}</p>` : "";
}

async function loadMarket() {
  if (!state.symbols) {
    try {
      state.symbols = await api("/api/market");
    } catch {
      state.symbols = [];
    }
  }
  const symbol = state.symbol ?? state.symbols[0];
  if (!symbol) {
    state.market = "unavailable";
    return;
  }
  state.symbol = symbol;
  const tf = state.marketTimeframe ? `?timeframe=${state.marketTimeframe}` : "";
  try {
    state.market = await api(`/api/market/${symbol}/chart${tf}`);
  } catch {
    state.market = "unavailable";
  }
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
      <span class="pulse"></span><p>Loading the bars this was decided on&hellip;</p>
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
const sizeWatcher = new ResizeObserver(() => paintCharts());

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
            data-expires="${p.expires_ts}">${secondsLeft}s left</span>
    </header>

    <div class="ticket__body">
      ${ladder(p)}

      <dl class="figures">
        ${figure("Entry", fmt.price(p.entry), null, null, changed.has("entry"))}
        ${figure(
          "Stop",
          fmt.price(p.stop),
          `${fmt.pct(p.stop_distance_pct)} away`,
          "short",
          changed.has("stop")
        )}
        ${figure("Target", fmt.price(p.target), `R:R ${p.reward_risk.toFixed(2)}`, "long", changed.has("target"))}
        ${figure(
          "Liquidation",
          fmt.price(p.liquidation_price),
          `${p.liquidation_buffer_r.toFixed(1)}× the stop distance beyond it`,
          "liq",
          changed.has("liquidation_price")
        )}
        ${figure("Size", fmt.qty(p.qty), `${fmt.money(p.notional)} notional`, null, changed.has("qty"))}
        ${figure("Leverage", `${p.leverage}×`, `${fmt.money(p.margin)} margin`, null, changed.has("leverage"))}
        ${figure(
          "At risk",
          fmt.money(p.risk_amount),
          `${fmt.pct(p.risk_pct)} of ${fmt.money(p.equity)}`,
          null,
          changed.has("risk_amount")
        )}
        ${figure("Assessed risk", p.risk_level, p.bias, null, false)}

        <div class="reasoning">
          <h3>Why</h3>
          ${factorTable(p)}
          <ul>${p.reasoning.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>
          ${
            p.invalidation_note
              ? `<p class="invalidation"><b>Wrong if</b> ${escapeHtml(p.invalidation_note)}</p>`
              : ""
          }
        </div>
      </dl>
    </div>

    ${chartPanel(p)}

    <footer class="ticket__foot">
      <div class="dial">
        <label for="lev-${p.id}">Leverage</label>
        <span class="stepper">
          <button type="button" data-act="lev-down" aria-label="Lower leverage"
                  ${p.leverage <= 1 ? "disabled" : ""}>&minus;</button>
          <output id="lev-${p.id}">${p.leverage}×</output>
          <button type="button" data-act="lev-up" disabled
                  title="Raising leverage moves liquidation closer to the stop; that is a different trade"
                  aria-label="Raising leverage is not permitted">+</button>
        </span>
      </div>

      <div class="dial">
        <label>Risk</label>
        <span class="stepper">
          <button type="button" data-act="risk-down" aria-label="Halve the risk">&frac12;</button>
          <output>${fmt.pct(p.risk_pct)}</output>
        </span>
      </div>

      <span class="foot-spacer"></span>

      <button class="btn" type="button" data-act="decline">Decline</button>
      <button class="btn commit" type="button" data-act="commit"
              ${halted ? "disabled" : ""}
              aria-describedby="commit-help-${p.id}">
        <span class="commit__fill"></span>
        <span class="commit__label">${halted ? "Halted" : "Hold to send"}</span>
      </button>
      <span id="commit-help-${p.id}" hidden>Press and hold for just over a second to send this order.</span>

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
      <span>equity <b class="num">${fmt.money(sys.equity)}</b></span>
      <span>open <b class="num">${sys.open_positions}</b></span>
      <span class="flag ${sys.testnet ? "flag--testnet" : "flag--armed"}">
        ${sys.testnet ? "testnet" : "live money"}
      </span>
      ${sys.execution_connected ? "" : '<span class="flag">no exchange connected</span>'}
      ${sys.kill_switch_engaged ? '<span class="flag flag--halted">halted</span>' : ""}`
    : '<span class="pulse"></span>';

  const banners = document.getElementById("banners");
  let html = "";
  if (state.outcome) {
    html += `<div class="banner banner--${state.outcome.kind === "ok" ? "sent" : "blocked"}"
                  role="status">
      <h2>${state.outcome.kind === "ok" ? "Sent" : "Not sent"}</h2>
      <p>${escapeHtml(state.outcome.text)}</p>
    </div>`;
  }
  if (sys?.kill_switch_engaged) {
    html += `<div class="banner banner--halt">
      <h2>Trading is halted</h2>
      <p>${escapeHtml(sys.kill_switch_reason)} &mdash; nothing will be sent until this is cleared by hand.</p>
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
    list.innerHTML = `<div class="placeholder"><span class="pulse"></span><p>Loading&hellip;</p></div>`;
    return;
  }
  if (!state.proposals.length) {
    list.innerHTML = `<div class="placeholder">
      <h2>Nothing to decide</h2>
      <p>Most bars are not setups. This screen stays empty until the analysis finds
         something worth putting money on, which is the normal state.</p>
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
  state.hover = null;
  renderMarket();
  loadMarket().then(renderMarket);
});

function renderMarket() {
  const host = document.getElementById("market");
  if (!host) return;
  host.innerHTML = marketPanel();
  paintMarket();
  const canvas = host.querySelector("[data-canvas]");
  if (canvas) {
    wireMarketHover(canvas);
    sizeWatcher.observe(canvas);
  }
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
  document.querySelectorAll("[data-canvas]:not([data-canvas='market'])").forEach((canvas) => {
    wireChartHover(canvas);
    sizeWatcher.observe(canvas);
  });
  loadCharts();
  /* The market is refreshed on the same poll but rendered separately: it has no
   * hold gesture to interrupt, so it never has to wait for one. */
  loadMarket().then(renderMarket);
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
