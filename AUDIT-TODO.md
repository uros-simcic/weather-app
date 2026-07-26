# Audit findings — open items

Six-lens adversarial audit, 2026-07-25. Three lenses completed (**time**,
**frontend**, **spec**) and produced 22 candidate findings; the automated
verifier pass and the other three lenses died on a spend limit. Everything
below was read and confirmed by hand, not just asserted by an agent.

Fixed items are in git history (`5f3bf55`, `c68d3d1`, `2aec7d3`).

---

## Not yet fixed

### HIGH — satellite fallback link can never appear
`docs/app.js` `renderPanels()`. The error handler is attached to the `<video>`
element, but a media element with a `<source>` child never fires `error` on
itself — only the `<source>` does. Confirmed empirically in Chrome. So if ARSO
renames the mp4 (their "latest" assets have moved before), the panel stays
blank forever instead of degrading to the text link.
*Fix:* set `satVideo.src = SATELLITE_ANIM_URL` directly and drop the `<source>`,
or attach the listener to the `<source>` element.

### MEDIUM — header clock leaks a timer on every wake
`docs/app.js` `renderHeader()` calls `setInterval(tick, 1000)` on every render,
and `loadAndRender` runs on `focus`, `pageshow`, `visibilitychange` and a 30-min
timer. Measured: three wake events → three extra 1 s timers, none cleared. A
phone left on this page accumulates them all day.
*Fix:* start the clock once in `init()`, or keep the id module-level and
`clearInterval` before re-arming.

### MEDIUM — radar and satellite never refresh
`renderPanels()` runs once in `init()`. Open at 08:00, return at 14:00: the rows
update but both images still show 08:00, with no cue they are stale.
*Fix:* call a refresh from `loadAndRender` with a cache-busting query param and
re-attach the error handlers.

### LOW — negative precipitation is published
`pipeline/blend.py`. LightGBM output is not clamped at 0, so dry hours
accumulate small negative values that subtract from the daily total. Observed
magnitude ~-0.1 mm; enough to push 1.05 mm down to 0.95 and flip `daily_drops`
from 1 to 0, i.e. a wet day rendering as dry.
*Fix:* `max(0.0, value)` for precipitation, and apply `daily_drops` to the
rounded sum so the day path matches the block path.

### LOW — sub-threshold rain probability is shown
`pipeline/blend.py` rounds pop to the nearest 5 *before* the frontend's `>= 30`
gate, so a blended 28 % is published as 30 and displayed — a value the spec says
to suppress, shown higher than the model produced.
*Fix:* apply the `>= 30` gate to the raw value in blend.py, round only survivors.

### LOW — selected day's scroll position is reset on focus
Tap a day, scroll to the evening blocks, switch tabs to a cross-check link and
back: `focus` → `loadAndRender` → `scrollRowTo` snaps back to 08-11.
*Fix:* only auto-scroll when `selectedDate` actually changed.

### LOW — null temperature renders as "0°"
`makeTemps` does `Math.round(null)` → 0, printed blue (below 5). Happens if a
block has no member data for temperature.
*Fix:* render "–" or an empty spacer when value is null, like `makePop` does.

### LOW — humidity badge can show "47.5 %"
Median of two stations reporting 47 and 48. Every other refresh shows an
integer. *Fix:* `Math.round(rh)` in both text and aria-label.

---

## Never examined

Three audit lenses never ran — these areas are **unexplored**, not clean:

- **aggregation** — is anything still averaged that shouldn't be
  (precipitation_probability, uv_index, cloud_cover)? Is min/max-of-blend the
  same as blend-of-min/max, or does it compress the daily range? Backtest
  train/holdout leakage?
- **pipeline** — non-atomic `forecast.json` writes racing the browser and
  `now.yml`; unbounded log growth; `if: always()` committing inconsistent state;
  sanity bounds applied before vs after the lag correction.
- **data** — empirical sanity sweep of live values against ARSO.

Re-run with the saved script (13 agents, batched verification):
`Workflow({scriptPath: "<scratchpad>/audit-workflow.js"})` — the original is at
`/private/tmp/claude-501/.../scratchpad/audit-workflow.js`; recreate it if the
scratchpad was cleared. Restrict `DIMENSIONS` to the three unrun lenses.

---

## Verified clean (do not re-litigate)

- DST: both 2026 transitions produce correct offsets and contiguous blocks;
  Open-Meteo returns a clean 24 hours on the fall-back day, no duplicate keys.
- Device-timezone independence: every date/time path passes
  `timeZone: 'Europe/Ljubljana'` explicitly.
- `new Date(x) <= nowTs` (Date vs number) is correct JS — relational operators
  coerce via `valueOf`. Only `==` would have been wrong.
- CSP: no violations; the three `innerHTML` sinks are constants or the
  self-authored sprite. All API data goes through `textContent`/`setAttribute`.
- Block wind direction genuinely comes from the max-speed hour, per spec §7.2.
- `selectedDate` rollover past midnight degrades correctly.

---

## Longer-running questions

1. **Precipitation blend choice.** ECMWF alone scores 0.115 on the holdout vs
   the shipped LightGBM's 0.142, but single members are not candidates in
   `backtest.py`'s selection. Deliberately not "fixed" on ERA5 evidence, since
   ERA5 *is* ECMWF's reanalysis and inflates it most for model-derived fields
   like rain. Settle it with station verification.
2. **ML vs weighted mean.** LightGBM won all four variables, but was trained and
   graded against ERA5. `verify.py` now scores against real station readings —
   it only started producing rows after the key fix in `c68d3d1`, so give it
   days before drawing conclusions.
3. **No station is in Brda.** Bilje (55 m) and Nova Gorica (113 m) are valley
   stations 7–10 km away; Brda is at 135 m in the hills. PWS **IBRDAM11
   "Vipolže"** (45.98/13.54) is actually in Brda and online, but is not wired in
   — owner's call.
