"""The integration snippets the Add Application wizard shows must be real, runnable code."""

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNIPPETS = ROOT / "dashboard" / "src" / "components" / "universal" / "snippets.js"
NODE = shutil.which("node")


def render(agent):
    script = (
        f"import {{ allSnippets }} from {json.dumps(SNIPPETS.as_uri())};"
        f"console.log(JSON.stringify(allSnippets({{origin:'http://localhost:5173',publishableKey:'pk_test_abc',agent:{json.dumps(agent)}}})));"
    )
    out = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@unittest.skipUnless(NODE, "node is required")
class SnippetTests(unittest.TestCase):
    AGENTS = [
        None,
        {"agent_id": "novatrust-agent", "sensitive_tool": "create_transfer", "sensitive_action": "token.transfer", "resource": "treasury"},
        {"agent_id": 'we"ird-agent', "sensitive_tool": "2 bad-name", "sensitive_action": "token.sell", "resource": "vault's"},
    ]

    def test_python_snippet_parses_and_uses_real_sdk_names(self):
        for agent in self.AGENTS:
            code = render(agent)["python"]
            ast.parse(code)
            self.assertIn("guard_tool(", code)
            self.assertIn("# pip install neurosoc\n", code)
            self.assertNotIn("./sdk/python", code)
            self.assertIn("NEUROSOC_SECRET_KEY", code)
            self.assertNotIn("sk_", code.replace("NEUROSOC_SECRET_KEY", ""))

    def test_python_snippet_runs_and_fails_closed_when_neurosoc_is_unreachable(self):
        code = render(self.AGENTS[1])["python"].replace("http://localhost:5173", "http://127.0.0.1:1")
        env = {**os.environ, "NEUROSOC_SECRET_KEY": "sk_test_0123456789", "PYTHONPATH": str(ROOT / "sdk" / "python")}
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Blocked:", result.stdout)  # the tool body did not run; the guard failed closed

    @unittest.skipUnless(os.environ.get("NEUROSOC_TEST_PYPI") == "1", "set NEUROSOC_TEST_PYPI=1 (needs network)")
    def test_snippet_runs_against_the_published_package(self):
        """The wizard shows `pip install neurosoc`; prove the snippet works with exactly that package."""
        code = render(self.AGENTS[1])["python"].replace("http://localhost:5173", "http://127.0.0.1:1")
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([sys.executable, "-m", "venv", tmp], check=True)
            python = str(Path(tmp) / "bin" / "python")
            subprocess.run([python, "-m", "pip", "install", "-q", "--no-cache-dir", "--upgrade", "neurosoc"], check=True)
            env = {"PATH": os.environ["PATH"], "NEUROSOC_SECRET_KEY": "sk_test_0123456789"}
            result = subprocess.run([python, "-c", code], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)  # a TypeError here would mean PyPI lacks a keyword
        self.assertIn("Blocked:", result.stdout)

    def test_javascript_snippets_are_syntactically_valid(self):
        snippets = render(self.AGENTS[1])
        with tempfile.TemporaryDirectory() as tmp:
            module = Path(tmp) / "module.mjs"
            module.write_text(snippets["module"])
            subprocess.run([NODE, "--check", str(module)], check=True, capture_output=True)
            inline = snippets["script"].split("<script>")[1].split("</script>")[0]
            plain = Path(tmp) / "inline.js"
            plain.write_text(inline)
            subprocess.run([NODE, "--check", str(plain)], check=True, capture_output=True)

    def test_script_tag_targets_served_bundle_with_consent_wait(self):
        tag = render(None)["script"]
        self.assertIn('src="http://localhost:5173/neurosoc.min.js"', tag)
        self.assertIn('data-key="pk_test_abc"', tag)
        self.assertIn('data-consent="wait"', tag)
        self.assertTrue((ROOT / "dashboard" / "public" / "neurosoc.min.js").exists())


if __name__ == "__main__":
    unittest.main()
