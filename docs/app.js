import { CROSS_CHECK_LINKS, RADAR_ANIM_URL, SATELLITE_ANIM_URL } from './config.js';

const ICON_WHITELIST = new Set(['sun', 'partly', 'cloud', 'fog', 'rain', 'snow', 'storm']);
const HAIL_LEVELS = { none: 0, low: 1, medium: 2, high: 3 };
const COMPASS = ['S', 'SV', 'V', 'JV', 'J', 'JZ', 'Z', 'SZ'];
const SVGNS = 'http://www.w3.org/2000/svg';

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
  else if (uv >= 3) cls = 'cell__uv--amber';
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
  return '#3a3a37';
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

function buildCell({ label, icon, drops, pop, temps, rh, uv, wind_kmh, wind_dir, isZdaj }) {
  const cell = document.createElement('div');
  cell.className = 'cell card' + (isZdaj ? ' cell--zdaj' : '');

  const labelEl = document.createElement('div');
  labelEl.className = 'cell__label';
  labelEl.textContent = label;
  cell.appendChild(labelEl);

  cell.appendChild(makeIcon(icon, drops || 0));
  cell.appendChild(makePop(pop));
  cell.appendChild(makeTemps(...temps));
  cell.appendChild(makeHumidityBadge(temps[temps.length - 1].value, rh));
  cell.appendChild(makeUv(uv));
  if (wind_kmh != null && wind_kmh > 5) cell.appendChild(makeWindArrow(wind_dir, wind_kmh));

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

function renderTodayRow(forecast, now) {
  const row = document.getElementById('today-row');
  row.innerHTML = '';

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
  for (const block of forecast.blocks) {
    if (new Date(block.end).getTime() <= nowTs) continue;
    row.appendChild(buildCell({
      label: block.label,
      icon: block.icon,
      drops: block.drops,
      pop: block.pop,
      temps: [{ value: block.t, cls: block.t >= 30 ? 'cell__temp--hot' : '' }],
      rh: block.rh,
      uv: block.uv,
      wind_kmh: block.wind_kmh,
      wind_dir: block.wind_dir,
    }));
  }
}

function renderWeekRow(forecast) {
  const row = document.getElementById('week-row');
  row.innerHTML = '';
  for (const day of forecast.days) {
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

function renderPanels() {
  const radarImg = document.getElementById('radar-img');
  radarImg.src = RADAR_ANIM_URL;
  const satVideo = document.getElementById('satellite-video');
  satVideo.querySelector('source').src = SATELLITE_ANIM_URL;
  satVideo.load();
}

async function init() {
  // Same-origin, self-authored sprite (not user/API data) — innerHTML is safe here.
  const iconsResp = await fetch('icons.svg');
  const iconsText = await iconsResp.text();
  const iconsHolder = document.getElementById('icons-holder');
  iconsHolder.innerHTML = iconsText;

  const [forecast, now] = await Promise.all([
    fetch('forecast.json?t=' + Date.now()).then((r) => r.json()),
    fetch('now.json?t=' + Date.now()).then((r) => r.json()),
  ]);

  renderHeader(forecast);
  renderTodayRow(forecast, now);
  renderWeekRow(forecast);
  renderHailPill(now);
  renderLinks();
  renderPanels();
}

init();
