import { lazy, Suspense, useMemo } from "react";
import { Link } from "react-router-dom";
import CardSwap, { SwapCard } from "./CardSwap";
import SpecularButton from "./SpecularButton";
import { DEMO_DATA_ENABLED } from "../lib/featureFlags";
import { useCountUp, useInView } from "../hooks/useReveal";
import { useDashboardStore } from "../store/dashboardStore";

const Beams = lazy(() => import("./Beams"));

const verdictLabel = { HACKER: "Threat", FORGETFUL_USER: "Review", LEGITIMATE: "Normal", INCONCLUSIVE: "Monitoring" };
const pct = (value) => Math.round((Number(value) || 0) * 100);

const accent = "text-[#6f9fff]";

/** Fades and lifts its children in once they scroll into view; `delay` staggers siblings. */
function Reveal({ as: Tag = "div", delay = 0, className = "", children, ...rest }) {
  const [ref, visible] = useInView();
  return (
    <Tag ref={ref} className={`soc-reveal ${visible ? "is-in" : ""} ${className}`} style={{ "--d": `${delay}ms` }} {...rest}>
      {children}
    </Tag>
  );
}

export function Chip({ children }) {
  return (
    <span className="text-xs text-soc-muted">{children}</span>
  );
}

export function Hero({ onOpenAlerts }) {
  return (
    <section className="soc-glass relative isolate mt-2 overflow-hidden px-8 py-16 md:px-14 md:py-24">
      <div className="soc-fade-in pointer-events-none absolute inset-0 -z-20" aria-hidden="true">
        <Suspense fallback={null}>
          <Beams beamWidth={2.4} beamHeight={18} beamNumber={10} lightColor="#6f9fff" backgroundColor="#05070d" speed={1.6} noiseIntensity={1.5} scale={0.18} rotation={32} />
        </Suspense>
      </div>
      {/* Keep the headline side dark enough to read over the beams. */}
      <div className="pointer-events-none absolute inset-0 -z-10 bg-gradient-to-r from-[#05070d] via-[#05070d]/80 to-transparent" aria-hidden="true" />
      {/* Soft blue light spilling in from the top-right, as in the reference deck. */}
      <div className="pointer-events-none absolute -right-32 -top-40 -z-10 h-[560px] w-[760px] rounded-full bg-[#3f7bff]/35 blur-[130px] soc-drift" aria-hidden="true" />
      <div className="pointer-events-none absolute right-10 top-0 -z-10 h-[260px] w-[360px] rounded-full bg-[#a9c6ff]/25 blur-[90px] soc-drift soc-drift-alt" aria-hidden="true" />
      <div className="pointer-events-none absolute -bottom-48 -left-24 -z-10 h-[380px] w-[520px] rounded-full bg-[#1d3fa8]/30 blur-[120px] soc-drift soc-drift-slow" aria-hidden="true" />
      <div className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-px bg-gradient-to-r from-transparent via-white/25 to-transparent" aria-hidden="true" />

      <p className="soc-rise text-xs text-soc-muted" style={{ "--d": "0ms" }}>NeuroSOC · Security operations</p>
      <h1 style={{ "--d": "120ms" }} className="soc-rise mt-6 max-w-3xl text-4xl font-light leading-[1.08] tracking-[-0.03em] text-white md:text-[60px]">
        <span className="soc-shimmer">AI-powered</span> threat defence for every session
      </h1>
      <p style={{ "--d": "240ms" }} className="soc-rise mt-6 max-w-lg text-[15px] leading-relaxed text-white/55">
        Sessions are scored in real time. Threats are isolated quietly, and analysts keep the final word.
      </p>
      <div style={{ "--d": "360ms" }} className="soc-rise mt-10 flex flex-wrap items-center gap-3">
        <SpecularButton
          size="sm"
          radius={10}
          textColor="#05070d"
          baseColor="#ffffff"
          lineColor="#5b93ff"
          tint="#ffffff"
          tintOpacity={1}
          onClick={onOpenAlerts}
        >
          Open alerts
        </SpecularButton>
        <Link
          to="/intel-feed"
          className="rounded-[10px] border border-white/10 bg-white/[0.04] px-[22px] py-[11px] text-[13.6px] font-medium text-white/85 transition hover:bg-white/[0.08]"
        >
          Explore intel
        </Link>
      </div>
    </section>
  );
}

function Stat({ value, decimals = 0, unit, label, hint, delay }) {
  const [ref, visible] = useInView();
  const shown = useCountUp(value, visible);
  const text = shown.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });

  return (
    <article
      ref={ref}
      style={{ "--d": `${delay}ms` }}
      className={`soc-glass soc-lift soc-reveal ${visible ? "is-in" : ""} group relative flex min-h-[210px] min-w-0 flex-col justify-between overflow-hidden p-6`}
    >
      <div className="pointer-events-none absolute -left-16 -top-16 h-48 w-48 rounded-full bg-[#2f5fe0]/20 blur-3xl transition-colors duration-500 group-hover:bg-[#2f5fe0]/40" aria-hidden="true" />
      <span className="relative text-xs text-soc-muted">{hint}</span>
      <div className="relative">
        <p className="soc-tabular truncate text-5xl font-extralight leading-none tracking-[-0.04em] xl:text-[56px]">
          <span className="text-[#6f9fff]">{text}</span>
          {unit ? <span className="ml-1 text-2xl text-[#5b93ff]">{unit}</span> : null}
        </p>
        <p className="mt-4 line-clamp-2 text-[13px] leading-snug text-soc-muted">{label}</p>
      </div>
    </article>
  );
}

export function WhyNow() {
  const stats = useDashboardStore((state) => state.stats.data);
  const demoAlertCount = useDashboardStore((state) => state.alerts.items.length);

  return (
    <section className="pt-6">
      <Reveal>
        <Chip>At a glance</Chip>
      </Reveal>
      <Reveal as="h2" delay={80} className="mt-5 text-3xl font-light tracking-[-0.03em] text-white md:text-[40px]">
        Today, <span className={accent}>in numbers</span>
      </Reveal>
      <div className="mt-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat delay={0} value={Number(stats.totalTransactions || 0)} label="Sessions scored by the decision layer" hint="Analysed" />
        <Stat delay={90} value={Number(stats.hackerDetections || 0)} label="Confirmed threats routed to sandbox isolation" hint="Isolated" />
        <Stat delay={180} value={Number(stats.avgRiskScore || 0)} decimals={1} unit="%" label="Mean risk score across analysed sessions" hint="Average risk" />
        <Stat
          delay={270}
          value={Number(DEMO_DATA_ENABLED ? demoAlertCount : stats.liveAlerts || 0)}
          label={DEMO_DATA_ENABLED ? "Seeded and generated stream events" : "Available for investigation"}
          hint="Events"
        />
      </div>
    </section>
  );
}

const STEPS = [
  ["01", "Score every session", "Behaviour, device and network signals combine into one risk score."],
  ["02", "Isolate the threat", "Likely attackers are moved to a sandbox before they reach funds."],
  ["03", "Analyst decides", "Every verdict stays reviewable, and your feedback retrains the model."],
];

export function Workspace() {
  const alerts = useDashboardStore((state) => state.alerts.items);
  const top = useMemo(() => alerts.slice(0, 3), [alerts]);
  const cards = top.length ? top : [{}, {}, {}];

  return (
    <section className="pt-16">
      <Reveal>
        <Chip>How it works</Chip>
      </Reveal>
      <Reveal as="h2" delay={80} className="mt-5 max-w-3xl text-3xl font-light leading-tight tracking-[-0.03em] text-white md:text-[40px]">
        Scattered alerts, turned <span className={accent}>into a structured system</span> your team can act on
      </Reveal>

      <div className="mt-8 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <div className="grid gap-4">
          {STEPS.map(([n, title, body], i) => (
            <Reveal as="article" key={n} delay={i * 110} className="soc-glass soc-lift group flex min-w-0 items-start gap-5 p-6">
              <span className="text-xs text-[#6f9fff] transition-transform duration-300 group-hover:translate-x-0.5">{n}</span>
              <div className="min-w-0">
                <h3 className="text-base font-normal text-white">{title}</h3>
                <p className="mt-1.5 text-[13px] leading-relaxed text-soc-muted">{body}</p>
              </div>
            </Reveal>
          ))}
        </div>

        <Reveal delay={200} className="soc-glass soc-swap-stage relative min-h-[380px] overflow-hidden">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_60%_at_60%_40%,rgba(47,95,224,0.28),transparent_70%)] soc-pulse-glow" aria-hidden="true" />
          <span className="absolute left-6 top-6 text-xs text-soc-muted">Latest verdicts</span>
          <CardSwap width={300} height={180} cardDistance={40} verticalDistance={40} delay={4200} pauseOnHover>
            {cards.map((a, i) => (
              <SwapCard
                key={a.id || i}
                className="flex flex-col justify-between overflow-hidden rounded-2xl border-white/10 p-5 text-white"
                style={{
                  background:
                    "linear-gradient(160deg, #3f66c9 0%, #16296b 40%, #080c18 100%)",
                  boxShadow: "inset 0 1px 0 rgba(255,255,255,0.18), 0 30px 60px -25px rgba(0,0,0,0.9)",
                }}
              >
                <span className="text-xs text-white/60">
                  {verdictLabel[a.verdict] || "Monitoring"}
                </span>
                <span className="line-clamp-1 text-sm font-light text-white/85">
                  {a.sourceIp ? `${a.userName || a.sourceIp}${a.locationLabel ? ` · ${a.locationLabel}` : ""}` : "Waiting for events"}
                </span>
                <span className="soc-tabular text-4xl font-extralight tracking-[-0.04em]">
                  {a.sourceIp ? pct(a.score) : "--"}
                  <span className="ml-0.5 text-lg text-white/60">% risk</span>
                </span>
              </SwapCard>
            ))}
          </CardSwap>
        </Reveal>
      </div>
    </section>
  );
}
