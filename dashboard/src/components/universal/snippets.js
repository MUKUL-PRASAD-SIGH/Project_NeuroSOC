// Integration snippets shown after an application is created. Pure functions with no imports so
// tests/test_dashboard_snippets.py can run them under Node and syntax-check every result.
// The Python SDK is on PyPI (`pip install neurosoc`). The JavaScript SDK is not on npm yet, so the script tag
// is served by this dashboard at /neurosoc.min.js and the module form uses a copy of the source.

const pyStr = (value) => JSON.stringify(String(value ?? ""));
const pyIdent = (value, fallback) => {
  const cleaned = String(value || "").replace(/[^A-Za-z0-9_]/g, "_").replace(/^(\d)/, "_$1");
  return cleaned || fallback;
};

export function scriptTagSnippet({ origin, publishableKey }) {
  return `<script src="${origin}/neurosoc.min.js"
        data-key="${publishableKey}"
        data-endpoint="${origin}"
        data-consent="wait"></script>
<script>
  // Nothing is collected until you call this, for example from your cookie banner's Accept button.
  document.getElementById("accept-cookies").addEventListener("click", function () {
    window.NeuroSOC.consent(true);
  });
</script>`;
}

export function moduleSnippet({ origin, publishableKey }) {
  return `// Copy dashboard/src/sdk (or sdk/js/src) into your project; the package is not on npm yet.
import { NeuroSOC } from "./sdk";

const soc = NeuroSOC.init({
  publishableKey: ${JSON.stringify(publishableKey)},
  endpoint: ${JSON.stringify(origin)},
  waitForConsent: true,
});

export function onConsentAccepted(userId) {
  soc.consent(true);
  soc.identify({ id: userId, type: "human" });
  soc.track({ action: "auth.login", resource: { id: "session", type: "account", sensitivity: "medium" } });
}`;
}

export function pythonSnippet({ origin, agent }) {
  const agentId = agent?.agent_id || "my-agent";
  const tool = agent?.sensitive_tool || "create_transfer";
  const action = agent?.sensitive_action || "token.transfer";
  const resource = agent?.resource || "treasury";
  return `# pip install neurosoc
import os
from neurosoc import NeuroSOC, ActionBlocked

# The secret key stays on your server. Never ship it to a browser or commit it.
soc = NeuroSOC(${pyStr(origin)}, os.environ["NEUROSOC_SECRET_KEY"])


@soc.guard_tool(
    agent_id=${pyStr(agentId)},
    action=${pyStr(action)},
    resource=${pyStr(resource)},
    resource_type="account",
    sensitivity="high",
    block_only_when_enforced=True,  # Monitor mode records; Protect mode blocks
)
def ${pyIdent(tool, "create_transfer")}(to: str, amount: float, instruction_source: str = "owner"):
    # Your real action goes here. It only runs if NeuroSOC allows it.
    return {"sent": amount, "to": to}


try:
    print(${pyIdent(tool, "create_transfer")}(to="Alice", amount=50.0))
except ActionBlocked as blocked:
    print("Blocked:", blocked.verdict.reasons)
`;
}

export function allSnippets(input) {
  return {
    script: scriptTagSnippet(input),
    module: moduleSnippet(input),
    python: pythonSnippet(input),
  };
}
