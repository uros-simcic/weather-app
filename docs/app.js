import { CROSS_CHECK_LINKS, RADAR_ANIM_URL, SATELLITE_ANIM_URL } from './config.js';

const ICON_WHITELIST = new Set(['sun', 'partly', 'cloud', 'fog', 'rain', 'snow', 'storm']);
const HAIL_LEVELS = { none: 0, low: 1, medium: 2, high: 3 };
const COMPASS = ['S', 'SV', 'V', 'JV', 'J', 'JZ', 'Z', 'SZ'];
const SVGNS = 'http://www.w3.org/2000/svg';

// null = default "today" view (zdaj + today's remaining blocks). Otherwise a
// day date string ("YYYY-MM-DD") whose hourly blocks fill the top row.
let selectedDate = null;

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

function makeTemps(...parts) {
  const wrap = document.createElement('div');
  wrap.className = 'cell__temps';
  for (const { value, cls } of parts) {
    const span = document.createElement('span');
    span.className = cls;
    span.textContent = Math.round(value) + '°';
    span.setAttribute('aria-label', Math.round(value) + ' stopinj Celzija');
    wrap.appendChild(span);
  }
  return wrap;
}

function makeHumidityBadge(t, rh) {
  const el = document.createElement('div');
  if (t == null || t < 22) {
    el.className = 'badge badge--spacer';
    return el;
  }
  let cls = 'badge--neutral';
  if (rh >= 60 && t >= 26) cls = 'badge--red';
  else if (rh >= 60 && t >= 22) cls = 'badge--amber';
  el.className = 'badge ' + cls;
  el.textContent = rh + ' %';
  el.setAttribute('aria-label', 'Vlažnost ' + rh + ' odstotkov');
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
  if (wind_kmh != null && wind_kmh > 5) {
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

  function tick() {
    document.getElementById('header-clock').textContent =
      new Intl.DateTimeFormat('sl-SI', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Europe/Ljubljana' }).format(new Date());
  }
  tick();
  setInterval(tick, 1000);
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
    temps: [{ value: block.t, cls: block.t >= 30 ? 'cell__temp--hot' : '' }],
    rh: block.rh,
    uv: block.uv,
    wind_kmh: block.wind_kmh,
    wind_dir: block.wind_dir,
  });
}

function renderTopRow(forecast, now) {
  const row = document.getElementById('today-row');
  row.innerHTML = '';
  const days = forecast.days || [];
  const todayDate = days.length ? days[0].date : null;

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
      scrollRowTo(row, firstCell, startCell);
      return;
    }
    selectedDate = null; // selection went stale (e.g. rolled past midnight)
  }

  // Default: zdaj + today's not-yet-expired blocks.
  row.appendChild(buildCell({
    label: 'zdaj',
    icon: now.icon,
    drops: 0,
    pop: null,
    temps: [{ value: now.t, cls: now.t >= 30 ? 'cell__temp--hot' : '' }],
    rh: now.rh,
    uv: now.uv,
    wind_kmh: now.wind_kmh,
    wind_dir: now.wind_dir,
    isZdaj: true,
  }));

  const nowTs = Date.now();
  const todayBlocks = (days.length && days[0].blocks) || forecast.blocks || [];
  for (const block of todayBlocks) {
    if (new Date(block.end).getTime() <= nowTs) continue;
    row.appendChild(blockCell(block));
  }
  row.scrollLeft = 0;
}

function renderWeekRow(forecast, now) {
  const row = document.getElementById('week-row');
  row.innerHTML = '';
  // Skip today (days[0]) — it already fills the top row; showing it here too
  // is redundant. The week row is the 7 days ahead.
  for (const day of forecast.days.slice(1)) {
    row.appendChild(buildCell({
      label: day.name,
      icon: day.icon,
      drops: day.drops,
      pop: day.pop,
      temps: [
        { value: day.t_am, cls: 'cell__temp--am' },
        { value: day.t_pm, cls: day.t_pm >= 30 ? 'cell__temp--hot' : 'cell__temp--pm' },
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
  const radarImg = document.getElementById('radar-img');
  radarImg.onerror = () => panelFallback(
    document.getElementById('radar-panel'),
    'https://meteo.arso.gov.si/met/sl/weather/observ/radar', 'Radar padavin (ARSO)');
  radarImg.src = RADAR_ANIM_URL;

  const satVideo = document.getElementById('satellite-video');
  satVideo.onerror = () => panelFallback(
    document.getElementById('satellite-panel'),
    'https://meteo.arso.gov.si/met/sl/weather/observ/satelit', 'Satelitska slika (ARSO)');
  satVideo.querySelector('source').src = SATELLITE_ANIM_URL;
  satVideo.load();
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
  const block = forecast.blocks.find((b) => new Date(b.start) <= nowTs && nowTs < new Date(b.end))
    || forecast.blocks[0];
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
  } catch (e) {
    console.error('now.json broken, falling back to current forecast block', e);
    now = nowFromForecastFallback(forecast);
  }

  renderHeader(forecast);
  renderStaleBanner(forecast);
  renderTopRow(forecast, now);
  renderWeekRow(forecast, now);
  renderHailPill(now);
}

async function init() {
  // Same-origin, self-authored sprite (not user/API data) — innerHTML is safe here.
  const iconsResp = await fetch('icons.svg');
  const iconsText = await iconsResp.text();
  const iconsHolder = document.getElementById('icons-holder');
  iconsHolder.innerHTML = iconsText;

  renderLinks();
  renderPanels();
  await loadAndRender();

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
