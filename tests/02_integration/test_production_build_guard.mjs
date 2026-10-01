import assert from "node:assert/strict";
import test from "node:test";

import { assertMocksDisabledForBuild } from "../../scripts/productionBuildGuard.mjs";

test("development server permits local mock modes", () => {
  assert.doesNotThrow(() =>
    assertMocksDisabledForBuild("serve", { VITE_USE_MOCKS: "true" }, "dashboard"),
  );
});

test("production build refuses VITE_USE_MOCKS", () => {
  assert.throws(
    () => assertMocksDisabledForBuild("build", { VITE_USE_MOCKS: "true" }, "dashboard"),
    /disable VITE_USE_MOCKS/,
  );
});

test("production build refuses service worker mocks", () => {
  assert.throws(
    () => assertMocksDisabledForBuild("build", { VITE_ENABLE_MSW: "TRUE" }, "dashboard"),
    /disable VITE_ENABLE_MSW/,
  );
});

test("production build refuses simulation-only UI features and credentials", () => {
  assert.throws(
    () =>
      assertMocksDisabledForBuild(
        "build",
        {
          VITE_ENABLE_SIMULATION_SCENARIOS: "true",
          VITE_NOVATRUST_TRUSTED_PASSWORD: "local-demo-password",
        },
        "dashboard",
      ),
    /VITE_ENABLE_SIMULATION_SCENARIOS/,
  );
});

test("production build permits live-data configuration", () => {
  assert.doesNotThrow(() =>
    assertMocksDisabledForBuild(
      "build",
      { VITE_USE_MOCKS: "false", VITE_ENABLE_MSW: "false" },
      "dashboard",
    ),
  );
});
