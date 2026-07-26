import { CROSS_CHECK_LINKS, RADAR_ANIM_URL, SATELLITE_ANIM_URL } from './config.js';

const ICON_WHITELIST = new Set(['sun', 'partly', 'cloud', 'fog', 'rain', 'snow', 'storm']);
const HAIL_LEVELS = { none: 0, low: 1, medium: 2, high: 3 };
const COMPASS = ['S', 'SV', 'V', 'JV', 'J', 'JZ', 'Z', 'SZ'];
const SVGNS = 'http://www.w3.org/2000/svg';

// null = default "today" view (zdaj + today's remaining blocks). Otherwise a
// day date string ("YYYY-MM-DD") whose hourly blocks fill the top row.
let selectedDate = null;
// Which day the top row was last auto-scrolled for, and the scroll offset at
// the moment of the last rebuild — together these keep a background refresh
// from moving the row under the user.
let lastScrolledDate = null;
let preservedScrollLeft = 0;

function iconRef(name, drops) {
  let resolved = ICON_WHITELIST.has(name) ? name : 'cloud';
  if (resolved === 'rain') resolved = drops >= 2 ? 'rain-heavy' : 'rain-light';
  return '#icon-' + resolved;
}

function compassLabel(deg) {
  if (deg == null) return '';
  return COMPASS[Math.round(deg / 45) % 8];
}

function makeIcon(name, drops) {
  const svg = document.createElementNS(SVGNS, 'svg');
  svg.classList.add('cell__icon');
  const use = document.createElementNS(SVGNS, 'use');
  use.setAttribute('href', iconRef(name, drops));
  svg.appendChild(use);
  return svg;
}

function makePop(pop) {
  const el = document.createElement('div');
  el.className = 'cell__pop';
  if (pop != null && pop >= 30) {
    el.textContent = Math.round(pop / 5) * 5 + ' %';
  }
  return el;
}

// Cold (blue) outranks everything, including the muted morning styling — a
// freezing morning is worth flagging. Hot stays off the morning value, which
// the spec keeps muted grey so the afternoon reads as the day's headline.
function tempClass(value, variant) {
  if (value == null) return variant || '';
  // Compare the rounded number, i.e. the one actually on screen: raw 4.6 prints
  // as "5" and must not be blue, raw 29.6 prints as "30" and must be red.
  const shown = Math.round(value);
  if (shown < 5) return 'cell__temp--cold';
  if (shown >= 30 && variant !== 'cell__temp--am') return 'cell__temp--hot';
  return variant || '';
}

function makeTemps(...parts) {
  const wrap = document.createElement('div');
  wrap.className = 'cell__temps';
  for (const { value, variant } of parts) {
    const span = document.createElement('span');
    span.className = tempClass(value, variant);
    if (value == null) {
      // Math.round(null) is 0, which printed a confident blue "0°" for a block
      // where no member reported a temperature at all.
      span.textContent = '–';
      span.setAttribute('aria-label', 'temperatura ni na voljo');
    } else {
      span.textContent = Math.round(value) + '°';
      span.setAttribute('aria-label', Math.round(value) + ' stopinj Celzija');
    }
    wrap.appendChild(span);
  }
  return wrap;
}

function makeHumidityBadge(t, rh) {
  const el = document.createElement('div');
  // rh is null whenever every station is stale (fetch_obs writes null rather
  // than guessing); without this check the badge rendered the string "null %".
  if (t == null || rh == null || t < 22) {
    el.className = 'badge badge--spacer';
    return el;
  }
  let cls = 'badge--neutral';
  if (rh >= 60 && t >= 26) cls = 'badge--red';
  else if (rh >= 60 && t >= 22) cls = 'badge--amber';
  el.className = 'badge ' + cls;
  // The station median can be fractional (47 and 48 -> 47.5); every other
  // refresh showed an integer, so round for a consistent badge.
  const shown = Math.round(rh);
  el.textContent = shown + ' %';
  el.setAttribute('aria-label', 'Vlažnost ' + shown + ' odstotkov');
  return el;
}

function makeUv(uv) {
  const el = document.createElement('div');
  if (uv == null || uv === 0) {
    el.className = 'cell__uv';
    return el;
  }
  let cls = 'cell__uv--grey';
  if (uv >= 8) cls = 'cell__uv--red cell__uv--bold';
  else if (uv >= 3) cls = 'cell__uv--orange';
  el.className = 'cell__uv ' + cls;
  el.textContent = 'UV ' + uv;
  el.setAttribute('aria-label', 'UV indeks ' + uv);
  return el;
}

// Simplified 3-tier scheme (calm/light hidden, then grey/orange/red) rather
// than a full Beaufort scale — matches common consumer weather-app
// conventions; the exact km/h cutoffs are a judgment call, not a standard.
function windColor(speed) {
  if (speed >= 20) return '#c93636';
  if (speed >= 12) return '#c98a12';
  return '#8a8a86';
}

function windFeathers(speed) {
  if (speed >= 20) return 3;
  if (speed >= 12) return 2;
  return 1;
}

function makeWindArrow(dir, speed) {
  const svg = document.createElementNS(SVGNS, 'svg');
  svg.classList.add('cell__wind');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'Veter ' + Math.round(speed) + ' km/h iz ' + compassLabel(dir));
  const color = windColor(speed);
  const g = document.createElementNS(SVGNS, 'g');
  g.setAttribute('stroke', color);
  g.setAttribute('stroke-width', '1.8');
  g.setAttribute('stroke-linecap', 'round');
  g.setAttribute('fill', color);
  g.setAttribute('transform', 'rotate(' + ((dir || 0) + 180) + ' 12 12)');

  const shaft = document.createElementNS(SVGNS, 'line');
  shaft.setAttribute('x1', '12'); shaft.setAttribute('y1', '20');
  shaft.setAttribute('x2', '12'); shaft.setAttribute('y2', '5');
  g.appendChild(shaft);

  const head = document.createElementNS(SVGNS, 'path');
  head.setAttribute('d', 'M8 8.5 L12 2 L16 8.5 Z');
  g.appendChild(head);

  const count = windFeathers(speed);
  for (let i = 0; i < count; i++) {
    const y = 20 - i * 2.6;
    const f = document.createElementNS(SVGNS, 'line');
    f.setAttribute('x1', '12'); f.setAttribute('y1', y);
    f.setAttribute('x2', '15'); f.setAttribute('y2', y - 2.2);
    g.appendChild(f);
  }

  svg.appendChild(g);
  return svg;
}

function buildCell({ label, icon, drops, pop, temps, rh, uv, wind_kmh, wind_dir, isZdaj, highlight, onClick }) {
  const cell = document.createElement('div');
  cell.className = 'cell card' + (isZdaj || highlight ? ' cell--selected' : '') + (onClick ? ' cell--tappable' : '');

  if (onClick) {
    cell.tabIndex = 0;
    cell.setAttribute('role', 'button');
    cell.addEventListener('click', onClick);
    cell.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); }
    });
  }

  const labelEl = document.createElement('div');
  labelEl.className = 'cell__label';
  labelEl.textContent = label;
  cell.appendChild(labelEl);

  const iconPop = document.createElement('div');
  iconPop.className = 'cell__iconpop';
  iconPop.appendChild(makeIcon(icon, drops || 0));
  iconPop.appendChild(makePop(pop));
  cell.appendChild(iconPop);

  cell.appendChild(makeTemps(...temps));
  cell.appendChild(makeHumidityBadge(temps[temps.length - 1].value, rh));
  cell.appendChild(makeUv(uv));

  // Calm wind renders an invisible spacer, not nothing — the cell uses
  // space-between, so a missing slot would redistribute all the others.
  // Direction must be known too: coercing a null bearing to 0 drew a confident
  // "from the north" arrow when the station reported speed but no direction.
  if (wind_kmh != null && wind_kmh > 5 && wind_dir != null) {
    cell.appendChild(makeWindArrow(wind_dir, wind_kmh));
  } else {
    const spacer = document.createElementNS(SVGNS, 'svg');
    spacer.classList.add('cell__wind', 'cell__wind--spacer');
    cell.appendChild(spacer);
  }

  return cell;
}

function renderHeader(forecast) {
  const now = new Date();
  const dayName = new Intl.DateTimeFormat('sl-SI', { weekday: 'long', timeZone: 'Europe/Ljubljana' }).format(now);
  const dateStr = new Intl.DateTimeFormat('sl-SI', { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'Europe/Ljubljana' }).format(now);
  document.getElementById('header-date').textContent =
    dayName.charAt(0).toUpperCase() + dayName.slice(1) + ', ' + dateStr.replace(/\./g, '.').replace(/\s/g, '') + ',';

  document.getElementById('header-sunrise').textContent = forecast.sun.sunrise;
  document.getElementById('header-sunset').textContent = forecast.sun.sunset;

  tickClock();
}

// Module-level so re-arming replaces the timer instead of stacking another one.
// renderHeader runs on every focus/pageshow/visibilitychange and on a 30-minute
// timer, so starting an interval inside it leaked one clock per wake event.
let clockTimer = null;

function tickClock() {
  const paint = () => {
    document.getElementById('header-clock').textContent =
      new Intl.DateTimeFormat('sl-SI', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Europe/Ljubljana' }).format(new Date());
  };
  paint();
  if (clockTimer !== null) clearInterval(clockTimer);
  clockTimer = setInterval(paint, 1000);
}

// Scroll the row so targetCell sits at the left edge. The distance between two
// cells (targetCell.offsetLeft - firstCell.offsetLeft) is independent of
// layout/offset-parent, unlike a bare offsetLeft. Re-assert once after layout
// settles — iOS Safari otherwise ignores a scroll set right after DOM insertion.
function scrollRowTo(row, firstCell, targetCell) {
  if (!targetCell || targetCell === firstCell) return;
  const setX = () => { row.scrollLeft = targetCell.offsetLeft - firstCell.offsetLeft; };
  setX();
  requestAnimationFrame(setX);
}

function blockCell(block) {
  return buildCell({
    label: block.label,
    icon: block.icon,
    drops: block.drops,
    pop: block.pop,
    temps: [{ value: block.t }],
    rh: block.rh,
    uv: block.uv,
    wind_kmh: block.wind_kmh,
    wind_dir: block.wind_dir,
  });
}

// Today's date in Brda's timezone as YYYY-MM-DD, matching forecast.json's keys.
// Derived from the clock, never from days[0]: a skipped or late pipeline run
// leaves yesterday first in the file, and assuming otherwise showed an empty
// "today" while today's real forecast sat in the week row labelled as tomorrow.
function localToday() {
  return new Intl.DateTimeFormat('en-CA', {
    year: 'numeric', month: '2-digit', day: '2-digit', timeZone: 'Europe/Ljubljana',
  }).format(new Date());
}

// Index of today in days[]. -1 when the data predates today entirely (a run
// skipped for more than a day), in which case callers fall back to days[0].
function todayIndex(days) {
  return days.findIndex((d) => d.date === localToday());
}

function renderTopRow(forecast, now) {
  const row = document.getElementById('today-row');
  // Captured before the rebuild so a same-day re-render can restore the user's
  // reading position instead of snapping back.
  preservedScrollLeft = row.scrollLeft;
  row.innerHTML = '';
  const days = forecast.days || [];
  const tIdx = todayIndex(days);
  const todayDate = tIdx >= 0 ? days[tIdx].date : (days.length ? days[0].date : null);

  // A future day is selected: show all its blocks, no zdaj. Open scrolled to
  // the 08-11 block so the morning leads (the pre-dawn blocks are legitimately
  // sparse — uv 0, humidity hidden < 22°C), but scrolling left still reveals them.
  if (selectedDate && selectedDate !== todayDate) {
    const day = days.find((d) => d.date === selectedDate);
    if (day && day.blocks) {
      let firstCell = null, startCell = null;
      for (const block of day.blocks) {
        const cell = blockCell(block);
        if (!firstCell) firstCell = cell;
        if (block.label === '08-11') startCell = cell;
        row.appendChild(cell);
      }
      // Only jump to 08-11 when the selection actually changed. A background
      // refresh (focus/pageshow/30-min timer) re-renders the same day, and
      // scrolling then yanked the user back from whatever hour they were reading.
      if (lastScrolledDate !== selectedDate) {
        scrollRowTo(row, firstCell, startCell);
        lastScrolledDate = selectedDate;
      } else {
        row.scrollLeft = preservedScrollLeft;
      }
      return;
    }
    selectedDate = null; // selection went stale (e.g. rolled past midnight)
  }

  // Default: zdaj + today's not-yet-expired blocks. `now` is null when both
  // now.json and the forecast fallback failed — show the forecast without a
  // current-conditions cell rather than fabricating one.
  if (now) {
    row.appendChild(buildCell({
      label: 'zdaj',
      icon: now.icon,
      drops: now.drops || 0,
      pop: null,
      temps: [{ value: now.t }],
      rh: now.rh,
      uv: now.uv,
      wind_kmh: now.wind_kmh,
      wind_dir: now.wind_dir,
      isZdaj: true,
    }));
  }

  const nowTs = Date.now();
  const todayDay = tIdx >= 0 ? days[tIdx] : days[0];
  const nextDay = tIdx >= 0 ? days[tIdx + 1] : days[1];
  // Include tomorrow's blocks as candidates: a day's list runs from 23:00 the
  // previous evening, so after 23:00 every one of today's blocks has expired
  // while the block actually covering "now" (tomorrow's 23-02) sits in the next
  // day. Without this the top row showed only zdaj for an hour every night.
  const candidates = [
    ...((todayDay && todayDay.blocks) || forecast.blocks || []),
    ...((nextDay && nextDay.blocks) || []),
  ];
  for (const block of candidates) {
    if (new Date(block.end).getTime() <= nowTs) continue;
    row.appendChild(blockCell(block));
  }
  row.scrollLeft = 0;
}

function renderWeekRow(forecast, now) {
  const row = document.getElementById('week-row');
  row.innerHTML = '';
  // Days after today only. Today already fills the top row, and any day before
  // it (left over when a pipeline run is skipped) is in the past — neither
  // belongs here.
  const tIdx = todayIndex(forecast.days);
  const startIdx = tIdx >= 0 ? tIdx + 1 : 1;
  for (const day of forecast.days.slice(startIdx)) {
    row.appendChild(buildCell({
      label: day.name,
      icon: day.icon,
      drops: day.drops,
      pop: day.pop,
      temps: [
        { value: day.t_am, variant: 'cell__temp--am' },
        { value: day.t_pm, variant: 'cell__temp--pm' },
      ],
      rh: day.rh_pm,
      uv: day.uv_max,
      wind_kmh: day.wind_kmh,
      wind_dir: day.wind_dir,
      highlight: selectedDate === day.date,
      onClick: () => {
        // Re-tap the selected day to return to the zdaj (today) view.
        selectedDate = selectedDate === day.date ? null : day.date;
        renderTopRow(forecast, now);
        renderWeekRow(forecast, now);
      },
    }));
  }
}

function renderHailPill(now) {
  const pill = document.getElementById('hail-pill');
  const rawStatus = (now.hail && now.hail.status) || 'none';
  const level = HAIL_LEVELS[rawStatus] ?? 0;
  const tier = level >= 3 ? 'high' : level >= 2 ? 'medium' : 'low';
  pill.classList.remove('hail-pill--low', 'hail-pill--medium', 'hail-pill--high');
  pill.classList.add('hail-pill--' + tier);
  pill.textContent = 'Verjetnost toče: ' + level + '/3';
  pill.hidden = false;
}

function renderLinks() {
  const wrap = document.getElementById('links');
  wrap.innerHTML = '';
  for (const { label, href } of CROSS_CHECK_LINKS) {
    const a = document.createElement('a');
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.className = 'card' + (label === 'ARSO' ? ' links__arso' : '');
    a.textContent = label;
    wrap.appendChild(a);
  }
}

function panelFallback(panel, href, label) {
  panel.innerHTML = '';
  const a = document.createElement('a');
  a.href = href;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  a.className = 'panel__fallback';
  a.textContent = label;
  panel.appendChild(a);
}

function renderPanels() {
  // Cache-bust on every call: these are live nowcast loops, and without this a
  // page left open all day kept showing the animation it loaded at startup.
  const bust = '?t=' + Date.now();

  const radarPanel = document.getElementById('radar-panel');
  const radarImg = radarPanel && radarPanel.querySelector('img');
  if (radarImg) {
    radarImg.onerror = () => panelFallback(
      radarPanel,
      'https://meteo.arso.gov.si/met/sl/weather/observ/radar', 'Radar padavin (ARSO)');
    radarImg.src = RADAR_ANIM_URL + bust;
  }

  const satPanel = document.getElementById('satellite-panel');
  const satVideo = satPanel && satPanel.querySelector('video');
  if (satVideo) {
    // Set src on the media element itself rather than on a <source> child: a
    // media element with a <source> never fires `error` on itself — only the
    // <source> does — so the fallback link could never appear if ARSO moved
    // the file (verified in Chrome).
    const staleSource = satVideo.querySelector('source');
    if (staleSource) staleSource.remove();
    satVideo.onerror = () => panelFallback(
      satPanel,
      'https://meteo.arso.gov.si/met/sl/weather/observ/satelit', 'Satelitska slika (ARSO)');
    satVideo.src = SATELLITE_ANIM_URL + bust;
    satVideo.load();
  }
}

function renderStaleBanner(forecast) {
  const banner = document.getElementById('stale-banner');
  const generated = new Date(forecast.generated_at);
  const ageHours = (Date.now() - generated.getTime()) / 3600000;
  if (ageHours > (forecast.stale_after_hours ?? 24)) {
    const ts = new Intl.DateTimeFormat('sl-SI', {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Ljubljana',
    }).format(generated);
    banner.textContent = 'Podatki zastareli (' + ts + ')';
    banner.hidden = false;
  } else {
    banner.hidden = true;
  }
}

// now.json can go missing or fail to parse (e.g. mid-write during a pipeline
// run); fall back to the current forecast block's values and say so in the
// console, never silently show stale/wrong data as if it were fresh (§7.8).
function nowFromForecastFallback(forecast) {
  const nowTs = Date.now();
  // Search every day's blocks, not just the top-level (today's) list — after
  // 23:00 the bracketing block belongs to tomorrow. Returning blocks[0] when
  // nothing brackets now would have shown last night's 23:00 reading as current.
  const all = (forecast.days || []).flatMap((d) => d.blocks || []);
  const block = (all.length ? all : forecast.blocks || [])
    .find((b) => new Date(b.start) <= nowTs && nowTs < new Date(b.end));
  if (!block) return null;
  return {
    t: block.t, rh: block.rh, wind_kmh: block.wind_kmh, wind_dir: block.wind_dir,
    icon: block.icon, uv: block.uv, hail: { status: 'none' },
  };
}

async function loadAndRender() {
  let forecast;
  try {
    forecast = await fetch('forecast.json?t=' + Date.now()).then((r) => r.json());
  } catch (e) {
    console.error('forecast.json fetch/parse failed, keeping previous render', e);
    return;
  }

  let now;
  try {
    now = await fetch('now.json?t=' + Date.now()).then((r) => r.json());
    if (now == null || typeof now.t !== 'number') throw new Error('now.json missing expected fields');
    // measured_at is naive Ljubljana local; compare against the same wall clock.
    // Without this an outage froze now.json and hours-old readings kept being
    // presented as current, with no banner and a live-ticking header clock.
    const measuredAge = (Date.now() - new Date(now.measured_at + '+02:00').getTime()) / 60000;
    if (Number.isFinite(measuredAge) && measuredAge > 120) {
      throw new Error('now.json is ' + Math.round(measuredAge) + ' min old');
    }
  } catch (e) {
    console.error('now.json unusable, falling back to the current forecast block', e);
    now = nowFromForecastFallback(forecast);
  }

  renderHeader(forecast);
  renderStaleBanner(forecast);
  // Radar and satellite are live loops: refresh them alongside the data, or a
  // page left open keeps showing the animation it loaded hours ago.
  renderPanels();
  // A null fallback means no block brackets the current time either; render the
  // forecast rows without a zdaj cell rather than inventing a reading.
  renderTopRow(forecast, now);
  renderWeekRow(forecast, now);
  if (now) renderHailPill(now);
}

async function init() {
  // Same-origin, self-authored sprite (not user/API data) — innerHTML is safe here.
  // Cache-busted like the JSON: without it a browser keeps the old sprite after
  // an icon change, so redesigned symbols never reach anyone already using the page.
  const iconsResp = await fetch('icons.svg?t=' + Date.now());
  const iconsText = await iconsResp.text();
  const iconsHolder = document.getElementById('icons-holder');
  iconsHolder.innerHTML = iconsText;

  renderLinks();
  await loadAndRender();  // renders the panels too

  // Mobile browsers suspend timers aggressively; pageshow/focus cover the
  // wake-up paths visibilitychange misses, so a reopened page can't keep
  // showing hours-old zdaj values.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') loadAndRender();
  });
  window.addEventListener('pageshow', loadAndRender);
  window.addEventListener('focus', loadAndRender);
  setInterval(loadAndRender, 30 * 60 * 1000);
}

init();
