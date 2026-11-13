const assert = require('assert').strict;
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const tests = [];
function test(name, run) { tests.push({ name, run }); }

// Run the actual browser module's data/render orchestration without starting
// its timers or making network requests. Drawing is captured at renderTopRow.
const source = fs.readFileSync(path.join(__dirname, '../docs/app.js'), 'utf8')
  .replace(/^import .*;$/m, '').replace(/^init\(\);$/m, '');
function app() {
  const context = vm.createContext({ console: { error() {} } });
  vm.runInContext(source, context);
  vm.runInContext(`
    renderHeader = renderStaleBanner = renderWeekRow = renderHailPill =
      renderLinks = renderPanels = () => {};
    paint = async () => {};
    renderTopRow = (forecast, now) => { globalThis.rendered = now; };
  `, context);
  return context;
}

test('station label uses the observation time in Ljubljana in both seasons', () => {
  const ctx = app();
  for (const observed_at of ['2026-11-12T13:00:00Z', '2026-07-12T12:00:00Z']) {
    assert.equal(ctx.currentConditionsLabel({ source: 'stations', observed_at }), 'zdaj · 14:00');
  }
  assert.equal(ctx.currentConditionsLabel({ source: 'stations' }), 'zdaj');
  assert.equal(ctx.currentConditionsLabel({ source: 'stations', observed_at: 'bad' }), 'zdaj');
});

test('stale station data renders a visibly labelled forecast fallback', async () => {
  const ctx = app();
  const now = Date.now();
  const forecast = { days: [{ blocks: [{ start: new Date(now - 60000).toISOString(),
    end: new Date(now + 60000).toISOString(), t: 14, icon: 'cloud' }] }] };
  ctx.fetchJson = async (name) => ({ value: name === 'forecast.json' ? forecast :
    { measured_at: new Date(now - 121 * 60000).toISOString(), t: 10, source: 'stations' } });
  await ctx.loadAndRender();
  assert.equal(ctx.rendered.t, 14);
  assert.equal(ctx.currentConditionsLabel(ctx.rendered), 'napoved');
});

test('fresh model fallback is also labelled as forecast', async () => {
  const ctx = app();
  ctx.fetchJson = async (name) => ({ value: name === 'forecast.json' ? {} :
    { measured_at: new Date().toISOString(), t: 14, source: 'model_fallback' } });
  await ctx.loadAndRender();
  assert.equal(ctx.currentConditionsLabel(ctx.rendered), 'napoved');
});

test('missing readings and no current forecast block do not invent current conditions', async () => {
  const ctx = app();
  ctx.fetchJson = async (name) => name === 'forecast.json' ? { value: { days: [] } } : { error: 'offline' };
  await ctx.loadAndRender();
  assert.equal(ctx.rendered, null);
});

(async () => {
  for (const { name, run } of tests) {
    await run();
    console.log('PASS ' + name);
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
