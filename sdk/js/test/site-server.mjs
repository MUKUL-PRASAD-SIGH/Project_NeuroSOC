// The dummy website ("Orbit") used by the browser tests: plain pages, a same-origin form backend,
// a "partner" server that receives cross-origin forms, and the built SDK at /neurosoc.min.js.
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const site = join(here, "browser", "site");
const bundle = process.env.NEUROSOC_BUNDLE || join(here, "..", "dist", "neurosoc.min.js");
const types = { ".html": "text/html; charset=utf-8", ".css": "text/css" };

export function startSite({ port = 8710, partnerPort = 8711, apiUrl, key = "pk_test_dummy" }) {
  const received = { signups: [], partner: [], logins: [] };
  const form = (req) => new Promise((resolve) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      const raw = Buffer.concat(chunks).toString("utf8");
      if ((req.headers["content-type"] || "").includes("multipart/form-data")) {
        const fields = {};
        for (const m of raw.matchAll(/name="([^"]+)"\r\n\r\n([\s\S]*?)\r\n--/g)) fields[m[1]] = m[2];
        return resolve(fields);
      }
      resolve(Object.fromEntries(new URLSearchParams(raw)));
    });
  });
  const main = createServer(async (req, res) => {
    const url = new URL(req.url, "http://x");
    if (req.method === "POST" && url.pathname.startsWith("/api/")) {
      const fields = await form(req);
      (url.pathname === "/api/signup" ? received.signups : received.logins).push(fields);
      res.writeHead(200, { "Content-Type": "application/json" });
      return res.end(JSON.stringify({ ok: true, session: fields.neurosoc_session ?? null }));
    }
    if (url.pathname === "/favicon.ico") { res.writeHead(204); return res.end(); }
    if (url.pathname === "/neurosoc.min.js") {
      res.writeHead(200, { "Content-Type": "text/javascript", "Cache-Control": "no-store" });
      return res.end(readFileSync(bundle));
    }
    const name = url.pathname === "/" ? "index.html" : url.pathname.startsWith("/app") ? "app.html"
      : url.pathname === "/style.css" ? "style.css" : url.pathname.replace(/^\//, "") + ".html";
    const file = join(site, name);
    if (name.includes("..") || !existsSync(file)) { res.writeHead(404); return res.end("not found"); }
    const q = url.searchParams;
    const attrs = [q.has("wait") && 'data-consent="wait"', q.has("debug") && 'data-debug="true"',
      q.get("nocapture") === "1" && 'data-auto-capture="false"', q.get("notag") === "1" && 'data-tag-forms="false"',
      q.get("nobehavior") === "1" && 'data-capture-behavior="false"'].filter(Boolean).join(" ");
    const tag = q.has("nosdk") ? "" : q.has("nokey")
      ? '<script src="/neurosoc.min.js" async></script>'
      : `<script src="/neurosoc.min.js" data-key="${q.get("key") || key}" data-endpoint="${q.get("endpoint") || apiUrl}" ${attrs} async></script>`;
    const body = readFileSync(file, "utf8").replace("{{SDK_TAG}}", tag).replace("{{EXTERNAL}}", `http://127.0.0.1:${partnerPort}`);
    const headers = { "Content-Type": types[name.slice(name.lastIndexOf("."))] ?? "text/html", "Cache-Control": "no-store" };
    // ?csp=1: the SDK must work under a strict policy: scripts from this host only, calls to the API host only.
    if (q.get("csp") === "1") headers["Content-Security-Policy"] = `default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src ${q.get("endpoint") || apiUrl}; form-action 'self'`;
    res.writeHead(200, headers);
    res.end(body);
  });
  const partner = createServer(async (req, res) => {
    received.partner.push({ url: req.url, fields: await form(req) });
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end("<p>partner received</p>");
  });
  return new Promise((resolve) => main.listen(port, "127.0.0.1", () => partner.listen(partnerPort, "127.0.0.1", () => resolve({
    url: `http://127.0.0.1:${port}`, received,
    close: () => Promise.all([main, partner].map((s) => new Promise((r) => { s.closeAllConnections?.(); s.close(r); }))),
  }))));
}
