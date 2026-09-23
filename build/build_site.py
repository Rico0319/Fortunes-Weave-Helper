#!/usr/bin/env python3
"""
Generate index.html — a self-contained, offline-capable recruitment planner
and build reference for Fire Emblem: Fortune's Weave.

The dataset is inlined into the page so it works from file:// with no server
and no network (handy inside the Orca browser).

The page builds its DOM with createElement rather than innerHTML, so scraped
strings can never be interpreted as markup.

Usage:
    python3 build/build_site.py
"""
from __future__ import annotations

import json
from pathlib import Path

BUILD = Path(__file__).parent
ROOT = BUILD.parent
DATA = ROOT / "data" / "fwe.json"
OUT = ROOT / "index.html"

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fortune's Weave — Recruitment &amp; Build Planner</title>
<style>
  :root {
    --bg: #12141a; --panel: #1a1d26; --panel2: #212533; --line: #2e3342;
    --ink: #e8eaf0; --dim: #9aa3b8; --faint: #6b7386;
    --accent: #e0a34a; --good: #4fb477; --warn: #d9a13b; --bad: #cf5f5f;
    --lord: #d4af37; --s: #e06c75; --a: #d19a66; --b: #61afef; --c: #7f8698;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  a { color: var(--accent); }
  header {
    position: sticky; top: 0; z-index: 20; background: #161922f2;
    backdrop-filter: blur(8px); border-bottom: 1px solid var(--line);
    padding: 10px 16px; display: flex; gap: 16px; align-items: center; flex-wrap: wrap;
  }
  h1 { font-size: 15px; margin: 0; font-weight: 600; letter-spacing: .2px; }
  h1 span { color: var(--faint); font-weight: 400; }
  .ctl { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--dim); }
  select, input[type=number], input[type=search] {
    background: var(--panel2); color: var(--ink); border: 1px solid var(--line);
    border-radius: 6px; padding: 5px 8px; font: inherit; font-size: 12px;
  }
  input[type=number] { width: 64px; }
  input[type=search] { width: 190px; }
  nav { display: flex; gap: 4px; margin-left: auto; }
  nav button {
    background: transparent; color: var(--dim); border: 1px solid transparent;
    border-radius: 6px; padding: 6px 11px; font: inherit; font-size: 12px; cursor: pointer;
  }
  nav button:hover { color: var(--ink); background: var(--panel2); }
  nav button.on { color: #12141a; background: var(--accent); font-weight: 600; }
  main { padding: 16px; max-width: 1500px; margin: 0 auto; }
  section { display: none; }
  section.on { display: block; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 14px; }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; }
  .card .k { font-size: 11px; color: var(--faint); text-transform: uppercase; letter-spacing: .5px; }
  .card .v { font-size: 22px; font-weight: 600; margin-top: 2px; }
  .card .v small { font-size: 12px; color: var(--dim); font-weight: 400; }
  .bar { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 12px; }
  .bar .spacer { flex: 1; }
  table { width: 100%; border-collapse: collapse; background: var(--panel); border-radius: 8px; overflow: hidden; }
  th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--line); vertical-align: middle; }
  th { background: var(--panel2); font-size: 11px; text-transform: uppercase; letter-spacing: .5px; color: var(--dim); position: sticky; top: 57px; z-index: 10; white-space: nowrap; }
  tr:last-child td { border-bottom: none; }
  tr.done { opacity: .42; }
  tr.done .unit { text-decoration: line-through; }
  .unit { font-weight: 600; white-space: nowrap; }
  .sub { color: var(--faint); font-size: 11px; }
  .badge { display: inline-block; min-width: 19px; text-align: center; padding: 1px 5px; border-radius: 4px; font-size: 10px; font-weight: 700; color: #12141a; }
  .t-Lord { background: var(--lord); } .t-S { background: var(--s); }
  .t-A { background: var(--a); } .t-B { background: var(--b); } .t-C { background: var(--c); }
  .t-unknown { background: var(--faint); }
  .pill { display: inline-block; padding: 1px 7px; border-radius: 10px; font-size: 11px; font-weight: 600; border: 1px solid var(--line); }
  .p-ready { color: var(--good); border-color: #2c6b48; background: #16301f; }
  .p-need  { color: var(--warn); border-color: #6b5620; background: #2c2413; }
  .p-block { color: var(--bad);  border-color: #6b2c2c; background: #2c1616; }
  .p-done  { color: var(--dim); }
  .p-auto  { color: var(--b);    border-color: #2c4a6b; background: #16202c; }
  .seg { display: inline-flex; border: 1px solid var(--line); border-radius: 5px; overflow: hidden; }
  .seg button { background: var(--panel2); color: var(--dim); border: 0; padding: 2px 6px; font: inherit; font-size: 11px; cursor: pointer; }
  .seg button + button { border-left: 1px solid var(--line); }
  .seg button.on { background: var(--accent); color: #12141a; font-weight: 700; }
  .seg button.met { color: var(--good); }
  .seg button.on.met { color: #12141a; }
  input[type=checkbox] { accent-color: var(--accent); width: 15px; height: 15px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 12px; }
  .bcard { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px; }
  .bcard h3 { margin: 0 0 2px; font-size: 15px; display: flex; align-items: center; gap: 7px; }
  .bcard .sk { color: var(--accent); font-size: 12px; margin: 6px 0 2px; font-weight: 600; }
  .bcard .skd { color: var(--dim); font-size: 11.5px; }
  .grow { display: grid; grid-template-columns: repeat(9, 1fr); gap: 3px; margin: 9px 0 4px; }
  .g { text-align: center; }
  .g .lbl { font-size: 9.5px; color: var(--faint); }
  .g .num { font-size: 11px; font-weight: 600; }
  .g .track { height: 3px; background: var(--panel2); border-radius: 2px; overflow: hidden; margin-top: 2px; }
  .g .fill { height: 100%; background: var(--accent); }
  .tag { font-size: 10.5px; color: var(--dim); border: 1px solid var(--line); border-radius: 4px; padding: 1px 6px; }
  .tag.hot { color: var(--accent); border-color: #6b5620; }
  .prog { font-size: 12px; color: var(--ink); margin-top: 8px; }
  .prog em { color: var(--faint); font-style: normal; }
  .note { color: var(--dim); font-size: 12px; margin: 0 0 12px; }
  .gift { font-size: 11.5px; color: var(--dim); }
  .gift b { color: var(--good); font-weight: 600; }
  details { margin-top: 8px; }
  summary { cursor: pointer; color: var(--faint); font-size: 11.5px; }
  .foot { color: var(--faint); font-size: 11px; margin-top: 22px; line-height: 1.7; }
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  .r { text-align: right; }
  .btn { background: var(--panel2); color: var(--dim); border: 1px solid var(--line); border-radius: 6px; padding: 5px 10px; font: inherit; font-size: 12px; cursor: pointer; }
  .btn:hover { color: var(--ink); }
  @media (max-width: 760px) { nav { margin-left: 0; } th { top: 0; position: static; } }
</style>
</head>
<body>
<header>
  <h1>Fortune's Weave <span>· planner</span></h1>
  <div class="ctl">Route <select id="route"></select></div>
  <div class="ctl">Renown <input id="renown" type="number" min="1" max="15" value="11"></div>
  <nav>
    <button data-tab="recruit" class="on">Recruitment</button>
    <button data-tab="builds">Builds</button>
    <button data-tab="classes">Classes</button>
    <button data-tab="gifts">Gifts</button>
    <button data-tab="late">Part II/III</button>
  </nav>
</header>
<main>
  <section id="recruit" class="on">
    <div class="cards" id="sum"></div>
    <div class="bar">
      <input type="search" id="q" placeholder="Filter by name…">
      <label class="ctl"><input type="checkbox" id="hideDone"> hide recruited</label>
      <label class="ctl"><input type="checkbox" id="onlyGaps"> only gaps</label>
      <span class="spacer"></span>
      <button class="btn" id="reset">reset progress</button>
    </div>
    <table>
      <thead><tr>
        <th style="width:34px">✓</th><th>Unit</th><th>Tier</th><th>Support</th>
        <th>Renown</th><th>Extra requirement</th><th>Status</th>
      </tr></thead>
      <tbody id="rows"></tbody>
    </table>
    <p class="note" id="recruitNote"></p>
  </section>

  <section id="builds">
    <div class="bar">
      <input type="search" id="bq" placeholder="Filter by name…">
      <label class="ctl"><input type="checkbox" id="onlyRecruited"> only recruited</label>
      <span class="spacer"></span>
    </div>
    <div class="grid" id="bcards"></div>
  </section>

  <section id="classes">
    <p class="note">Certification happens at the <b>Exam Proctor</b> in Dagsion (Hightown) during Free Time. Class growth bonuses are <b>added</b> to a unit's base growths.</p>
    <div id="classtiers"></div>
  </section>

  <section id="gifts">
    <p class="note">Gifts matching a unit's tastes give the most support per gift. Use this to close out the support requirement on anyone you still need.</p>
    <table>
      <thead><tr><th>Unit</th><th>Needed</th><th>Loved gifts</th><th>Really liked</th><th>Likes / interests</th></tr></thead>
      <tbody id="giftrows"></tbody>
    </table>
  </section>

  <section id="late">
    <p class="note">These units cannot be recruited in Part I. Several are gated behind paralogues you must clear earlier, so treat this as a Part I to-do list.</p>
    <table>
      <thead><tr><th>Unit</th><th>Availability</th><th>Condition</th></tr></thead>
      <tbody id="laterows"></tbody>
    </table>
  </section>

  <p class="foot" id="foot"></p>
</main>

<script id="fwe-data" type="application/json">__DATA__</script>
<script>
'use strict';

/* ------------------------------------------------------------------ *
 * dataset
 * ------------------------------------------------------------------ */
function readDataset() {
  const node = document.getElementById('fwe-data');
  try {
    return JSON.parse(node.textContent);
  } catch (error) {
    throw new Error('planner: embedded dataset is corrupt — rebuild via build/build_site.py');
  }
}

const DOC = readDataset();
const UNITS = DOC.units;
const TIERS = DOC.meta.tier_labels;
const STATS = DOC.meta.stats;
const STORE = 'fwe-planner-v1';
const DEFAULTS = {
  route: 'Cai', renown: 11, recruited: {}, support: {}, extras: {},
  hideDone: false, onlyGaps: false, onlyRecruited: false, q: '', bq: '', tab: 'recruit'
};

/* ------------------------------------------------------------------ *
 * DOM helper — builds nodes, so data is never parsed as markup
 * ------------------------------------------------------------------ */
function el(tag, props, ...kids) {
  const node = document.createElement(tag);
  if (props) {
    for (const [key, value] of Object.entries(props)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = String(value);
      else if (key === 'dataset') Object.assign(node.dataset, value);
      else if (key === 'style') Object.assign(node.style, value);
      else if (key === 'on') for (const [evt, fn] of Object.entries(value)) node.addEventListener(evt, fn);
      else if (key in node) node[key] = value;
      else node.setAttribute(key, value);
    }
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.appendChild(typeof kid === 'object' ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

const clear = (parent, ...kids) => parent.replaceChildren(...kids.flat(Infinity).filter(Boolean));

const frag = (nodes) => nodes.flat(Infinity).filter(Boolean);

/** Colour a growth delta: positive good, negative bad, zero neutral. */
function growthColor(value, zeroColor) {
  if (value > 0) return 'var(--good)';
  if (value < 0) return 'var(--bad)';
  return zeroColor;
}

/* ------------------------------------------------------------------ *
 * state
 * ------------------------------------------------------------------ */
function loadState() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORE) || '{}');
    if (!saved || typeof saved !== 'object') return Object.assign({}, DEFAULTS);
    return Object.assign({}, DEFAULTS, saved);
  } catch (error) {
    console.warn('planner: saved progress was unreadable, starting fresh', error);
    return Object.assign({}, DEFAULTS);
  }
}

let state = loadState();

function save() {
  try {
    localStorage.setItem(STORE, JSON.stringify(state));
  } catch (error) {
    console.warn('planner: could not persist progress', error);
  }
}

/* ------------------------------------------------------------------ *
 * derived helpers
 * ------------------------------------------------------------------ */
const tierRank = (t) => TIERS.indexOf(t);
const tierClass = (t) => 'badge t-' + (TIERS.includes(t) ? t : 'unknown');
const reqOf = (name, route) => (UNITS[name].recruit || {})[route] || null;
const isDone = (n) => !!state.recruited[n];
const suppOf = (n) => state.support[n] || 0;
const extraOk = (n) => !!state.extras[n];

function statusOf(name) {
  const r = reqOf(name, state.route);
  if (!r) return { key: 'na', label: 'not on route', cls: 'p-block' };
  if (isDone(name)) return { key: 'done', label: 'recruited', cls: 'p-done' };
  if (!r.support && !r.renown) return { key: 'auto', label: 'auto-joins', cls: 'p-auto' };
  const needSupport = r.support > suppOf(name);
  const needRenown = r.renown > state.renown;
  const needExtra = (r.extra || []).length > 0 && !extraOk(name);
  if (!needSupport && !needRenown && !needExtra) return { key: 'ready', label: 'READY', cls: 'p-ready' };
  const bits = [];
  if (needRenown) bits.push('R' + r.renown);
  if (needSupport) bits.push('S' + r.support);
  if (needExtra) bits.push('extra');
  return { key: 'need', label: 'need ' + bits.join(' + '), cls: 'p-need' };
}

function routeTargets() {
  return Object.keys(UNITS)
    .filter((n) => reqOf(n, state.route))
    .sort((a, b) => {
      const ra = reqOf(a, state.route), rb = reqOf(b, state.route);
      return (ra.renown - rb.renown) || (ra.support - rb.support) || a.localeCompare(b);
    });
}

/* ------------------------------------------------------------------ *
 * recruitment tab
 * ------------------------------------------------------------------ */
function renderSummary() {
  const targets = routeTargets();
  const done = targets.filter(isDone).length;
  const ready = targets.filter((n) => statusOf(n).key === 'ready').length;
  const gaps = targets.filter((n) => !isDone(n) && statusOf(n).key !== 'auto').length;
  const auto = targets.filter((n) => statusOf(n).key === 'auto').length;

  clear(document.getElementById('sum'), [
    ['Recruited', done, ' / ' + targets.length],
    ['Ready now', ready, ''],
    ['Still to get', gaps, ''],
    ['Auto-joins', auto, '']
  ].map(([label, value, suffix]) => el('div', { class: 'card' },
    el('div', { class: 'k', text: label }),
    el('div', { class: 'v' }, String(value), suffix ? el('small', { text: suffix }) : null))));

  const myClan = Object.entries(DOC.clans).find(([, members]) => members.includes(state.route));
  const retainers = myClan ? myClan[1].filter((m) => m !== state.route) : [];
  clear(document.getElementById('recruitNote'),
    myClan
      ? "Retainers of " + state.route + "'s own house (" + myClan[0] + ') join automatically: ' + retainers.join(', ') +
        '. Everyone else on this route has to be recruited with support and renown.'
      : '');
}

function supportSegment(n, required) {
  return el('div', { class: 'seg' }, [0, 1, 2, 3].map((level) => el('button', {
    class: (suppOf(n) === level ? 'on ' : '') + (level && level <= required ? 'met' : ''),
    dataset: { sup: n + '|' + level },
    text: level === 0 ? '–' : 'S' + level
  })));
}

function recruitRow(n) {
  const u = UNITS[n];
  const r = reqOf(n, state.route);
  const st = statusOf(n);
  const hasExtra = (r.extra || []).length > 0;

  function renownCell() {
    if (!r.renown) return el('span', { class: 'sub', text: 'none' });
    const met = r.renown <= state.renown;
    return el('span', {
      style: { color: met ? 'var(--good)' : 'var(--bad)' },
      text: 'R' + r.renown + (met ? ' ✓' : ' ✗')
    });
  }

  function extraCell() {
    if (!hasExtra) return el('span', { class: 'sub', text: '—' });
    return el('label', { class: 'ctl' },
      el('input', { type: 'checkbox', dataset: { extra: n }, checked: extraOk(n) }),
      r.extra.join(' · '));
  }

  return el('tr', { class: isDone(n) ? 'done' : null },
    el('td', null, el('input', {
      type: 'checkbox', dataset: { done: n }, checked: isDone(n),
      'aria-label': 'mark ' + n + ' recruited'
    })),
    el('td', null,
      el('span', { class: 'unit', text: n }),
      el('div', { class: 'sub', text: r.chapter || '' })),
    el('td', null, el('span', { class: tierClass(u.tier), text: u.tier })),
    el('td', null,
      el('span', { class: 'sub', text: r.support ? 'S' + r.support : 'none' }),
      supportSegment(n, r.support)),
    el('td', null, renownCell()),
    el('td', null, extraCell()),
    el('td', null, el('span', { class: 'pill ' + st.cls, text: st.label })));
}

function renderRecruit() {
  const q = state.q.toLowerCase();
  let list = routeTargets();
  if (q) list = list.filter((n) => n.toLowerCase().includes(q));
  if (state.hideDone) list = list.filter((n) => !isDone(n));
  if (state.onlyGaps) list = list.filter((n) => !isDone(n) && statusOf(n).key !== 'auto');
  clear(document.getElementById('rows'), frag(list.map(recruitRow)));
}

/* ------------------------------------------------------------------ *
 * builds tab
 * ------------------------------------------------------------------ */
function growthBars(growths, className) {
  const bonus = className && DOC.classes[className] ? DOC.classes[className].growths : null;
  return STATS.map((stat) => {
    const base = growths[stat] || 0;
    const add = bonus ? bonus[stat] || 0 : 0;
    const total = Math.max(0, base + add);
    const color = growthColor(add, 'var(--accent)');
    return el('div', {
      class: 'g',
      title: 'base ' + base + (bonus ? ' ' + (add >= 0 ? '+' : '') + add : '') + ' = ' + total + '%'
    },
      el('div', { class: 'lbl', text: stat }),
      el('div', { class: 'num', text: String(total) }),
      el('div', { class: 'track' },
        el('div', { class: 'fill', style: { width: Math.min(100, total * 1.4) + '%', background: color } })));
  });
}

function buildCard(n) {
  const u = UNITS[n];
  const path = u.progression || [];
  const finalClass = path.length ? path[path.length - 1] : '';
  const hasClassData = !!(finalClass && DOC.classes[finalClass]);
  const loved = (u.gifts || {}).loved || [];

  return el('div', { class: 'bcard' },
    el('h3', null,
      el('span', { class: tierClass(u.tier), text: u.tier }),
      n,
      el('span', { class: 'sub', style: { marginLeft: 'auto' }, text: 'Σ' + u.growth_total })),
    el('div', { class: 'sub', text: (u.proficiencies || []).join(' · ') || 'no listed proficiencies' }),
    u.skill ? el('div', { class: 'sk', text: u.skill }) : null,
    u.skill_desc ? el('div', { class: 'skd', text: u.skill_desc }) : null,
    el('div', { class: 'prog' },
      el('em', { text: 'path: ' }),
      path.length ? path.join(' → ') : 'fixed class'),
    el('div', { class: 'grow' }, frag(growthBars(u.growths, finalClass))),
    el('div', { class: 'sub', text: hasClassData
      ? 'bars include ' + finalClass + ' class bonuses'
      : 'bars show base growths' }),
    loved.length
      ? el('details', null,
          el('summary', { text: 'gift preferences' }),
          el('div', { class: 'gift' }, el('b', { text: 'loves: ' }), loved.join(', ')))
      : null);
}

function renderBuilds() {
  const q = state.bq.toLowerCase();
  let names = Object.keys(UNITS);
  if (q) names = names.filter((n) => n.toLowerCase().includes(q));
  if (state.onlyRecruited) names = names.filter(isDone);
  names.sort((a, b) =>
    tierRank(UNITS[a].tier) - tierRank(UNITS[b].tier) ||
    UNITS[b].growth_total - UNITS[a].growth_total ||
    a.localeCompare(b));
  clear(document.getElementById('bcards'), frag(names.map(buildCard)));
}

/* ------------------------------------------------------------------ *
 * classes tab
 * ------------------------------------------------------------------ */
const CLASS_ORDER = ['Base', 'Beginner', 'Specialty', 'Advanced', 'Master', 'Divine'];
const ROUTE_EXCLUSIVE = { Cai: ['Dragoon', 'Caladrius', 'Troubadour'] };

function classTable(tier) {
  const entries = Object.entries(DOC.classes).filter(([, c]) => c.tier === tier);
  const exclusive = ROUTE_EXCLUSIVE[state.route] || [];

  const head = el('thead', null,
    el('tr', null,
      el('th', { style: { width: '220px' }, text: 'Class' }),
      el('th', { text: 'Growth bonus · ' + STATS.join(' ') })));

  const rows = entries.map(([name, cls]) => {
    const bonus = STATS.map((stat) => {
      const value = cls.growths[stat] || 0;
      return el('span', {
        style: { color: growthColor(value, 'var(--faint)') },
        text: (value > 0 ? '+' : '') + value
      });
    });
    const spaced = bonus.flatMap((node, i) => (i < bonus.length - 1 ? [node, ' '] : [node]));
    const nameCell = el('td', { class: 'unit' }, name,
      exclusive.includes(name) ? el('span', { class: 'tag hot', text: state.route + ' route' }) : null);
    return el('tr', null, nameCell, el('td', { class: 'sub mono' }, frag(spaced)));
  });

  return el('table', null, head, el('tbody', null, frag(rows)));
}

function renderClasses() {
  const tiers = CLASS_ORDER.filter((t) => Object.values(DOC.classes).some((c) => c.tier === t));
  clear(document.getElementById('classtiers'), frag(tiers.map((tier) =>
    el('div', null,
      el('h3', { style: { fontSize: '14px', margin: '18px 0 6px' } },
        tier,
        el('span', { class: 'sub', text: ' · ' + (DOC.meta.class_gates[tier] || 'starting class') })),
      classTable(tier)))));
}

/* ------------------------------------------------------------------ *
 * gifts tab
 * ------------------------------------------------------------------ */
function giftRow(n) {
  const u = UNITS[n];
  const g = u.gifts || {};
  const r = reqOf(n, state.route);
  const need = [];
  if (r.support > suppOf(n)) need.push('S' + r.support);
  if (r.renown > state.renown) need.push('R' + r.renown);
  if ((r.extra || []).length && !extraOk(n)) need.push('extra');
  const liked = g.really_liked || [];

  return el('tr', null,
    el('td', null,
      el('span', { class: 'unit', text: n }),
      el('span', { class: tierClass(u.tier), text: u.tier })),
    el('td', null, need.length
      ? el('span', { class: 'pill p-need', text: need.join(' + ') })
      : el('span', { class: 'pill p-ready', text: 'ready' })),
    el('td', { class: 'gift' }, el('b', { text: (g.loved || []).join(', ') })),
    el('td', { class: 'gift', text: liked.slice(0, 8).join(', ') + (liked.length > 8 ? ' …' : '') }),
    el('td', { class: 'gift', text: (g.likes || []).concat(g.interests || []).join(' · ') }));
}

function renderGifts() {
  const list = routeTargets().filter((n) => !isDone(n) && statusOf(n).key !== 'auto');
  const body = document.getElementById('giftrows');
  clear(body, list.length
    ? frag(list.map(giftRow))
    : el('tr', null, el('td', { colspan: 5, class: 'sub', text: 'Nothing outstanding — everyone reachable on this route is recruited.' })));
}

/* ------------------------------------------------------------------ *
 * part II / III tab
 * ------------------------------------------------------------------ */
function renderLate() {
  clear(document.getElementById('laterows'), frag(DOC.late_recruits.map((r) => {
    const u = UNITS[r.name];
    const tier = u ? u.tier : '?';
    return el('tr', null,
      el('td', null,
        el('span', { class: 'unit', text: r.name }),
        el('span', { class: tierClass(tier), text: tier })),
      el('td', { text: r.availability }),
      el('td', { class: 'sub', text: r.condition }));
  })));
}

/* ------------------------------------------------------------------ *
 * wiring
 * ------------------------------------------------------------------ */
function renderAll() {
  document.querySelectorAll('nav button').forEach((b) => b.classList.toggle('on', b.dataset.tab === state.tab));
  document.querySelectorAll('section').forEach((s) => s.classList.toggle('on', s.id === state.tab));
  renderSummary();
  renderRecruit();
  renderBuilds();
  renderClasses();
  renderGifts();
  renderLate();
  clear(document.getElementById('foot'),
    'Recruitment requirements: game8, cross-checked against the community spreadsheet. ' +
    'Growth rates, class bonuses and the tier list: game8 (Creek is untiered in the source). ' +
    'Progress is stored in this browser only.');
}

const routeSelect = document.getElementById('route');
DOC.meta.routes.forEach((r) => routeSelect.add(new Option(r + "'s route", r)));
routeSelect.value = state.route;
routeSelect.addEventListener('change', (e) => {
  state.route = e.target.value;
  save();
  renderAll();
});

const renownInput = document.getElementById('renown');
renownInput.value = state.renown;
renownInput.addEventListener('input', (e) => {
  state.renown = Math.max(1, Math.min(15, Number(e.target.value) || 1));
  save();
  renderSummary();
  renderRecruit();
  renderGifts();
});

document.querySelectorAll('nav button').forEach((b) => b.addEventListener('click', () => {
  state.tab = b.dataset.tab;
  save();
  renderAll();
}));

const searchInput = document.getElementById('q');
searchInput.value = state.q;
searchInput.addEventListener('input', (e) => {
  state.q = e.target.value;
  save();
  renderRecruit();
});

const buildSearch = document.getElementById('bq');
buildSearch.value = state.bq;
buildSearch.addEventListener('input', (e) => {
  state.bq = e.target.value;
  save();
  renderBuilds();
});

['hideDone', 'onlyGaps', 'onlyRecruited'].forEach((id) => {
  const input = document.getElementById(id);
  input.checked = state[id];
  input.addEventListener('change', () => {
    state[id] = input.checked;
    save();
    renderRecruit();
    renderBuilds();
  });
});

document.getElementById('reset').addEventListener('click', () => {
  if (!confirm('Clear all tracked progress?')) return;
  state.recruited = {};
  state.support = {};
  state.extras = {};
  save();
  renderAll();
});

document.body.addEventListener('change', (e) => {
  const t = e.target;
  if (t.dataset && t.dataset.done) {
    state.recruited[t.dataset.done] = t.checked;
    save();
    renderAll();
  }
  if (t.dataset && t.dataset.extra) {
    state.extras[t.dataset.extra] = t.checked;
    save();
    renderAll();
  }
});

document.body.addEventListener('click', (e) => {
  const button = e.target.closest('button[data-sup]');
  if (!button) return;
  const [name, level] = button.dataset.sup.split('|');
  state.support[name] = Number(level);
  save();
  renderAll();
});

renderAll();
</script>
</body>
</html>
"""


def load_dataset() -> dict:
    """Read data/fwe.json, with a pointer to the fix if it is missing."""
    try:
        return json.loads(DATA.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(
            f"missing {DATA.relative_to(ROOT)} — run build/fetch.py then build/extract.py first"
        ) from None
    except json.JSONDecodeError as error:
        raise SystemExit(f"{DATA.relative_to(ROOT)} is not valid JSON: {error}") from None


def main() -> int:
    document = load_dataset()
    payload = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    if "</script" in payload:
        raise SystemExit("dataset contains a literal </script — refusing to inline it")
    OUT.write_text(TEMPLATE.replace("__DATA__", payload), encoding="utf-8")
    print(f"units {len(document['units'])} · classes {len(document['classes'])}")
    print(f"-> {OUT} ({OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
