(function () {
  "use strict";
  const model = globalThis.ArchitectureExplorer;
  const byId = id => document.getElementById(id);
  const json = (id, value) => { byId(id).textContent = JSON.stringify(value, null, 2); };
  const status = (id, state, text) => {
    const node = byId(id);
    node.dataset.status = state;
    node.textContent = text;
  };
  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  async function loadJSON(path) {
    const response = await fetch(path, {credentials: "omit", cache: "no-cache"});
    if (!response.ok) throw new Error("Bundled evidence is unavailable");
    return response.json();
  }
  function initialize(atg, evidence) {
    if (atg.stages.length !== 10 || atg.roles.length !== 6 || atg.interactive_roles.length !== 4) throw new Error("Invalid ATG fixture");
    let states = model.initialWorkflow(atg.stages.length);
    let selectedStage = 0;
    const role = () => document.querySelector('input[name="role"]:checked').value;
    const active = () => byId("actor-active").checked;
    const assigned = () => byId("assigned").checked;
    function updateProjection() {
      const value = model.projection(atg, role(), {active: active(), assigned: assigned(), ownShipment: byId("own-shipment").checked});
      status("projection-status", value.status, value.status === "allow" ? "ALLOW / reduced model" : "DENY / no fields");
      json("projection-output", value.data);
      byId("excluded-fields").textContent = value.excluded.length ? value.excluded.join(", ") : "None in this representative fixture.";
    }
    function renderStages() {
      const rows = atg.stages.map((name, index) => {
        const li = element("li");
        const button = element("button");
        button.type = "button";
        button.setAttribute("aria-pressed", String(index === selectedStage));
        button.setAttribute("aria-label", name + ": " + states[index]);
        button.append(element("span", name), element("span", states[index], "stage-state"));
        button.addEventListener("click", () => {
          selectedStage = index;
          // Keep the button node and keyboard focus stable while inspecting stages.
          Array.from(byId("stage-list").querySelectorAll("button")).forEach((node, i) => node.setAttribute("aria-pressed", String(i === index)));
          byId("stage-detail").textContent = atg.stages[index] + " / " + states[index];
        });
        li.append(button);
        return li;
      });
      byId("stage-list").replaceChildren(...rows);
      byId("stage-detail").textContent = atg.stages[selectedStage] + " / " + states[selectedStage];
    }
    byId("role-control").addEventListener("change", updateProjection);
    ["assigned", "own-shipment", "actor-active"].forEach(id => byId(id).addEventListener("change", updateProjection));
    document.querySelectorAll("[data-action]").forEach(button => button.addEventListener("click", () => {
      const result = model.transition(states, selectedStage, button.dataset.action, role(), assigned(), active());
      states = result.states;
      status("workflow-result", result.status, result.status.toUpperCase() + ": " + result.message);
      renderStages();
    }));
    byId("workflow-reset").addEventListener("click", () => {
      states = model.initialWorkflow(atg.stages.length);
      selectedStage = 0;
      renderStages();
      status("workflow-result", "empty", "Model reset. Try a review gate or a locked dependency.");
    });
    const roleDetails = atg.roles.flatMap(r => [element("dt", r.label), element("dd", r.boundary)]);
    byId("all-roles").replaceChildren(...roleDetails);

    const scenarios = {
      exact: ["invoice_review", {invoice_id: "invoice-a"}],
      injection: ["invoice_review", {invoice_id: "invoice-injection"}],
      foreign: ["invoice_review", {invoice_id: "invoice-b"}],
      branch: ["invoice_review", {invoice_id: "invoice-other-branch"}],
      missing: ["invoice_review", {invoice_id: "invoice-missing"}],
      scope: ["invoice_review", {invoice_id: "invoice-a", tenant_id: "tenant-b"}],
      write: ["delete_invoice", {invoice_id: "invoice-a"}],
      retrieval: ["retrieve_supplier_context", {query: "supplier", limit: 3}],
      empty: ["retrieve_supplier_context", {query: "no-matching-fixture", limit: 3}],
    };
    function runTool() {
      let args;
      try { args = JSON.parse(byId("tool-args").value); }
      catch (_) {
        status("mcp-status", "error", "ERROR / malformed JSON");
        json("mcp-output", {error: "Enter a valid JSON object. No request was run."});
        json("draft-output", {message: "No extraction draft returned: invalid JSON."});
        status("mcp-explanation", "error", "JSON parsing failed before the tool boundary.");
        return;
      }
      const result = model.invoke(evidence.tqen, byId("tool-name").value, args);
      const invoice = result.status === "allow" && byId("tool-name").value === "invoice_review"
        ? evidence.tqen.invoices.find(row => row.invoice_id === result.result.invoice_id) : null;
      json("draft-output", invoice ? {invoice_id: invoice.invoice_id, lines: invoice.lines} : {message: "No extraction draft returned for this request."});
      status("mcp-status", result.status, result.status.toUpperCase() + " / local preview");
      json("mcp-output", result.result);
      let explanation = "Preview only. Human confirmation remains required; no mutation exists.";
      if (result.status === "deny") explanation = "Denied before data is returned. No write or external request occurred.";
      if (result.status === "empty") explanation = "Valid scoped query; no matching synthetic documents.";
      if (result.status === "allow" && invoice?.invoice_id === "invoice-injection") explanation = "Text returned as untrusted data. Its requested scope change, URL fetch, and approval are DENIED by the absence of those capabilities.";
      status("mcp-explanation", result.status, explanation);
    }
    function chooseScenario() {
      const choice = scenarios[byId("mcp-scenario").value];
      byId("tool-name").value = choice[0];
      byId("tool-args").value = JSON.stringify(choice[1], null, 2);
      runTool();
    }
    byId("mcp-scenario").addEventListener("change", chooseScenario);
    byId("invoke-tool").addEventListener("click", runTool);
    json("schema-output", evidence.tqen.tools);

    let selectedSpan = evidence.spans.length ? evidence.spans[0].span_id : null;
    const depth = span => {
      let count = 0;
      let parent = span.parent_span_id;
      while (parent && count < evidence.spans.length) {
        count += 1;
        const ancestor = evidence.spans.find(s => s.span_id === parent);
        parent = ancestor ? ancestor.parent_span_id : null;
      }
      return count;
    };
    function selectSpan(span) {
      selectedSpan = span.span_id;
      json("trace-output", span);
      status("trace-status", span.status, span.status + " / recorded");
      byId("trace-list").querySelectorAll("button").forEach(node => node.setAttribute("aria-pressed", String(node.dataset.spanId === selectedSpan)));
    }
    function renderSpans() {
      const filter = byId("trace-filter").value;
      const visible = evidence.spans.filter(span => filter === "all" || span.status === filter);
      if (!visible.length) {
        byId("trace-list").replaceChildren(element("p", "No spans match this view. Choose another status to inspect the recording.", "empty"));
        json("trace-output", {spans: [], message: "No recorded spans selected."});
        status("trace-status", "empty", "EMPTY");
        return;
      }
      byId("trace-list").replaceChildren(...visible.map(span => {
        const wrapper = element("div", undefined, "trace-node");
        wrapper.dataset.depth = String(depth(span));
        const button = element("button", undefined, "span-button");
        button.type = "button";
        button.dataset.spanId = span.span_id;
        button.append(element("span", span.name), element("span", span.status + " / " + (span.duration_ns / 1e6).toFixed(3) + " ms local helper", "span-meta"));
        button.addEventListener("click", () => selectSpan(span));
        wrapper.append(button);
        return wrapper;
      }));
      selectSpan(visible.find(span => span.span_id === selectedSpan) || visible[0]);
    }
    byId("trace-filter").addEventListener("change", renderSpans);
    document.querySelectorAll(":disabled").forEach(node => { node.disabled = false; });
    updateProjection();
    renderStages();
    chooseScenario();
    renderSpans();
    byId("load-status").hidden = true;
  }
  Promise.all([loadJSON("evidence/atg.json"), loadJSON("evidence/explorer.json")])
    .then(([atg, evidence]) => initialize(atg, model.validateEvidence(evidence)))
    .catch(() => {
      // Do not echo arbitrary failed-response bodies or exception text into the UI.
      status("load-status", "error", "Evidence could not load. Serve the docs folder over HTTP, then reload. Source links and descriptions remain available.");
      document.querySelectorAll("button, input, select, textarea, fieldset").forEach(node => { node.disabled = true; });
    });
})();
