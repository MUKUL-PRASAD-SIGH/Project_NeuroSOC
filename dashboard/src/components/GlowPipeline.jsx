import { useLayoutEffect, useRef, useState } from "react";

const STATUS_COPY = {
  active: "Live",
  complete: "Done",
  pending: "Queued",
};

function resolveStatus(index, activeIndex, isRunning) {
  if (activeIndex < 0 || index > activeIndex) return "pending";
  if (index < activeIndex) return "complete";
  return isRunning ? "active" : "complete";
}

// A grey pipe that fills with glowing blue, pulled down stage by stage as a run advances.
export default function GlowPipeline({ phases, activePhase, isRunning }) {
  const listRef = useRef(null);
  const rowRefs = useRef([]);
  const [centers, setCenters] = useState([]);
  const activeIndex = phases.findIndex((phase) => phase.id === activePhase);

  useLayoutEffect(() => {
    const list = listRef.current;
    if (!list) return undefined;

    function measure() {
      setCenters(rowRefs.current.slice(0, phases.length).map((node) => (node ? node.offsetTop + node.offsetHeight / 2 : 0)));
    }

    const observer = new ResizeObserver(measure);
    observer.observe(list);
    measure();
    return () => observer.disconnect();
  }, [phases.length]);

  const top = centers[0] ?? 0;
  const bottom = centers[centers.length - 1] ?? 0;
  const reach = activeIndex >= 0 ? centers[activeIndex] ?? top : top;
  const fillHeight = activeIndex >= 0 ? reach - top : 0;
  const lit = activeIndex >= 0;

  return (
    <div ref={listRef} className="relative">
      <div className="soc-pipe-track absolute left-[13px] w-[8px] rounded-full" style={{ top, height: Math.max(bottom - top, 0) }} aria-hidden="true" />
      <div
        className={`soc-pipe-fill absolute left-[13px] w-[8px] rounded-full ${isRunning ? "soc-pipe-fill-running" : ""}`}
        style={{ top, height: fillHeight, opacity: lit ? 1 : 0 }}
        aria-hidden="true"
      />
      <div
        className={`soc-pipe-head absolute left-[17px] ${isRunning ? "soc-pipe-head-running" : ""}`}
        style={{ top: reach, opacity: isRunning ? 1 : 0 }}
        aria-hidden="true"
      />

      <ol className="relative space-y-3">
        {phases.map((phase, index) => {
          const status = resolveStatus(index, activeIndex, isRunning);
          return (
            <li
              key={phase.id}
              ref={(node) => {
                rowRefs.current[index] = node;
              }}
              aria-current={status === "active" ? "step" : undefined}
              className="flex items-center gap-4"
            >
              <span className={`soc-pipe-node soc-pipe-node-${status} relative z-10 ml-[9px] h-4 w-4 shrink-0 rounded-full`} aria-hidden="true" />
              <div className={`soc-pipe-card soc-pipe-card-${status} flex min-w-0 flex-1 items-center justify-between gap-4 rounded-xl border px-4 py-3`}>
                <div className="relative min-w-0">
                  <p className="font-mono text-[10px] tracking-[0.2em] text-soc-muted">{phase.code}</p>
                  <p
                    className={`mt-1 text-sm font-medium transition-colors duration-500 ${
                      status === "active" ? "text-soc-red" : status === "complete" ? "text-soc-text" : "text-soc-muted"
                    }`}
                  >
                    {phase.label}
                  </p>
                </div>
                <span
                  className={`relative shrink-0 font-mono text-[10px] uppercase tracking-[0.18em] transition-colors duration-500 ${
                    status === "active" ? "text-soc-electric" : status === "complete" ? "text-soc-amber" : "text-soc-muted/70"
                  }`}
                >
                  {STATUS_COPY[status]}
                </span>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
