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
          <ul>${p.reasoning.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>
          ${
            p.invalidation_note
              ? `<p class="invalidation"><b>Wrong if</b> ${escapeHtml(p.invalidation_note)}</p>`
              : ""
          }
        </div>
      </dl>
    </div>

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
    default:
      break;
  }
});

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
refresh();
setInterval(refresh, POLL_MS);
setInterval(tickCountdowns, 1000);
