// Canonical copy, exercised by tests/test_production_build_guard.mjs. Mirrored (not
// symlinked, for Docker-build-context portability) at dashboard/scripts/productionBuildGuard.mjs
// and simulation_portal/scripts/productionBuildGuard.mjs -- each app's Docker build context is
// scoped to its own directory, so a `../scripts/...` import across that boundary can't resolve
// inside the image. Keep all three copies identical.
const MOCK_BUILD_FLAGS = ["VITE_USE_MOCKS", "VITE_ENABLE_MSW", "VITE_ENABLE_SIMULATION_SCENARIOS"];

export function assertMocksDisabledForBuild(command, env, serviceName) {
  if (command !== "build") {
    return;
  }

  const enabledFlags = MOCK_BUILD_FLAGS.filter(
    (flag) => String(env[flag] ?? "").trim().toLowerCase() === "true",
  );
  const simulationSecrets = Object.keys(env).filter(
    (key) => key.startsWith("VITE_NOVATRUST_") && String(env[key] ?? "").trim() !== "",
  );
  enabledFlags.push(...simulationSecrets);

  if (enabledFlags.length > 0) {
    throw new Error(
      `${serviceName} production build refused: disable ${enabledFlags.join(", ")}. Mock data is for local development only.`,
    );
  }
}
