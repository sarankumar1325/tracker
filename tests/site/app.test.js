// Runs site/logic.js and site/app.js under node with a stub DOM and the repository's data/ files, to check what the
// page's click handlers re-render. Run with `node --test tests/site/app.test.js`.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.join(__dirname, "..", "..");

function element() {
  const handlers = {};
  return {
    innerHTML: "", textContent: "", value: "", hidden: false, href: "", dataset: {}, style: {}, handlers,
    addEventListener(type, fn) { handlers[type] = fn; },
    querySelector() { return null; },
    scrollIntoView() {},
    append() {},
  };
}

// Loads the page at `hash` and resolves once main() has rendered; returns the stub elements by id.
async function loadPage(hash) {
  const elements = new Map();
  const location = { hash };
  const context = {
    console,
    URLSearchParams,
    setTimeout,
    location,
    history: { replaceState(_state, _title, url) { location.hash = url; } },
    navigator: {},
    document: {
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, element());
        return elements.get(id);
      },
      createElement: element,
    },
    fetch: async (url) => {
      const file = path.join(ROOT, url);
      if (!/^data\/[a-z]+\.json$/.test(url) || !fs.existsSync(file)) return { ok: false, json: async () => null };
      const json = JSON.parse(fs.readFileSync(file, "utf8"));
      return { ok: true, json: async () => json };
    },
  };
  vm.createContext(context);
  const code = ["logic.js", "app.js"].map((f) => fs.readFileSync(path.join(ROOT, "site", f), "utf8")).join("\n;\n");
  vm.runInContext(code, context, { filename: "site/logic.js + site/app.js" });
  for (let i = 0; i < 20 && !elements.get("lookup")?.innerHTML; i++) await new Promise((r) => setImmediate(r));
  return elements;
}

const click = (attr, value) => ({ target: { closest: (sel) => (sel === `button[${attr}]` ? { dataset: { [attr.replace("data-", "")]: value } } : null) } });

test("clicking a platform bar updates the lookup's \"Why?\" command (#56)", async () => {
  const coverage = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "coverage.json"), "utf8"));
  const python = coverage.targets[0].python;
  const platforms = coverage.targets.filter((t) => t.python === python).map((t) => t.platform);
  assert.ok(platforms.includes("musl-aarch64") && platforms.includes("win-arm64"), `${python} targets: ${platforms}`);
  const name = coverage.packages[0].name;

  const page = await loadPage(`#python=${python}&platform=musl-aarch64&package=${name}`);
  const lookup = page.get("lookup");
  assert.match(lookup.innerHTML, / -t musl-aarch64 --explain/);

  page.get("platforms").handlers.click(click("data-platform", "win-arm64"));
  assert.match(lookup.innerHTML, / -t win-arm64 --explain/);
  assert.doesNotMatch(lookup.innerHTML, /musl-aarch64 --explain/);
});
