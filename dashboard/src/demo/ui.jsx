// Tiny design kit for the NovaTrust customer app: light, quiet, lots of whitespace.
export function Card({ title, action, children, className = "" }) {
  return (
    <section className={`rounded-2xl border border-slate-200 bg-white p-6 shadow-sm ${className}`}>
      {title || action ? (
        <div className="mb-4 flex items-center justify-between gap-3">
          {title ? <h2 className="text-sm font-semibold tracking-tight text-slate-900">{title}</h2> : <span />}
          {action}
        </div>
      ) : null}
      {children}
    </section>
  );
}

const TONES = {
  neutral: "border-slate-200 bg-slate-50 text-slate-600",
  good: "border-emerald-200 bg-emerald-50 text-emerald-700",
  warn: "border-amber-200 bg-amber-50 text-amber-800",
  bad: "border-rose-200 bg-rose-50 text-rose-700",
  info: "border-indigo-200 bg-indigo-50 text-indigo-700",
};

export function Pill({ tone = "neutral", children, className = "" }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${TONES[tone]} ${className}`}>
      {children}
    </span>
  );
}

export function Button({ variant = "primary", className = "", ...props }) {
  const styles = {
    primary: "bg-slate-900 text-white hover:bg-slate-700 disabled:bg-slate-300",
    secondary: "border border-slate-300 bg-white text-slate-800 hover:bg-slate-50 disabled:text-slate-400",
    ghost: "text-slate-600 hover:bg-slate-100 disabled:text-slate-300",
    danger: "border border-rose-300 bg-white text-rose-700 hover:bg-rose-50 disabled:text-rose-300",
  };
  return (
    <button
      type="button"
      {...props}
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors
        focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed ${styles[variant]} ${className}`}
    />
  );
}

export function Field({ label, hint, children, htmlFor }) {
  return (
    <div>
      <label htmlFor={htmlFor} className="mb-1.5 block text-xs font-medium text-slate-600">{label}</label>
      {children}
      {hint ? <p className="mt-1 text-xs text-slate-400">{hint}</p> : null}
    </div>
  );
}

export const inputClass =
  "block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 " +
  "focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200 disabled:bg-slate-50";

export function Spinner({ label = "Loading" }) {
  return (
    <span role="status" className="inline-flex items-center gap-2 text-xs text-slate-500">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-300 border-t-slate-700" aria-hidden="true" />
      {label}
    </span>
  );
}

export function Notice({ tone = "info", title, children, action }) {
  const palette = {
    info: "border-indigo-200 bg-indigo-50 text-indigo-900",
    warn: "border-amber-200 bg-amber-50 text-amber-900",
    bad: "border-rose-200 bg-rose-50 text-rose-900",
    good: "border-emerald-200 bg-emerald-50 text-emerald-900",
  }[tone];
  return (
    <div role={tone === "bad" ? "alert" : "status"} className={`flex flex-wrap items-start justify-between gap-3 rounded-xl border px-4 py-3 text-sm ${palette}`}>
      <div>
        {title ? <p className="font-semibold">{title}</p> : null}
        <div className={title ? "mt-0.5 text-[13px] leading-relaxed" : "leading-relaxed"}>{children}</div>
      </div>
      {action}
    </div>
  );
}

export function Skeleton({ className = "" }) {
  return <div className={`animate-pulse rounded-lg bg-slate-200/70 ${className}`} aria-hidden="true" />;
}
