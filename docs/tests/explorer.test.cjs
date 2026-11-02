"use strict";
// Native Node tests only. No website package installation or DOM dependency.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const model = require("../explorer-model.js");
const atg = require("../evidence/atg.json");
const evidence = require("../evidence/explorer.json");

test("four representative projections exclude forbidden fields and fail closed", () => {
  const options = {active:true, assigned:true, ownShipment:true};
  const client = model.projection(atg, "client", options);
  assert.deepEqual(Object.keys(client.data), ["public_progress"]);
  assert.ok(client.excluded.includes("internal_task"));
  assert.ok(client.excluded.includes("internal_drafts"));
  assert.ok(client.excluded.includes("staff_document_requests"));
  assert.ok(!Object.hasOwn(model.projection(atg, "manager", options).data, "account_administration"));
  assert.deepEqual(Object.keys(model.projection(atg, "employee", options).data), ["public_progress", "internal_task"]);
  for (const role of atg.interactive_roles) assert.equal(model.projection(atg, role, {...options, active:false}).status, "deny");
  assert.equal(model.projection(atg, "employee", {...options, assigned:false}).status, "deny");
  assert.equal(model.projection(atg, "client", {...options, ownShipment:false}).status, "deny");
  assert.equal(model.projection(atg, "superadmin", options).status, "deny");
});

test("workflow cannot skip dependencies, review, authorization or inactive actor gates", () => {
  const original = model.initialWorkflow(10);
  assert.equal(model.transition(original, 1, "enter", "owner").status, "deny");
  assert.equal(model.transition(original, 0, "approve", "owner").status, "deny");
  assert.equal(model.transition(original, 0, "complete", "owner").status, "deny");
  assert.equal(model.transition(original, 0, "submit", "client").status, "deny");
  assert.equal(model.transition(original, 0, "submit", "employee", false).status, "deny");
  assert.equal(model.transition(original, 0, "submit", "owner", false, false).status, "deny");
  const pending = model.transition(original, 0, "submit", "employee", true);
  assert.equal(pending.states[0], "pending_approval");
  assert.equal(model.transition(pending.states, 0, "approve", "employee", true).status, "deny");
  const rejected = model.transition(pending.states, 0, "reject", "manager");
  assert.equal(rejected.states[0], "in_progress");
  const done = model.transition(pending.states, 0, "approve", "owner");
  assert.equal(done.states[0], "done");
  assert.equal(model.transition(done.states, 1, "enter", "manager").states[1], "in_progress");
  assert.equal(original[0], "in_progress");
});

test("MCP replay matches actual recorded outcomes, denies scope and mutations", () => {
  const fixtures = evidence.tqen;
  const before = JSON.stringify(fixtures);
  for (const id of ["invoice-a", "invoice-injection"]) {
    assert.deepEqual(model.invoke(fixtures, "invoice_review", {invoice_id:id}).result, fixtures.recorded_outcomes[id]);
  }
  for (const id of ["invoice-b", "invoice-other-branch", "invoice-missing", "constructor"]) {
    assert.deepEqual(model.invoke(fixtures, "invoice_review", {invoice_id:id}), {status:"deny", result:{error:"Resource not available"}});
  }
  assert.equal(model.invoke(fixtures, "invoice_review", {invoice_id:"toString"}).status, "deny");
  for (const args of [{}, {invoice_id:1}, {invoice_id:"invoice-a", tenant_id:"tenant-b"}, {invoice_id:"invoice-a", confirm:true}, [], null]) {
    assert.equal(model.invoke(fixtures, "invoice_review", args).status, "deny");
  }
  assert.equal(model.invoke(fixtures, "delete_invoice", {invoice_id:"invoice-a"}).status, "deny");
  const injection = model.invoke(fixtures, "invoice_review", {invoice_id:"invoice-injection"}).result;
  assert.equal(injection.line_items[0].trust, "untrusted");
  assert.equal(injection.line_items[0].candidate_sku, null);
  assert.equal(injection.requires_human_confirmation, true);
  assert.equal(JSON.stringify(fixtures), before);
});

test("retrieval uses fixed scope, strict bounds and an explicit empty result", () => {
  assert.deepEqual(model.invoke(evidence.tqen, "retrieve_supplier_context", {query:"supplier"}).result, evidence.tqen.recorded_retrieval);
  assert.equal(model.invoke(evidence.tqen, "retrieve_supplier_context", {query:"absent-fixture"}).status, "empty");
  for (const args of [{query:"supplier", limit:true}, {query:"supplier", limit:"3"}, {query:"supplier", limit:6}, {query:"supplier", branch_id:"branch-2"}, {query:""}]) {
    assert.equal(model.invoke(evidence.tqen, "retrieve_supplier_context", args).status, "deny");
  }
  const noCapability = {...evidence.tqen, scope:{...evidence.tqen.scope, capabilities:[]}};
  assert.equal(model.invoke(noCapability, "invoice_review", {invoice_id:"invoice-a"}).status, "deny");
});

test("invoice arithmetic remains exact and non-exact identity requires review", () => {
  const fixture = structuredClone(evidence.tqen);
  fixture.invoices[0].lines = [{description:"Tomatoes", quantity:"3", unit_price:"0.10", stated_total:"0.30"}];
  assert.equal(model.invoke(fixture, "invoice_review", {invoice_id:"invoice-a"}).result.line_items[0].arithmetic_matches, true);
  fixture.invoices[0].lines[0].stated_total = "0.31";
  fixture.invoices[0].lines[0].description = "Tomato";
  const row = model.invoke(fixture, "invoice_review", {invoice_id:"invoice-a"}).result.line_items[0];
  assert.equal(row.arithmetic_matches, false);
  assert.equal(row.requires_review, true);
  assert.equal(row.candidate_sku, null);
});

test("recorded spans validate parent relationships and payload-free allowlists", () => {
  assert.equal(model.validateEvidence(evidence), evidence);
  assert.equal(evidence.spans.length, 4);
  const names = evidence.spans.map(s => s.name);
  assert.ok(names.includes("clinicalbridge.orchestrator"));
  assert.ok(evidence.spans.some(s => s.status === "ERROR"));
  const bad = structuredClone(evidence);
  bad.spans[0].attributes.prompt = "not allowed";
  assert.throws(() => model.validateEvidence(bad), /Invalid trace metadata/);
});

class Element {
  constructor(tag = "div") {
    this.tagName = tag; this.children = []; this.dataset = {}; this.listeners = {};
    this.attributes = {}; this.value = ""; this.checked = false; this.disabled = false;
    this.hidden = false; this.textContent = "";
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  fire(name) { this.listeners[name]?.({target:this}); }
  querySelectorAll(selector) {
    const all = this.children.flatMap(child => [child, ...child.querySelectorAll(selector)]);
    return selector === "button" ? all.filter(node => node.tagName === "button") : [];
  }
}
async function browser({fail = false} = {}) {
  const html = fs.readFileSync(path.join(__dirname, "../index.html"), "utf8");
  const ids = [...html.matchAll(/<([a-z]+)[^>]*\bid="([a-z-]+)"[^>]*>/g)];
  const elements = Object.fromEntries(ids.map(([, tag, id]) => [id, new Element(tag)]));
  const radios = atg.interactive_roles.map(value => Object.assign(new Element("input"), {value, checked:value === "owner"}));
  for (const id of ["assigned", "own-shipment", "actor-active"]) elements[id].checked = true;
  elements["mcp-scenario"].value = "exact";
  elements["trace-filter"].value = "all";
  const actions = ["enter", "submit", "approve", "reject"].map(action => {
    const node = new Element("button"); node.dataset.action = action; return node;
  });
  const all = [...Object.values(elements), ...radios, ...actions];
  all.filter(node => ["button", "input", "select", "textarea", "fieldset"].includes(node.tagName)).forEach(node => {node.disabled = true;});
  const document = {
    getElementById: id => elements[id],
    createElement: tag => new Element(tag),
    querySelector: () => radios.find(r => r.checked),
    querySelectorAll: selector => selector === "[data-action]" ? actions : selector === ":disabled" ? all.filter(n => n.disabled) : all.filter(n => ["button", "input", "select", "textarea", "fieldset"].includes(n.tagName)),
  };
  const requests = [];
  const fetch = async url => {
    requests.push(url);
    if (fail) return {ok:false};
    assert.ok(["evidence/atg.json", "evidence/explorer.json"].includes(url));
    return {ok:true, json:async () => structuredClone(url.endsWith("atg.json") ? atg : evidence)};
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../explorer.js"), "utf8"), {ArchitectureExplorer:model, document, fetch});
  await new Promise(resolve => setImmediate(resolve));
  return {elements, radios, actions, requests};
}

test("controller updates projection, denial state and review transitions", async () => {
  const {elements, radios, actions} = await browser();
  assert.equal(elements["load-status"].hidden, true);
  radios.forEach(r => {r.checked = r.value === "client";});
  elements["role-control"].fire("change");
  assert.deepEqual(Object.keys(JSON.parse(elements["projection-output"].textContent)), ["public_progress"]);
  actions.find(a => a.dataset.action === "submit").fire("click");
  assert.equal(elements["workflow-result"].dataset.status, "deny");
  radios.forEach(r => {r.checked = r.value === "owner";});
  actions.find(a => a.dataset.action === "submit").fire("click");
  assert.match(elements["stage-detail"].textContent, /pending_approval/);
  actions.find(a => a.dataset.action === "approve").fire("click");
  assert.match(elements["stage-detail"].textContent, /done/);
});

test("controller exercises injection, malformed JSON, denied scope and empty retrieval", async () => {
  const {elements} = await browser();
  elements["mcp-scenario"].value = "injection"; elements["mcp-scenario"].fire("change");
  assert.match(elements["mcp-output"].textContent, /untrusted/);
  assert.match(elements["mcp-explanation"].textContent, /DENIED/);
  elements["mcp-scenario"].value = "scope"; elements["mcp-scenario"].fire("change");
  assert.equal(elements["mcp-status"].dataset.status, "deny");
  elements["mcp-scenario"].value = "empty"; elements["mcp-scenario"].fire("change");
  assert.equal(elements["mcp-status"].dataset.status, "empty");
  elements["tool-args"].value = "{"; elements["invoke-tool"].fire("click");
  assert.equal(elements["mcp-status"].dataset.status, "error");
});

test("controller rejects JSON null, primitives and arrays without stale results or exceptions", async () => {
  const {elements} = await browser();
  for (const value of ["null", "true", "3", '"invoice-a"', "[]"]) {
    elements["mcp-scenario"].value = "exact";
    elements["mcp-scenario"].fire("change");
    assert.ok(JSON.parse(elements["draft-output"].textContent).lines.length);
    elements["tool-args"].value = value;
    assert.doesNotThrow(() => elements["invoke-tool"].fire("click"));
    assert.equal(elements["mcp-status"].dataset.status, "deny");
    assert.deepEqual(JSON.parse(elements["mcp-output"].textContent), {error:"Invalid tool arguments"});
    assert.match(elements["mcp-explanation"].textContent, /Denied before data is returned/);
    assert.equal(Object.hasOwn(JSON.parse(elements["draft-output"].textContent), "lines"), false);
  }
});

test("denied calls and malformed JSON clear previously allowed extraction rows", async () => {
  const {elements} = await browser();
  for (const scenario of ["scope", "write", "foreign", "branch", "missing"]) {
    elements["mcp-scenario"].value = "exact";
    elements["mcp-scenario"].fire("change");
    assert.equal(JSON.parse(elements["draft-output"].textContent).invoice_id, "invoice-a");
    elements["mcp-scenario"].value = scenario;
    elements["mcp-scenario"].fire("change");
    assert.equal(elements["mcp-status"].dataset.status, "deny");
    const draft = JSON.parse(elements["draft-output"].textContent);
    assert.deepEqual(Object.keys(draft), ["message"]);
    assert.doesNotMatch(elements["draft-output"].textContent, /Tomatoes|stated_total|unit_price|invoice-a/);
  }
  elements["mcp-scenario"].value = "exact";
  elements["mcp-scenario"].fire("change");
  elements["tool-args"].value = "{";
  elements["invoke-tool"].fire("click");
  assert.equal(elements["mcp-status"].dataset.status, "error");
  assert.deepEqual(Object.keys(JSON.parse(elements["draft-output"].textContent)), ["message"]);
});

test("controller selects recorded errors and supports an empty trace view", async () => {
  const {elements} = await browser();
  elements["trace-filter"].value = "ERROR"; elements["trace-filter"].fire("change");
  assert.equal(JSON.parse(elements["trace-output"].textContent).status, "ERROR");
  assert.equal(elements["trace-list"].querySelectorAll("button").length, 1);
  elements["trace-filter"].value = "none"; elements["trace-filter"].fire("change");
  assert.equal(elements["trace-status"].dataset.status, "empty");
  assert.deepEqual(JSON.parse(elements["trace-output"].textContent).spans, []);
});

test("evidence load failure leaves all controls disabled and explains recovery", async () => {
  const {elements, actions, requests} = await browser({fail:true});
  assert.equal(elements["load-status"].dataset.status, "error");
  assert.match(elements["load-status"].textContent, /HTTP/);
  assert.ok(actions.every(node => node.disabled));
  assert.equal(requests.length, 2);
});
