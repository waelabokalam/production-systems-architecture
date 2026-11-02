"""Public explorer contracts; standard-library runner, optional native Node checks."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class ExplorerContracts(unittest.TestCase):
    def test_local_runtime_and_safe_resource_policy(self):
        source = (DOCS / "index.html").read_text()
        page = Page(source)
        for tag, attrs in page.tags:
            if tag in {"script", "img", "iframe", "link", "audio", "video"}:
                target = attrs.get("src", attrs.get("href", ""))
                self.assertNotRegex(target, r"^(https?:)?//")
                if target:
                    self.assertTrue((DOCS / target).is_file(), target)
            self.assertFalse(any(key.startswith("on") for key in attrs), tag)
        self.assertIn("connect-src 'self'", source)
        self.assertIn("object-src 'none'", source)
        self.assertIn("<noscript>", source)
        self.assertIn('class="skip"', source)
        self.assertIn('lang="en"', source)

    def test_controllers_have_no_html_execution_or_external_transport(self):
        js = "\n".join((DOCS / name).read_text() for name in ("explorer.js", "explorer-model.js"))
        self.assertNotRegex(js, r"\b(eval|Function|WebSocket|EventSource|sendBeacon)\s*\(")
        self.assertNotRegex(js, r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|localStorage|sessionStorage")
        self.assertNotRegex(js, r"https?://|import\s*\(|require\s*\(")
        self.assertIn('loadJSON("evidence/atg.json")', js)
        self.assertIn('loadJSON("evidence/explorer.json")', js)
        self.assertIn('credentials: "omit"', js)

    def test_atg_fixture_matches_published_names_and_scope(self):
        fixture = json.loads((DOCS / "evidence/atg.json").read_text())
        case = (ROOT / "case-studies/atg.md").read_text()
        self.assertEqual(len(fixture["stages"]), 10)
        self.assertEqual(len(fixture["roles"]), 6)
        self.assertEqual(fixture["interactive_roles"], ["owner", "manager", "employee", "client"])
        for stage in fixture["stages"]:
            self.assertIn(stage, case)
        for role in fixture["roles"]:
            self.assertIn(role["label"].replace(" / ", "/"), case.replace(" / ", "/"))
        self.assertEqual(fixture["baseline"]["rls_protected_tables"], 54)
        self.assertIn("representative", fixture["scope"])
        self.assertIn("not a universal", fixture["model_scope"])

    def test_recording_is_payload_free_and_metadata_only(self):
        data = json.loads((DOCS / "evidence/explorer.json").read_text())
        self.assertEqual(len(data["spans"]), 4)
        ids = {s["span_id"] for s in data["spans"]}
        self.assertEqual(len(ids), 4)
        self.assertEqual([s["span_id"] for s in data["spans"]], [format(i, "016x") for i in range(1, 5)])
        self.assertEqual([s["trace_id"] for s in data["spans"]], [format(1, "032x")] * 3 + [format(2, "032x")])
        for span in data["spans"]:
            self.assertGreater(span["duration_ns"], 0)
            self.assertGreaterEqual(span["start_offset_ns"], 0)
            self.assertIn(span["status"], {"OK", "ERROR"})
            self.assertFalse(span["events"])
            self.assertLessEqual(set(span["attributes"]), {"clinicalbridge.outcome", "clinicalbridge.document_count"})
            if span["parent_span_id"]:
                self.assertIn(span["parent_span_id"], ids)
        self.assertIn("Not the real clinical orchestrator", data["recording"]["scope"])
        self.assertIn("Not a production latency", data["recording"]["timing"])
        self.assertNotIn("synthetic exception content", json.dumps(data["spans"]))

    def test_tool_schemas_and_actual_transcript(self):
        data = json.loads((DOCS / "evidence/explorer.json").read_text())
        schemas = json.loads((ROOT / "examples/tqen-mcp-tools.schema.json").read_text())
        self.assertEqual(data["tqen"]["tools"], schemas)
        for tool in data["tqen"]["tools"]:
            self.assertFalse(tool["inputSchema"]["additionalProperties"])
            self.assertTrue(tool["annotations"]["readOnlyHint"])
            self.assertFalse({"tenant_id", "branch_id", "url", "sql", "role"} & tool["inputSchema"]["properties"].keys())
        transcript = (DOCS / "evidence/recorded-tests.txt").read_text()
        self.assertIn("26 passed", transcript)
        self.assertIn("6 passed", transcript)
        self.assertIn("proof_tests/test_tqen_mcp.py", transcript)

    def test_accessibility_mobile_and_privacy_guards(self):
        html = (DOCS / "index.html").read_text()
        css = (DOCS / "explorer.css").read_text()
        self.assertIn("prefers-color-scheme: dark", css)
        self.assertIn("prefers-reduced-motion: reduce", css)
        self.assertIn(":focus-visible", css)
        self.assertIn("max-width:767px", css)
        self.assertNotIn("—", html)
        for path in DOCS.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            content = path.read_text()
            self.assertNotRegex(content, r"/Users/|/private/tmp/|supabase\.co|railway\.app|pages\.dev|Bearer\s+[A-Za-z0-9]")
            self.assertNotRegex(content, re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I))

    @unittest.skipUnless(shutil.which("node"), "Native Node is optional; install it to run the UI-model checks")
    def test_native_node_models_and_ui_events(self):
        run = subprocess.run(["node", "--test", "docs/tests/explorer.test.cjs"], cwd=ROOT,
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
