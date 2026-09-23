/**
 * Headless smoke test for the generated planner.
 *
 * index.html is a single self-contained page, so there is no module to import.
 * This test extracts the inlined dataset and the app script, runs the app in a
 * vm context backed by a minimal DOM implementation, and then exercises the
 * real rendering and status logic. It catches runtime errors and layout
 * regressions that a syntax check would miss, without needing a browser.
 *
 * Usage: node build/test_planner.mjs
 */
import { readFileSync } from "node:fs";
import { createContext, runInContext } from "node:vm";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const html = readFileSync(join(ROOT, "index.html"), "utf8");

let failures = 0;
const check = (label, actual, expected) => {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) failures++;
  console.log(
    `${ok ? "  ok  " : " FAIL "} ${label}` +
      (ok ? "" : `\n         expected ${JSON.stringify(expected)}\n         actual   ${JSON.stringify(actual)}`)
  );
};
const ok = (label, cond) => check(label, !!cond, true);

/* ------------------------------------------------------------------ *
 * extract page payload
 * ------------------------------------------------------------------ */
const dataMatch = html.match(/<script id="fwe-data" type="application\/json">([\s\S]*?)<\/script>/);
if (!dataMatch) throw new Error("no inlined dataset found in index.html");
const DOC = JSON.parse(dataMatch[1]);

const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
if (!scripts.length) throw new Error("no app script found in index.html");
const appJs = scripts[scripts.length - 1][1];

/* ------------------------------------------------------------------ *
 * minimal DOM
 * ------------------------------------------------------------------ */
class TextNode {
  constructor(data) { this.data = String(data); this.children = []; }
  get textContent() { return this.data; }
  set textContent(v) { this.data = String(v); }
}

class El {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.attrs = {};
    this.dataset = {};
    this.style = {};
    this.listeners = {};
    this._classes = new Set();
    this._text = null;
    this.id = "";
    this.value = "";
    this.checked = false;
    this.type = "";
    this.title = "";
  }
  get className() { return [...this._classes].join(" "); }
  set className(v) { this._classes = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get classList() {
    const set = this._classes;
    return {
      add: (...n) => n.forEach((x) => set.add(x)),
      remove: (...n) => n.forEach((x) => set.delete(x)),
      contains: (n) => set.has(n),
      toggle: (n, force) => {
        const on = force === undefined ? !set.has(n) : !!force;
        if (on) set.add(n); else set.delete(n);
        return on;
      },
    };
  }
  get textContent() {
    if (this._text !== null) return this._text;
    return this.children.map((c) => c.textContent).join("");
  }
  set textContent(v) { this._text = String(v); this.children = []; }
  appendChild(child) { this.children.push(child); this._text = null; return child; }
  replaceChildren(...kids) { this.children = kids; this._text = null; }
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener(evt, fn) { (this.listeners[evt] ||= []).push(fn); }
  add(option) { this.children.push(option); }
}

/** Depth-first walk over an element tree. */
function walk(node, visit) {
  visit(node);
  for (const child of node.children || []) walk(child, visit);
}
function findAll(root, pred) {
  const hits = [];
  walk(root, (n) => { if (n.tagName && pred(n)) hits.push(n); });
  return hits;
}

const byId = new Map();
const makeEl = (id) => { const e = new El("div"); e.id = id; return e; };
const document = {
  getElementById(id) {
    if (id === "fwe-data") return { textContent: dataMatch[1] };
    if (!byId.has(id)) byId.set(id, makeEl(id));
    return byId.get(id);
  },
  createElement: (tag) => new El(tag),
  createTextNode: (t) => new TextNode(t),
  querySelectorAll: (sel) => {
    if (sel === "nav button") return document._nav;
    if (sel === "section") return document._sections;
    return [];
  },
  _nav: ["recruit", "builds", "classes", "gifts", "late"].map((tab) => {
    const b = new El("button"); b.dataset.tab = tab; return b;
  }),
  _sections: ["recruit", "builds", "classes", "gifts", "late"].map((id) => makeEl(id)),
  body: new El("body"),
};

const store = new Map();
const context = {
  document,
  console,
  JSON, Math, Object, Array, String, Number, Boolean, RegExp, Date, Error,
  Option: function Option(text, value) { this.text = text; this.value = value; },
  confirm: () => false,
  localStorage: {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, v),
  },
  setTimeout,
};
context.window = context;

/* ------------------------------------------------------------------ *
 * run the app
 * ------------------------------------------------------------------ */
// `let state` does not become a property of the vm global (only `function`
// declarations do), so append an explicit handle for the test to drive.
const harness = `${appJs}\n;globalThis.__fwe = { state, statusOf, routeTargets, UNITS };`;
runInContext(harness, createContext(context), { filename: "app.js" });
console.log("app script executed without throwing\n");

const { statusOf, routeTargets, UNITS } = context.__fwe;
const state = context.__fwe.state;
ok("statusOf is exposed", typeof statusOf === "function");
ok("routeTargets is exposed", typeof routeTargets === "function");

/* ------------------------------------------------------------------ *
 * dataset shape
 * ------------------------------------------------------------------ */
console.log("dataset:");
check("unit count", Object.keys(DOC.units).length, 62);
check("class count", Object.keys(DOC.classes).length, 59);
ok("every unit has 9 growth stats", Object.values(DOC.units).every((u) => Object.keys(u.growths).length === 9));
ok("every unit has a tier", Object.values(DOC.units).every((u) => u.tier && u.tier !== ""));
check("tier counts", DOC.meta.tier_labels.map((t) => DOC.tier_order[t].length), [5, 3, 23, 25, 5]);

/* ------------------------------------------------------------------ *
 * route scoping
 * ------------------------------------------------------------------ */
console.log("\nroute scoping (Cai):");
const cai = routeTargets();
ok("cai targets found", cai.length > 30);
ok("Cai is not a recruit target on his own route", !cai.includes("Cai"));
ok("Cai's own retainers auto-join", ["Tialla", "Peter", "Ultand"].every((n) => cai.includes(n)));
check("Tialla status is auto", statusOf("Tialla").key, "auto");
ok("Buccar is not recruitable on Cai", statusOf("Buccar").key === "na");
ok("Esmeralda IS recruitable on Cai", statusOf("Esmeralda").key !== "na");

/* ------------------------------------------------------------------ *
 * status transitions
 * ------------------------------------------------------------------ */
console.log("\nstatus transitions (Guzran on Cai = S1 / R2):");
check("base status", statusOf("Guzran").key, "need");
check("needs only support", statusOf("Guzran").label, "need S1");
state.support.Guzran = 1;
check("after S1 -> ready", statusOf("Guzran").key, "ready");
state.recruited.Guzran = true;
check("after recruit -> done", statusOf("Guzran").key, "done");
delete state.recruited.Guzran;

console.log("\nrenown gating:");
state.renown = 2;
check("Guzran ready at R2", statusOf("Guzran").key, "ready");
const gated = cai.find((n) => (DOC.units[n].recruit.Cai || {}).renown >= 10);
state.renown = 1;
ok(`${gated} is gated at R1`, statusOf(gated).key === "need");
check(`${gated} names the renown it needs`, statusOf(gated).label.includes("R10"), true);
state.renown = 11;

console.log("\nextra requirements:");
const withExtra = cai.find((n) => ((DOC.units[n].recruit.Cai || {}).extra || []).length);
const extraReq = DOC.units[withExtra].recruit.Cai;
state.support[withExtra] = extraReq.support;
state.extras[withExtra] = false;
check(`${withExtra} blocked on extra`, statusOf(withExtra).key, "need");
state.extras[withExtra] = true;
check(`${withExtra} ready once extra done`, statusOf(withExtra).key, "ready");
delete state.support[withExtra];
delete state.extras[withExtra];

/* ------------------------------------------------------------------ *
 * rendered output
 * ------------------------------------------------------------------ */
console.log("\nrendered output:");
const rows = byId.get("rows");
const bodyRows = rows.children.filter((c) => c.tagName === "tr");
check("recruitment table rows == route targets", bodyRows.length, cai.length);

const firstRowText = bodyRows[0].textContent;
ok("first row is the cheapest target", firstRowText.includes(cai[0]));
ok("first row shows its chapter", /Part I+ Ch \d/.test(firstRowText));
ok("rows render a status pill", findAll(rows, (n) => n.className.includes("pill")).length === cai.length);
ok("rows render a support segment", findAll(rows, (n) => n.className === "seg").length === cai.length);
ok("rows render tier badges", findAll(rows, (n) => n.className.startsWith("badge t-")).length === cai.length);
ok("support segments carry data-sup", findAll(rows, (n) => n.dataset.sup).length === cai.length * 4);

const summaryCards = byId.get("sum").children;
check("summary has 4 cards", summaryCards.length, 4);
check("first summary card label", summaryCards[0].children[0].textContent, "Recruited");
ok("summary counts targets", summaryCards[0].textContent.includes(String(cai.length)));

const buildCards = byId.get("bcards").children;
check("build cards for every unit", buildCards.length, 62);
const esmCard = buildCards.find((c) => c.textContent.startsWith("SEsmeralda"));
ok("Esmeralda has a build card", !!esmCard);
ok("build card names the personal skill", esmCard.textContent.includes("Brawn"));
ok("build card shows the class path", esmCard.textContent.includes("Gladiator → Armored Knight → Dreadnought"));
check("build card has 9 growth bars", findAll(esmCard, (n) => n.className === "g").length, 9);
ok("growth bars mention class bonuses", esmCard.textContent.includes("Dreadnought class bonuses"));

const classTables = findAll(byId.get("classtiers"), (n) => n.tagName === "table");
check("class tables (one per tier)", classTables.length, 6);

// Reconstruct which classes carry the route-exclusive tag, straight from the table.
const flaggedExclusives = findAll(byId.get("classtiers"), (n) => n.tagName === "tr")
  .filter((tr) => findAll(tr, (x) => x.className === "tag hot").length)
  .map((tr) => tr.children[0].textContent.replace(state.route + " route", "").trim());
check("flagged Cai-exclusive classes", flaggedExclusives.sort(), ["Caladrius", "Dragoon", "Troubadour"]);

const giftRows = byId.get("giftrows").children;
ok("gift rows rendered", giftRows.length > 0);
ok("gift rows show loved gifts", giftRows.some((r) => r.textContent.includes("loves") || r.children[2].textContent.length > 0));

check("part II/III rows", byId.get("laterows").children.length, 9);

/* ------------------------------------------------------------------ *
 * interaction: hide-recruited filter
 * ------------------------------------------------------------------ */
console.log("\ninteraction:");
state.recruited.Guzran = true;
state.hideDone = true;
context.renderRecruit();
check("hide-recruited drops one row", byId.get("rows").children.length, cai.length - 1);
state.hideDone = false;
state.q = "esz";
context.renderRecruit();
check("search filters to nothing for 'esz'", byId.get("rows").children.length, 0);
state.q = "Esme";
context.renderRecruit();
check("search finds Esmeralda", byId.get("rows").children.length, 1);
state.q = "";
delete state.recruited.Guzran;
context.renderRecruit();

/* ------------------------------------------------------------------ *
 * route switching
 * ------------------------------------------------------------------ */
console.log("\nroute switching:");
state.route = "Leda";
const leda = routeTargets();
ok("Leda has targets", leda.length > 30);
ok("Buccar auto-joins on Leda (her own retainer)", statusOf("Buccar").key === "auto");
ok("Buccar cannot be recruited on Cai", DOC.units.Buccar.recruit.Cai === null);
ok("Gaitz is Dietrich-only", ["Cai", "Leda", "Theodora"].every((r) => DOC.units.Gaitz.recruit[r] === null));
ok("Cai's retainer Ultand IS recruitable on Leda", statusOf("Ultand").key !== "na");
context.renderAll();
check("table re-renders for Leda", byId.get("rows").children.length, leda.length);
check("Leda has no route-exclusive class flags", findAll(byId.get("classtiers"), (n) => n.className === "tag hot").length, 0);
state.route = "Cai";
context.renderAll();

console.log("\nhouse rosters (from the sheet's Clans tab):");
const roster = (fragment) =>
  Object.entries(DOC.clans).find(([house]) => house.includes(fragment))?.[1];
check("Cai's house", roster("Cai's"), ["Cai", "Tialla", "Peter", "Ultand"]);
check("Leda's house", roster("Leda's"), ["Leda", "Buccar", "Sirocco", "Mu", "Olympia"]);
check("Theodora's house", roster("Theodora's"), ["Theodora", "Bonaventure", "Tobias", "Lilian", "Lysander"]);
check("Dietrich's house", roster("Dietrich's"), ["Dietrich", "Fabio", "Esmeralda", "Mikaela"]);
ok("every house has a roster", Object.values(DOC.clans).every((m) => m.length > 0));

/* ------------------------------------------------------------------ *
 * growth / class maths
 * ------------------------------------------------------------------ */
console.log("\nbuild data:");
const esm = UNITS.Esmeralda;
check("Esmeralda HP growth", esm.growths.HP, 55);
check("Esmeralda Def growth", esm.growths.Def, 45);
check("Esmeralda tier", esm.tier, "S");
check("Dreadnought class bonus Def", DOC.classes.Dreadnought.growths.Def, 30);
check("Esmeralda effective Def in Dreadnought", esm.growths.Def + DOC.classes.Dreadnought.growths.Def, 75);
check("personal skill parsed", esm.skill, "Brawn");
ok("proficiencies parsed", esm.proficiencies.includes("Axe") && esm.proficiencies.includes("Spear"));

console.log("\nclass gates:");
check("Advanced gate", DOC.meta.class_gates.Advanced, "Renown Lv 8 + Unit Lv 35 (Advanced License)");
check("Master gate", DOC.meta.class_gates.Master, "Unit Lv 45 (Master License)");
check("divine class count", Object.values(DOC.classes).filter((c) => c.tier === "Divine").length, 8);

/* ------------------------------------------------------------------ *
 * resilience: corrupt saved state must not break the page
 * ------------------------------------------------------------------ */
console.log("\nresilience:");
const corruptContext = {
  document,
  console: { warn() {}, log() {}, error() {} },
  JSON, Math, Object, Array, String, Number, Boolean, RegExp, Date, Error,
  Option: function Option() {},
  confirm: () => false,
  localStorage: { getItem: () => "{not valid json", setItem: () => {} },
  setTimeout,
};
runInContext(
  `${appJs}\n;globalThis.__fwe2 = { state };`,
  createContext(corruptContext),
  { filename: "app2.js" }
);
check("corrupt saved state falls back to default renown", corruptContext.__fwe2.state.renown, 11);
check("corrupt saved state starts with no progress", Object.keys(corruptContext.__fwe2.state.recruited).length, 0);

console.log(`\n${failures === 0 ? "ALL CHECKS PASSED" : failures + " CHECK(S) FAILED"}`);
process.exit(failures === 0 ? 0 : 1);
