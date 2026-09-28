import { chromium } from "playwright";
import { copyFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(scriptDirectory, "../..");
const dashboardUrl = (process.env.NEUROSOC_DASHBOARD_URL || "http://127.0.0.1:3000").replace(/\/$/, "");
const portalUrl = (process.env.NEUROSOC_PORTAL_URL || "http://127.0.0.1:3001").replace(/\/$/, "");
const apiUrl = (process.env.NEUROSOC_API_URL || "http://127.0.0.1:8002").replace(/\/$/, "");
const ingestionUrl = (process.env.NEUROSOC_INGESTION_URL || "http://127.0.0.1:8080").replace(/\/$/, "");
const browserChannel = process.env.NEUROSOC_BROWSER_CHANNEL || "msedge";
const runId = new Date().toISOString().replace(/[:.]/g, "-");
const outputDirectory = path.resolve(repositoryRoot, "artifacts", "demo", `neurosoc-walkthrough-${runId}`);

await mkdir(outputDirectory, { recursive: true });

async function readJson(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.text();
  if (!response.ok) {
    throw new Error(`${options.method || "GET"} ${url} returned ${response.status}: ${body.slice(0, 300)}`);
  }
  try {
    return JSON.parse(body);
  } catch {
    throw new Error(`${url} did not return JSON.`);
  }
}

async function waitForProcessedMessages(previousCount, minimumDelta = 2, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  let health;
  while (Date.now() < deadline) {
    health = await readJson(`${apiUrl}/health`);
    if (Number(health.processed_messages) >= previousCount + minimumDelta) {
      return health;
    }
    await new Promise((resolve) => setTimeout(resolve, 750));
  }
  throw new Error(
    `Kafka-to-inference processing did not advance by ${minimumDelta}. ` +
      `Started at ${previousCount}, ended at ${health?.processed_messages ?? "unknown"}.`,
  );
}

async function waitForPortalAlert(previousIds, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const alerts = await readJson(`${apiUrl}/api/v1/alerts`);
    const alert = alerts.find(
      (item) => !previousIds.has(item.id) && item.verdict === "HACKER" && item.userId === "alice",
    );
    if (alert) return alert;
    await new Promise((resolve) => setTimeout(resolve, 750));
  }
  throw new Error("The NovaTrust simulated transfer did not produce a new HACKER alert for demo user alice.");
}

const [initialHealth, modelManifest, ingestionHealth, initialAlerts] = await Promise.all([
  readJson(`${apiUrl}/health`),
  readJson(`${apiUrl}/api/v1/model/version`),
  readJson(`${ingestionUrl}/health`),
  readJson(`${apiUrl}/api/v1/alerts`),
]);

if (initialHealth.status !== "ok" || !initialHealth.kafka_consumer_connected || !initialHealth.kafka_producer_connected) {
  throw new Error("Inference API or Kafka is not healthy. Start the local Kafka and inference services first.");
}
if (!initialHealth.database_enabled) {
  throw new Error("PostgreSQL persistence is disabled. Configure the local demo DATABASE_URL before recording.");
}
if (!modelManifest.version || !modelManifest.activeModels?.length) {
  throw new Error("The API did not report an active model version and ensemble.");
}
if (ingestionHealth.service !== "ingestion" || ingestionHealth.mode !== "bank_portal") {
  throw new Error("The local ingestion API is not in bank_portal mode.");
}

const browser = await chromium.launch({ channel: browserChannel, headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 960 },
  deviceScaleFactor: 1,
  recordVideo: {
    dir: outputDirectory,
    size: { width: 1440, height: 960 },
  },
});
const page = await context.newPage();
page.setDefaultTimeout(30000);
let recordingStartedAt;

async function holdUntil(secondsFromStart) {
  const remaining = recordingStartedAt + secondsFromStart * 1000 - Date.now();
  if (remaining > 0) await page.waitForTimeout(remaining);
}

const pageErrors = [];
page.on("pageerror", (error) => pageErrors.push(error.message));
const apiRequestFailures = [];
page.on("requestfailed", (request) => {
  if (request.url().startsWith(apiUrl) || request.url().startsWith(ingestionUrl)) {
    apiRequestFailures.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText || "request failed"}`);
  }
});

const screenshots = [];
async function capture(name) {
  const destination = path.join(outputDirectory, `${name}.png`);
  await page.screenshot({ path: destination, fullPage: true, animations: "disabled" });
  screenshots.push(destination);
}

let runError;
let observed = {
  apiModelVersion: modelManifest.version,
  models: modelManifest.activeModels,
  reportedValidationF1: modelManifest.validationF1,
  databasePersistenceEnabled: initialHealth.database_enabled,
  kafkaHealthy: initialHealth.kafka_consumer_connected && initialHealth.kafka_producer_connected,
  initialProcessedMessages: Number(initialHealth.processed_messages) || 0,
  initialAlertCount: initialAlerts.length,
};
let temporaryVideo;

try {
  recordingStartedAt = Date.now();
  await page.goto(portalUrl, { waitUntil: "domcontentloaded" });
  await page.getByRole("link", { name: "Access Your Account" }).waitFor();
  await capture("00-novatrust-home");
  await holdUntil(5);

  await page.getByRole("link", { name: "Access Your Account" }).click();
  await page.locator("#email").fill("normal1@novatrust.com");
  await page.locator("#password").fill("password123");
  await page.getByRole("button", { name: "Sign In", exact: true }).click();
  await page.waitForURL((url) => url.pathname.endsWith("/dashboard"), { timeout: 25000 });
  await page.getByRole("heading", { name: /Welcome back, Alice/ }).waitFor();
  await page.getByText("Available Balance").waitFor();
  await capture("01-novatrust-account");
  await holdUntil(12);

  await page.getByRole("link", { name: "Transfer", exact: true }).first().click();
  await page.getByRole("heading", { name: "Transfer Money" }).waitFor();
  await page.locator("#recipientName").fill("Demo Recipient");
  await page.locator("#accountNumber").fill("1234567890");
  await page.locator("#routingNumber").fill("021000021");
  await page.locator("#amount").fill("25.00");
  await page.locator("#memo").fill("Demo OR 1=1 -- simulated attack signal");
  await page.getByRole("button", { name: "Transfer Money", exact: true }).click();
  await page.waitForURL((url) => url.pathname.endsWith("/security-alert"), { timeout: 25000 });
  await page.getByRole("heading", { name: "Security Alert" }).waitFor();
  const portalAlert = await waitForPortalAlert(new Set(initialAlerts.map((alert) => alert.id)));
  await page.getByText("Sandbox State").waitFor();
  observed = {
    ...observed,
    portalUsecase: {
      status: "passed",
      simulatedAccount: "alice",
      verdict: portalAlert.verdict,
      severity: portalAlert.severity,
      alertId: portalAlert.id,
      sourceIp: portalAlert.sourceIp,
    },
  };
  await capture("02-novatrust-security-alert");
  await holdUntil(30);

  await page.goto(dashboardUrl, { waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: "Security operations" }).waitFor();
  if ((await page.getByText("MOCK DATA MODE · not live inference").count()) > 0) {
    throw new Error("Mock mode is visible. Turn off VITE_USE_MOCKS and VITE_DEV_MOCK_FALLBACK before recording.");
  }
  await capture("03-service-startup");
  await holdUntil(38);
  await page.getByText("Loading", { exact: true }).waitFor({ state: "detached", timeout: 25000 });
  await capture("04-overview");
  await holdUntil(46);

  await page.getByRole("tab", { name: "Model health" }).click();
  await page.getByText("Active inference ensemble").waitFor();
  await page.locator("dd").filter({ hasText: modelManifest.version }).first().waitFor();
  await page.getByText("Reported validation F1").waitFor();
  await capture("05-model-health");
  await holdUntil(63);

  await page.getByRole("tab", { name: "Pipeline" }).click();
  await page.getByText("Portal accounts and activity are simulated; inference and verdict APIs are local.").waitFor();
  await capture("06-scenario-ready");
  await holdUntil(71.5);

  const activeHackerCard = page.locator("article").filter({ hasText: "Active Hacker" }).filter({ hasText: "Unknown Intruder" });
  const runButton = activeHackerCard.getByRole("button", { name: "Run scenario" });
  if ((await runButton.count()) !== 1) {
    throw new Error("Could not find the seeded Active Hacker scenario in the pipeline workbench.");
  }
  await runButton.click();

  await page.getByRole("heading", { name: "Raw ingress accepted", exact: true }).waitFor({ timeout: 20000 });
  await page.getByText("Generated interaction signals are ready for scoring").waitFor();
  await capture("07-ingestion-and-simulated-input");

  await page.getByRole("heading", { name: "Model output and demo containment decision" }).waitFor({ timeout: 30000 });
  await page.getByText(/explicit WEB_ATTACK test signal activates local containment/i).waitFor();
  await capture("08-model-and-containment");

  await page.getByText("Alert recorded; feedback pending", { exact: true }).waitFor({ timeout: 30000 });
  await page.getByText(`Active model ${modelManifest.version} remains unchanged`, { exact: true }).waitFor();
  await page.getByText("Promotion disabled", { exact: true }).waitFor();

  const postScenarioHealth = await waitForProcessedMessages(Number(initialHealth.processed_messages) || 0);
  const currentManifest = await readJson(`${apiUrl}/api/v1/model/version`);
  if (currentManifest.version !== modelManifest.version) {
    throw new Error(`The active model changed during the walkthrough (${modelManifest.version} → ${currentManifest.version}).`);
  }
  const alerts = await readJson(`${apiUrl}/api/v1/alerts`);
  const originalAlertIds = new Set(initialAlerts.map((alert) => alert.id));
  const demoAlert = alerts.find(
    (alert) => !originalAlertIds.has(alert.id) && alert.verdict === "HACKER" && alert.sourceIp === "203.0.113.77",
  );
  if (!demoAlert) {
    throw new Error("The local scenario did not create a new analyst-visible HACKER alert for 203.0.113.77.");
  }

  observed = {
    ...observed,
    processedMessagesAfterRun: Number(postScenarioHealth.processed_messages),
    processedMessageDelta: Number(postScenarioHealth.processed_messages) - (Number(initialHealth.processed_messages) || 0),
    alertId: demoAlert.id,
    alertVerdict: demoAlert.verdict,
    alertSeverity: demoAlert.severity,
    alertSourceIp: demoAlert.sourceIp,
    modelUnchanged: true,
  };
  await capture("09-scenario-result");
  await holdUntil(104.5);

  await page.getByRole("link", { name: "Intel Feed" }).click();
  await page.getByRole("heading", { name: "Alert triage" }).waitFor();
  await page.getByText("Threat", { exact: true }).first().waitFor();
  await page.getByText("203.0.113.77", { exact: false }).first().waitFor();
  await capture("10-intel-feed");
  await holdUntil(112.5);

  await page.getByRole("link", { name: "Response" }).click();
  await page.getByRole("heading", { name: "Incident response" }).waitFor();
  await page.getByRole("tab", { name: "Incident queue" }).click();
  await page.getByText("Recommended actions").waitFor();
  await page.getByText("Escalate to containment and isolate account activity.").first().waitFor();
  await capture("11-response-queue");
  await holdUntil(120.5);

  await page.getByRole("link", { name: "Overview" }).click();
  await page.getByRole("heading", { name: "Security operations" }).waitFor();
  await capture("12-close");
  await holdUntil(130);
  if (pageErrors.length || apiRequestFailures.length) {
    throw new Error(
      `Browser errors: ${pageErrors.join("; ") || "none"}; API request failures: ${apiRequestFailures.join("; ") || "none"}`,
    );
  }
} catch (error) {
  runError = error;
} finally {
  const video = page.video();
  await context.close();
  temporaryVideo = await video.path().catch(() => undefined);
  await browser.close();
}

const finalVideo = path.join(outputDirectory, "neurosoc-local-pilot-walkthrough.webm");
if (temporaryVideo) {
  await copyFile(temporaryVideo, finalVideo);
}

const report = {
  status: runError ? "failed" : "passed",
  startedAt: runId,
  dashboardUrl,
  portalUrl,
  apiUrl,
  ingestionUrl,
  browserChannel,
  voiceoverWordsPerSecond: 2,
  observed,
  pageErrors,
  apiRequestFailures,
  screenshots,
  video: temporaryVideo ? finalVideo : null,
  failure: runError ? String(runError.stack || runError) : null,
};
await writeFile(path.join(outputDirectory, "walkthrough-metadata.json"), `${JSON.stringify(report, null, 2)}\n`, "utf8");

if (runError) {
  console.error(`Walkthrough failed. Recording and diagnostics: ${outputDirectory}`);
  console.error(runError.stack || runError);
  process.exitCode = 1;
} else {
  console.log(`Walkthrough recorded: ${finalVideo}`);
  console.log(`Screenshots and evidence: ${outputDirectory}`);
  console.log(`Model ${observed.apiModelVersion}; alert ${observed.alertVerdict}/${observed.alertSeverity}; ` +
    `${observed.processedMessageDelta} Kafka/inference messages processed.`);
}
