/* Presentation unit checks; these are not browser or visual acceptance. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.env.DESK_SCRIPT, 'utf8');
function element(id, dataset = {}) {
  return {id, dataset, attrs: {}, style: {}, events: {}, hidden: false,
    setAttribute(k, v) { this.attrs[k] = v; },
    getAttribute(k) { return this.attrs[k]; },
    addEventListener(k, fn) { this.events[k] = fn; },
    focus() { this.focused = true; }, scrollIntoView() {},
    contains(other) { return other.parent === this; }};
}
function desk({stored = '{}', denied = false, hash = '', gap = false} = {}) {
  const buttons = ['summary', 'execution'].map(id => element('tab-' + id, {panel: id}));
  const panels = buttons.map(b => element(b.dataset.panel));
  const target = element('fill'); target.parent = panels[1];
  const nav = element('nav', {tabs: 'desk'}); nav.querySelectorAll = () => buttons;
  const ranges = ['5', '20', 'all'].map(range => element(range, {range}));
  const checks = ['deterministic_equity', 'spy_equity', 'cash-line'].map(series => {
    const e = element(series, {series}); e.checked = true; return e;
  });
  const line = element('line');
  line.attrs.points = Array.from({length: gap ? 3 : 11}, (_, i) => `${60 + i * 62},${100-i}`).join(' ');
  const axis = {start: element('start'), first: element('first')};
  const chart = element('chart', {sessions: JSON.stringify(Array.from({length: 10}, (_, i) => 'day-' + (i+1)))});
  chart.querySelectorAll = selector => selector === 'polyline' ? [line] : [element(selector)];
  chart.querySelector = selector => axis[selector.includes('start') ? 'start' : 'first'];
  const body = {dataset: {population: 'fixture'}, classList: {add() {}}};
  const document = {body, addEventListener(){},
    getElementById: id => [...panels, target].find(e => e.id === id),
    querySelector: () => chart,
    querySelectorAll: selector => ({'[data-tabs]': [nav], '[data-range]': ranges,
      '[data-series]': checks, 'a[href^="#"]': []})[selector]};
  const events = {};
  const context = {AbortController, document, location: {hash}, sessionStorage: {
    getItem() { if (denied) throw Error('denied'); return stored; },
    setItem(key, value) { if (denied) throw Error('denied'); stored = value; }
  }, addEventListener: (key, fn) => {events[key] = fn;}};
  vm.runInNewContext(source, context);
  return {buttons, panels, ranges, checks, line, axis, context, events, stored: () => JSON.parse(stored)};
}
test('tabs switch without touching graph and card; keyboard wraps', () => {
  const d = desk(); assert.equal(d.panels[1].hidden, true);
  const points = d.line.attrs.points;
  d.buttons[1].events.click(); assert.equal(d.panels[0].hidden, true);
  assert.equal(d.buttons[1].attrs['aria-selected'], 'true');
  d.buttons[1].events.keydown({key: 'ArrowRight', preventDefault() {}});
  assert.equal(d.buttons[0].focused, true); assert.equal(d.panels[0].hidden, false);
  assert.equal(d.line.attrs.points, points);
});
test('restores selected panel and range, namespaced state', () => {
  const d = desk({stored: '{"desk":"execution","range":"5"}'});
  assert.equal(d.panels[1].hidden, false);
  assert.equal(d.line.attrs.points.split(' ').length, 6);
  assert.equal(d.axis.start.textContent, 'day-5');
  assert.equal(d.stored().range, '5');
});
test('range changes preserve actual y values and do not rebase returns', () => {
  const d = desk(); d.ranges[0].events.click();
  assert.equal(d.line.attrs.points, '60.00,95 184.00,94 308.00,93 432.00,92 556.00,91 680.00,90');
  d.ranges[2].events.click(); assert.equal(d.axis.start.textContent, 'Initial');
  assert.equal(d.line.attrs.points.split(' ').length, 11);
});
test('missing prefix does not become an invented line in a later range', () => {
  const d = desk({gap: true}); d.ranges[0].events.click();
  assert.equal(d.line.attrs.points, '');
});
test('hash opens containing panel even when saved selection differs', () => {
  const d = desk({hash: '#fill'}); assert.equal(d.panels[1].hidden, false);
});
test('storage denial and malformed stored types do not break enhancement', () => {
  for (const stored of ['5', 'null', '[]', '{bad']) {
    assert.equal(desk({stored}).panels[0].hidden, false);
  }
  assert.equal(desk({denied: true}).panels[0].hidden, false);
});
test('benchmark controls persist display only', () => {
  const d = desk(); d.checks[1].checked = false; d.checks[1].events.change();
  assert.equal(d.stored().spy_equity, false);
});
