"""The skill's opening-range breakout and Time Machine, vectorised with numpy.

Mirrors trader-timemachine's history_replay / simulate exactly:
- session = 78 five-minute bars; opening range = bars 0..2 (15 min)
- entry = close of the first bar i >= 3 whose close is beyond the range
  (long: > OR high), only while that bar closes by the entry cutoff
- stop = OR midpoint, target = entry + 1R, stop checked before target in a bar
- flat at the close of bar `last`
- Time Machine: pool[i] = (o,h,l,c)/prev close of bar i over prior full
  sessions, slot drawn from i +- window, stop before target.
Validated against the repo's own TSLA fixture in validate.py.
"""
import numpy as np

SESSION_BARS = 78
OR_BARS = 3
ENTRY_LAST_BAR = 71   # bar 71 closes 15:30 (no_entries_after 15:30)
FLAT_BAR = 76         # bar 76 closes 15:55 (flat by 15:55)


def orb_trades(S, side=1, target_r=1.0, last=FLAT_BAR, entry_last=ENTRY_LAST_BAR):
    """S: (D, 78, 4) o,h,l,c. Returns list of dicts (day index, k, entry, stop, target, outcome, R)."""
    out = []
    for d in range(S.shape[0]):
        D = S[d]
        oh, ol = D[:OR_BARS, 1].max(), D[:OR_BARS, 2].min()
        c = D[OR_BARS:entry_last + 1, 3]
        hit = np.nonzero(c > oh)[0] if side == 1 else np.nonzero(c < ol)[0]
        if hit.size == 0:
            continue
        k = OR_BARS + int(hit[0])
        e = D[k, 3]
        s = (oh + ol) / 2
        risk = (e - s) * side
        if risk <= 0:
            continue
        t = e + side * target_r * risk
        oc, R = "close", None
        for b in D[k + 1:last + 1]:
            if (b[2] <= s) if side == 1 else (b[1] >= s):
                oc, R = "stop", -1.0
                break
            if (b[1] >= t) if side == 1 else (b[2] <= t):
                oc, R = "target", target_r
                break
        if R is None:
            R = (D[last, 3] - e) * side / risk
        out.append({"d": d, "k": k, "entry": e, "stop": s, "target": t, "risk": risk, "outcome": oc, "R": R})
    return out


def build_pool(S):
    """S: (P, 78, 4) prior full sessions -> (78, P, 4) ratios to the previous close (row 0 unused)."""
    prev = S[:, :-1, 3:4]
    ratios = S[:, 1:, :] / prev
    pool = np.ones((SESSION_BARS, S.shape[0], 4))
    pool[1:] = ratios.transpose(1, 0, 2)
    return pool


def simulate(pool, entry, stop, target, k, last, side=1, replays=2000, window=2, rng=None):
    """Vectorised Monte Carlo. Returns (p_target, p_stop, p_neither, avg_R)."""
    rng = rng or np.random.default_rng(19)
    L = last - k
    if L <= 0:
        return None
    P = pool.shape[1]
    slots = np.arange(k + 1, last + 1)[None, :] + rng.integers(-window, window + 1, size=(replays, L))
    slots = np.clip(slots, 1, SESSION_BARS - 1)
    picks = rng.integers(0, P, size=(replays, L))
    r = pool[slots, picks]                     # (N, L, 4)
    closes = entry * np.cumprod(r[:, :, 3], axis=1)
    prevc = np.concatenate([np.full((replays, 1), entry), closes[:, :-1]], axis=1)
    hi, lo = prevc * r[:, :, 1], prevc * r[:, :, 2]
    if side == 1:
        sb, tb = lo <= stop, hi >= target
    else:
        sb, tb = hi >= stop, lo <= target
    big = L + 1
    fs = np.where(sb.any(1), sb.argmax(1), big)
    ft = np.where(tb.any(1), tb.argmax(1), big)
    stop_first = (fs <= ft) & (fs < big)
    targ_first = (ft < fs)
    neither = ~(stop_first | targ_first)
    risk = (entry - stop) * side
    rt = (target - entry) * side / risk
    Rs = np.where(targ_first, rt, np.where(stop_first, -1.0, (closes[:, -1] - entry) * side / risk))
    return float(targ_first.mean()), float(stop_first.mean()), float(neither.mean()), float(Rs.mean())


def lean(pt, ps, r=1.0):
    if pt + ps <= 0:
        return None
    return pt / (pt + ps) - 1.0 / (1.0 + r)


def verdict_class(pt, ps, r=1.0):
    d = lean(pt, ps, r)
    if d is None:
        return "none"
    if abs(d) < 0.05:
        return "coin_flip"
    if abs(d) < 0.15:
        return "leans_target" if d > 0 else "leans_stop"
    return "strong_target" if d > 0 else "strong_stop"
