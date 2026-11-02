/* Pure reduced models. The browser is not an authorization boundary. */
(function (root) {
  "use strict";
  const clone = value => JSON.parse(JSON.stringify(value));
  // Integer decimal math mirrors the public Python Decimal proof without floats.
  // Only published fixture strings are consumed; not a general invoice parser.
  function decimal(value) {
    const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value);
    if (!match) throw new Error("Invalid fixture decimal");
    const fraction = match[3] || "";
    return {n: BigInt((match[1] || "") + match[2] + fraction), scale: fraction.length};
  }
  function arithmeticMatches(line) {
    const q = decimal(line.quantity), p = decimal(line.unit_price), t = decimal(line.stated_total);
    const scale = Math.max(q.scale + p.scale, t.scale);
    return q.n * p.n * (10n ** BigInt(scale - q.scale - p.scale)) === t.n * (10n ** BigInt(scale - t.scale));
  }
  function projection(data, role, options = {}) {
    const all = data.representative_record;
    const known = data.interactive_roles.includes(role);
    let fields = [];
    if (known && options.active !== false) {
      if (role === "owner") fields = Object.keys(all);
      if (role === "manager") fields = ["public_progress", "internal_task", "internal_drafts", "staff_document_requests"];
      if (role === "employee" && options.assigned === true) fields = ["public_progress", "internal_task"];
      if (role === "client" && options.ownShipment === true) fields = ["public_progress"];
    }
    return {status: fields.length ? "allow" : "deny", data: Object.fromEntries(fields.map(key => [key, clone(all[key])])),
      excluded: Object.keys(all).filter(key => !fields.includes(key))};
  }
  function initialWorkflow(count) {
    return Array.from({length: count}, (_, index) => index === 0 ? "in_progress" : "blocked");
  }
  function transition(states, index, action, role, assigned = false, active = true) {
    const unchanged = message => ({status: "deny", message, states: [...states]});
    if (!Number.isInteger(index) || index < 0 || index >= states.length) return unchanged("Unknown stage.");
    if (active !== true || !["owner", "manager", "employee"].includes(role) || (role === "employee" && assigned !== true)) {
      return unchanged("Role or assignment does not permit staff workflow mutation.");
    }
    const state = states[index];
    let next;
    if (action === "enter" && state === "blocked") {
      if (index > 0 && states[index - 1] !== "done") return unchanged("Dependency locked: complete the previous stage first.");
      next = "in_progress";
    } else if (action === "submit" && state === "in_progress") next = "pending_approval";
    else if (["approve", "reject"].includes(action) && state === "pending_approval" && ["owner", "manager"].includes(role)) {
      next = action === "approve" ? "done" : "in_progress";
    } else return unchanged("Transition denied: review, role, or current-state gate is not satisfied.");
    const updated = [...states];
    updated[index] = next;
    return {status: "allow", message: state + " → " + next + ". Earlier stage history is preserved.", states: updated};
  }
  function invoke(fixture, name, args) {
    const deny = message => ({status: "deny", result: {error: message}});
    if (!args || typeof args !== "object" || Array.isArray(args)) return deny("Invalid tool arguments");
    if (!fixture.scope.tenant_id || !fixture.scope.branch_id || !fixture.scope.capabilities.includes(name)) return deny("Resource not available");
    if (name === "invoice_review") {
      if (Object.keys(args).length !== 1 || typeof args.invoice_id !== "string" || !/^[a-z0-9-]{1,64}$/.test(args.invoice_id)) return deny("Invalid tool arguments");
      const invoice = fixture.invoices.find(row => row.tenant_id === fixture.scope.tenant_id && row.branch_id === fixture.scope.branch_id && row.invoice_id === args.invoice_id);
      if (!invoice) return deny("Resource not available");
      const line_items = invoice.lines.map(line => {
        const exact = line.description.trim().toLowerCase() === "tomatoes";
        return {source_text: line.description, trust: "untrusted", candidate_sku: exact ? "synthetic-tomato" : null,
          requires_review: !exact, arithmetic_matches: arithmeticMatches(line)};
      });
      return {status: "allow", result: {invoice_id: invoice.invoice_id, mode: "read_only_preview", requires_human_confirmation: true, line_items}};
    }
    if (name === "retrieve_supplier_context") {
      if (Object.keys(args).some(k => !["query", "limit"].includes(k)) || typeof args.query !== "string" || !args.query.length || args.query.length > 120 ||
        (args.limit !== undefined && (!Number.isInteger(args.limit) || args.limit < 1 || args.limit > 5))) return deny("Invalid tool arguments");
      const documents = fixture.documents.filter(d => d.tenant_id === fixture.scope.tenant_id && d.branch_id === fixture.scope.branch_id &&
        d.text.toLowerCase().includes(args.query.toLowerCase())).slice(0, args.limit === undefined ? 3 : args.limit)
        .map(d => ({document_id: d.document_id, source_text: d.text, trust: "untrusted"}));
      return {status: documents.length ? "allow" : "empty", result: {mode: "read_only_preview", documents}};
    }
    return deny("Resource not available");
  }
  function validateEvidence(data) {
    if (!data || data.format_version !== 1 || !Array.isArray(data.spans) || !data.tqen || !Array.isArray(data.tqen.tools)) throw new Error("Unsupported evidence format");
    const allowed = ["clinicalbridge.orchestrator", "clinicalbridge.agent_attempt", "clinicalbridge.ehr_retrieval", "clinicalbridge.anamnesis_retrieval"];
    const ids = new Set(data.spans.map(s => s.span_id));
    for (const span of data.spans) {
      if (!allowed.includes(span.name) || !["OK", "ERROR"].includes(span.status) || !Number.isFinite(span.duration_ns) || span.duration_ns < 0 ||
        (span.parent_span_id && !ids.has(span.parent_span_id)) || !Array.isArray(span.events) || span.events.length ||
        Object.keys(span.attributes).some(key => !["clinicalbridge.outcome", "clinicalbridge.document_count"].includes(key))) throw new Error("Invalid trace metadata");
    }
    return data;
  }
  const api = Object.freeze({projection, initialWorkflow, transition, invoke, validateEvidence});
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ArchitectureExplorer = api;
})(globalThis);
