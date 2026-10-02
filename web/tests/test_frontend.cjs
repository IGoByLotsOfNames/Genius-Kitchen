"use strict";

// Run the shipped browser script with controlled I/O, not a copy of its logic.
// These small DOM doubles exercise async ownership; they do not test rendering.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function snapshot(revision) {
  return {
    revision,
    csrf_token: "local-test-token",
    today: "2026-10-02",
    items: [],
    recipes: [],
    demo_mode: false,
  };
}

function browser() {
  const elements = new Map();
  const requests = [];
  const renders = [];
  const toasts = [];

  function element(id) {
    if (!elements.has(id)) {
      const listeners = new Map();
      const classes = new Set();
      elements.set(id, {
        value: "",
        textContent: "",
        hidden: true,
        disabled: false,
        open: false,
        dataset: {},
        options: [{ value: "Other" }, { value: "Dairy" }],
        closeCount: 0,
        classList: {
          add: name => classes.add(name),
          remove: name => classes.delete(name),
          toggle: (name, enabled) => enabled ? classes.add(name) : classes.delete(name),
        },
        addEventListener(type, listener) {
          assert.equal(listeners.has(type), false, `Unexpected extra ${id}:${type} listener`);
          listeners.set(type, listener);
        },
        emit(type, event = { preventDefault() {} }) {
          assert.ok(listeners.has(type), `Missing ${id}:${type} listener`);
          return listeners.get(type)(event);
        },
        reset() {
          for (const name of ["name", "quantity", "unit", "category", "expiry"]) {
            element(`ingredient-${name}`).value = "";
          }
        },
        showModal() { this.open = true; },
        close() { this.open = false; this.closeCount++; },
        focus() {},
        add(option) { this.options.push(option); },
      });
    }
    return elements.get(id);
  }

  const context = vm.createContext({
    document: {
      querySelectorAll: () => [],
      getElementById: element,
      addEventListener() {},
      hidden: false,
    },
    window: { addEventListener() {}, scrollTo() {} },
    Option: function Option(text, value) { this.text = text; this.value = value; },
    // Leave the automatic initial fetch pending. It owns no timer or socket.
    fetch: () => new Promise(() => {}),
    setInterval: () => 1,
    setTimeout: () => 1,
    clearTimeout() {},
    __observeRender: value => renders.push(value.revision),
    __observeToast: (message, bad = false) => toasts.push({ message, bad }),
    __request: (url, options) => {
      const pending = deferred();
      requests.push({ url, options, ...pending });
      return pending.promise;
    },
  });
  const run = code => vm.runInContext(code, context);
  vm.runInContext(source, context, { filename: "static/app.js" });
  run(`
    request = (...args) => __request(...args);
    render = () => __observeRender(state);
    toast = (...args) => __observeToast(...args);
  `);
  context.__initial = snapshot("initial");
  run("state = __initial;");

  return {
    element, requests, renders, toasts, run,
    get state() { return run("state"); },
    load: () => run("load()"),
    open(item = null) {
      context.__item = item;
      run("openIngredient(__item)");
    },
    submit: () => element("ingredient-form").emit("submit"),
  };
}

function milk() {
  return {
    id: "3", name: "Milk", quantity: 1, unit: "litre",
    category: "Dairy", expires_on: "2026-10-04",
  };
}

test("the latest load wins when responses arrive in reverse order", async () => {
  const app = browser();
  const first = app.load();
  const second = app.load();
  assert.equal(app.requests.length, 2);
  assert.equal(app.requests[0].url, "/api/state");

  app.requests[1].resolve(snapshot("newer"));
  await second;
  app.requests[0].resolve(snapshot("older"));
  await first;

  assert.equal(app.state.revision, "newer");
  assert.deepEqual(app.renders, ["newer"]);
  assert.equal(app.element("connection-error").hidden, true);
});

test("an obsolete load failure cannot replace a newer successful connection", async () => {
  const app = browser();
  const first = app.load();
  const second = app.load();
  app.requests[1].resolve(snapshot("newer"));
  await second;
  app.requests[0].reject(new Error("old connection failed"));
  await first;

  assert.equal(app.state.revision, "newer");
  assert.equal(app.element("connection-label").textContent, "Saved on this computer");
  assert.equal(app.element("connection-error").hidden, true);
  assert.deepEqual(app.toasts, []);
});

test("a load started before a mutation cannot roll back the saved state", async () => {
  const app = browser();
  const refresh = app.load();
  const save = app.run('mutate("/api/items", "POST", {name: "Rice"})');
  assert.equal(app.requests[1].options.headers["If-Match"], "initial");
  app.requests[1].resolve(snapshot("saved"));
  await save;
  app.requests[0].resolve(snapshot("before-save"));
  await refresh;

  assert.equal(app.state.revision, "saved");
  assert.deepEqual(app.renders, ["saved"]);
  assert.equal(app.run("busy"), false);
});

test("a pending mutation also invalidates a refresh that finishes before the save", async () => {
  const app = browser();
  const refresh = app.load();
  const save = app.run('mutate("/api/items", "POST", {name: "Rice"})');
  app.requests[0].resolve(snapshot("stale"));
  await refresh;
  assert.equal(app.state.revision, "initial");
  assert.deepEqual(app.renders, []);

  app.requests[1].resolve(snapshot("saved"));
  await save;
  assert.equal(app.state.revision, "saved");
  assert.deepEqual(app.renders, ["saved"]);
});

test("a conflict refresh keeps write ownership until the latest pantry is loaded", async () => {
  const app = browser();
  const saving = app.run('mutate("/api/items/3", "PATCH", {name: "Milk"})');
  const rejected = assert.rejects(saving, /The pantry changed\. Review the latest ingredients/);
  const conflict = new Error("stale revision");
  conflict.status = 409;
  app.requests[0].reject(conflict);
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(app.requests[1].url, "/api/state");
  assert.equal(app.run("busy"), true);
  await assert.rejects(
    app.run('mutate("/api/items", "POST", {name: "Rice"})'),
    /Please wait for the current change to finish/,
  );
  await app.load();
  assert.equal(app.requests.length, 2, "Neither another write nor a refresh may overlap conflict recovery");

  app.requests[1].resolve(snapshot("conflict-refreshed"));
  await rejected;
  assert.equal(app.state.revision, "conflict-refreshed");
  assert.deepEqual(app.renders, ["conflict-refreshed"]);
  assert.equal(app.run("busy"), false);
});

test("late refresh success and failure cannot replace the closed-app notice", async t => {
  for (const outcome of ["success", "failure"]) {
    await t.test(outcome, async () => {
      const app = browser();
      const refresh = app.load();
      const closing = app.element("stop-button").emit("click");
      assert.equal(app.element("confirm-dialog").open, true);
      app.element("confirm-ok").emit("click");
      // Let the real confirmation promise resume the real shutdown handler.
      await new Promise(resolve => setImmediate(resolve));
      assert.equal(app.requests[1].url, "/api/shutdown");
      app.requests[1].resolve({ shutdown: true });
      await closing;
      const closedMessage = app.element("connection-error").textContent;
      const closedToasts = [...app.toasts];

      if (outcome === "success") app.requests[0].resolve(snapshot("late"));
      else app.requests[0].reject(new Error("server stopped"));
      await refresh;

      assert.equal(app.run("stopped"), true);
      assert.equal(app.state.revision, "initial");
      assert.equal(app.element("connection-label").textContent, "App closed · pantry saved");
      assert.equal(app.element("connection-error").textContent, closedMessage);
      assert.equal(app.element("connection-error").hidden, false);
      assert.deepEqual(app.toasts, closedToasts);
      assert.deepEqual(app.renders, []);
    });
  }
});

test("late edit success preserves a newly opened add form and labels the saved operation correctly", async () => {
  const app = browser();
  app.open(milk());
  app.element("ingredient-name").value = "Fresh milk";
  const saving = app.submit();
  assert.equal(app.element("save-ingredient").disabled, true);
  assert.equal(app.requests[0].url, "/api/items/3");
  assert.equal(app.requests[0].options.method, "PATCH");
  assert.equal(app.requests[0].options.headers["If-Match"], "initial");

  app.element("ingredient-dialog").close();
  app.open();
  app.element("ingredient-name").value = "Unsaved pears";
  assert.equal(app.element("save-ingredient").disabled, false);
  app.requests[0].resolve(snapshot("milk-saved"));
  await saving;

  assert.equal(app.element("ingredient-dialog").open, true);
  assert.equal(app.element("ingredient-dialog").closeCount, 1);
  assert.equal(app.element("ingredient-dialog-title").textContent, "Add an ingredient");
  assert.equal(app.element("ingredient-name").value, "Unsaved pears");
  assert.equal(app.element("save-ingredient").disabled, false);
  assert.equal(app.element("form-error").hidden, true);
  assert.deepEqual(app.toasts, [{ message: "Fresh milk updated.", bad: false }]);
});

test("late save failure toasts without replacing a different form's validation error", async () => {
  const app = browser();
  app.open();
  app.element("ingredient-name").value = "Rice";
  const saving = app.submit();
  app.element("ingredient-dialog").close();
  app.open(milk());
  app.element("ingredient-name").value = "Unsaved milk draft";
  app.element("ingredient-quantity").value = "0";
  await app.submit();
  const currentError = app.element("form-error").textContent;
  assert.equal(currentError, "Enter a quantity greater than zero.");
  assert.equal(app.requests.length, 1);

  app.requests[0].reject(new Error("disk is full"));
  await saving;

  assert.equal(app.element("ingredient-dialog").open, true);
  assert.equal(app.element("ingredient-name").value, "Unsaved milk draft");
  assert.equal(app.element("form-error").textContent, currentError);
  assert.equal(app.element("form-error").hidden, false);
  assert.equal(app.element("save-ingredient").disabled, false);
  assert.deepEqual(app.toasts, [{ message: "disk is full", bad: true }]);
});

test("the active form still saves its snapshot, closes, and enables Save", async () => {
  const app = browser();
  app.open();
  app.element("ingredient-name").value = "  Brown rice  ";
  app.element("ingredient-quantity").value = "2.5";
  app.element("ingredient-unit").value = "  kg  ";
  const saving = app.submit();
  assert.equal(app.element("save-ingredient").disabled, true);
  assert.equal(app.requests[0].url, "/api/items");
  assert.equal(app.requests[0].options.method, "POST");
  assert.equal(app.requests[0].options.headers["X-CSRF-Token"], "local-test-token");
  assert.deepEqual(JSON.parse(app.requests[0].options.body), {
    name: "Brown rice", quantity: 2.5, unit: "kg", category: "Other", expires_on: "2026-10-02",
  });
  app.requests[0].resolve(snapshot("rice-saved"));
  await saving;

  assert.equal(app.element("ingredient-dialog").open, false);
  assert.equal(app.element("save-ingredient").disabled, false);
  assert.equal(app.state.revision, "rice-saved");
  assert.deepEqual(app.toasts, [{ message: "Brown rice added to your pantry.", bad: false }]);
});

test("the active form still displays save failure and remains available for correction", async () => {
  const app = browser();
  app.open(milk());
  const saving = app.submit();
  app.requests[0].reject(new Error("Cannot write the inventory file."));
  await saving;

  assert.equal(app.element("ingredient-dialog").open, true);
  assert.equal(app.element("ingredient-name").value, "Milk");
  assert.equal(app.element("form-error").hidden, false);
  assert.equal(app.element("form-error").textContent, "Cannot write the inventory file.");
  assert.equal(app.element("save-ingredient").disabled, false);
  assert.equal(app.state.revision, "initial");
  assert.deepEqual(app.toasts, []);
});
