# Audit findings — open items

Six-lens adversarial audit, opened 2026-07-25. Status re-checked against the
code on 2026-07-27; everything below was read and confirmed by hand, not just
asserted by an agent.

---

## Open

### LOW — today's row loses its scroll position on refresh
`docs/app.js` `renderTopRow()`. The *selected-day* branch now preserves the
reading position, but the default today branch still does `row.scrollLeft = 0`
unconditionally, so a focus/pageshow/30-min refresh yanks the row back to the
first block while you are reading a later one. Same class of bug as the one
fixed for selected days, different branch.
*Fix:* capture and restore `preservedScrollLeft` on this path too, but only when
the cell list is unchanged — the today row legitimately drops past blocks as the
day advances, and restoring a stale offset would then land on the wrong cell.

### LOW — humidity tier tests the raw value, the label shows the rounded one
`docs/app.js` `makeHumidityBadge()`. The amber/red thresholds compare raw `rh`
and `t` while the badge prints `Math.round(rh)`, so 59.6 % renders as "60 %" in
the neutral colour, and t=21.7 hides the badge although the cell above prints
22°. `tempClass()` deliberately uses the rounded, on-screen number — these two
should agree.
*Fix:* round before comparing, matching `tempClass`.

---

## Never examined

Three audit lenses have **still never run** — these areas are unexplored, not
clean. Two attempts (2026-07-25, 2026-07-27) both died on a spend/session limit
partway through.

- **aggregation** — is anything still averaged that shouldn't be (uv_index,
  cloud_cover, gusts)? Is min/max-of-blend the same as blend-of-min/max, or does
  it compress the daily range? Backtest train/holdout leakage?
- **pipeline** — non-atomic `forecast.json` writes racing the browser and
  `now.yml`; unbounded log growth; `if: always()` committing inconsistent state;
  sanity bounds applied before vs after the lag correction.
- **data** — empirical sanity sweep of live values against ARSO.

Re-run with the saved script, restricting `DIMENSIONS` to these three lenses:
`Workflow({scriptPath: "<session>/workflows/scripts/weather-app-audit-close-*.js"})`.
Run them **one lens at a time** — three concurrent Opus agents each doing ~15
tool calls is what blew the limit twice.

---

## Fixed (verified in code, do not re-litigate)

- **Satellite fallback link can never appear** — the `<source>` child is removed
  and `src` set on the `<video>` itself, so `error` fires where the handler is.
- **Header clock leaked a timer on every wake** — the live clock was dropped
  entirely; the only remaining `setInterval` is the 30-min refresh in `init()`.
- **Radar and satellite never refresh** — `renderPanels()` runs from
  `loadAndRender()` with a per-call cache buster.
- **A failed panel could never recover** — `panelFallback()` hid the media
  element instead of wiping the panel, and each attempt clears the stale link.
- **Selected day's scroll position reset on focus** — guarded by
  `lastScrolledDate`, with a `requestAnimationFrame` re-assert for iOS Safari.
- **Null temperature rendered as "0°"** — renders "–"; `tempClass` returns early
  so it is not styled cold.
- **Humidity badge could show "47.5 %"** — `Math.round(rh)` feeds both the text
  and the aria-label.
- **Negative precipitation was published** — LightGBM output is clamped with
  `max(0.0, value)`.
- **Daily drops disagreed with the published millimetres** — `daily_drops()` now
  takes the same rounded figure that `precip_mm` publishes, so 0.96 mm no longer
  prints "1.0 mm" with no drop against it.
- **Sub-threshold rain probability was shown** — `display_pop()` applies the
  `>= 30` gate to the raw value and rounds only survivors, and caps at
  `MAX_POP = 95`, so 99 % and 100 % are structurally unreachable.
- DST: both 2026 transitions produce correct offsets and contiguous blocks.
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
   stations 7–10 km away; Brda is at 135 m in the hills. Some cycles report only
   one of the two (`stations_used: ["NOVA_GORICA"]`). PWS **IBRDAM11 "Vipolže"**
   (45.98/13.54) is actually in Brda and online, but is not wired in — owner's
   call.
