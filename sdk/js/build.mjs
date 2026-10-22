import { build } from "esbuild";
import { gzipSync } from "node:zlib";
import { copyFileSync, readFileSync } from "node:fs";

const { version } = JSON.parse(readFileSync("package.json", "utf8"));
const define = { __SDK_VERSION__: JSON.stringify(version) };

// npm / bundlers: tree-shakeable ES module, no side effects on import.
await build({ entryPoints: ["src/index.ts"], outfile: "dist/index.mjs", bundle: true, format: "esm",
  target: "es2020", sourcemap: true, define });

// require() consumers (older bundlers, Node scripts).
await build({ entryPoints: ["src/index.ts"], outfile: "dist/index.cjs", bundle: true, format: "cjs",
  target: "es2020", sourcemap: true, define });

// <script> tag / CDN: self-starting, minified, exposes window.NeuroSOC.
await build({ entryPoints: ["src/auto.ts"], outfile: "dist/neurosoc.min.js", bundle: true, format: "iife",
  target: "es2020", minify: true, sourcemap: true, legalComments: "none", define });

const size = gzipSync(readFileSync("dist/neurosoc.min.js")).length;
console.log(`dist/neurosoc.min.js: ${(size / 1024).toFixed(1)} KB gzipped`);
if (size > 15 * 1024) {
  console.error("Script bundle exceeds the 15 KB gzipped budget.");
  process.exit(1);
}

// The Lens extension ships the same bundle.
copyFileSync("dist/neurosoc.min.js", "../extension/neurosoc.min.js");
