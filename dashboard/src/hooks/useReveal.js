import { useEffect, useRef, useState } from "react";

const reducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Returns [ref, visible]; visible flips true once the element scrolls into view. */
export function useInView(options = { threshold: 0.2 }) {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return undefined;
    if (reducedMotion() || typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return undefined;
    }
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setVisible(true);
        observer.disconnect();
      }
    }, options);
    observer.observe(node);
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return [ref, visible];
}

/** Eases from the previous value to `target` once `active` is true. */
export function useCountUp(target, active, durationMs = 1400) {
  const [value, setValue] = useState(0);
  const fromRef = useRef(0);

  useEffect(() => {
    if (!active) return undefined;
    if (reducedMotion()) {
      setValue(target);
      fromRef.current = target;
      return undefined;
    }
    const from = fromRef.current;
    const started = performance.now();
    let frame = 0;
    const tick = (now) => {
      const t = Math.min(1, (now - started) / durationMs);
      const next = from + (target - from) * (1 - Math.pow(1 - t, 3));
      setValue(next);
      if (t < 1) frame = requestAnimationFrame(tick);
      else fromRef.current = target;
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, active, durationMs]);

  return value;
}
