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
