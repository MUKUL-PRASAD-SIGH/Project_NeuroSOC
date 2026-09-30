import { Link } from 'react-router-dom';

const SERVICES = [
  {
    title: 'Everyday banking',
    desc: 'Current and savings accounts with instant notifications and card controls.',
    path: 'M3 10h18M5 6h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2Zm2 9h4',
  },
  {
    title: 'Payments and transfers',
    desc: 'Pay saved payees or new recipients, with an extra check on larger amounts.',
    path: 'M7 7h11l-3-3M17 17H6l3 3',
  },
  {
    title: 'Session protection',
    desc: 'Sign-ins and transfers are checked in the background. Unusual activity is paused for review.',
    path: 'M12 3 5 6v5c0 4.4 3 8.3 7 9.5 4-1.2 7-5.1 7-9.5V6l-7-3Zm-3 9 2 2 4-4',
  },
];

const OUTCOMES = [
  ['Continuous protection', 'Every sign-in and payment is checked in real time against how you normally bank.'],
  ['Instant alerts', 'We let you know straight away if something does not look like you.'],
  ['Around-the-clock team', 'Our security specialists review unusual activity 24 hours a day.'],
];

const PREVIEW_ROWS = [
  ['Grocery store', '−£42.18'],
  ['Salary', '+£2,800.00'],
  ['Electricity', '−£96.40'],
];

const tabular = { fontVariantNumeric: 'tabular-nums' as const };

export function Hero() {
  return (
    <section className="border-b border-slate-200 bg-slate-50">
      <div className="mx-auto grid max-w-6xl items-center gap-12 px-6 py-20 md:grid-cols-[1.2fr_1fr]">
        <div>
          <p className="text-sm font-medium text-[#1d6fb8]">Online banking</p>
          <h1 className="mt-3 text-4xl font-semibold leading-tight tracking-tight text-[#0b2545] md:text-5xl">
            Banking that keeps your account safe without getting in your way.
          </h1>
          <p className="mt-5 max-w-xl text-base leading-relaxed text-slate-600">
            Manage accounts, pay people and move money. Every session is checked in the background, so genuine
            customers carry on as normal.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link to="/login" className="rounded-md bg-[#0b2545] px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-[#13315c]">
              Sign in to online banking
            </Link>
            <a
              href="#security"
              className="rounded-md border border-slate-300 bg-white px-5 py-2.5 text-sm font-medium text-slate-700 transition-colors hover:border-slate-400"
            >
              How protection works
            </a>
          </div>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-slate-500">Current account</p>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              Protected
            </span>
          </div>
          <p className="mt-3 text-3xl font-semibold tracking-tight text-[#0b2545]" style={tabular}>£4,218.60</p>
          <p className="mt-1 text-xs text-slate-500">Available balance · example</p>
          <div className="mt-6 divide-y divide-slate-100 border-t border-slate-100 text-sm">
            {PREVIEW_ROWS.map(([name, amount]) => (
              <div key={name} className="flex items-center justify-between py-2.5">
                <span className="text-slate-700">{name}</span>
                <span className={amount.startsWith('+') ? 'text-emerald-700' : 'text-slate-900'} style={tabular}>
                  {amount}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

export function Services() {
  return (
    <section>
      <div className="mx-auto max-w-6xl px-6 py-16">
        <h2 className="text-2xl font-semibold tracking-tight text-[#0b2545]">What you can do</h2>
        <div className="mt-8 grid gap-6 md:grid-cols-3">
          {SERVICES.map((service) => (
            <div key={service.title} className="rounded-lg border border-slate-200 p-6">
              <span className="flex h-9 w-9 items-center justify-center rounded-md bg-[#e8f1fb] text-[#1d6fb8]">
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d={service.path} />
                </svg>
              </span>
              <h3 className="mt-4 text-base font-semibold text-slate-900">{service.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">{service.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function SecurityExplainer() {
  return (
    <section id="security" className="border-t border-slate-200 bg-slate-50">
      <div className="mx-auto grid max-w-6xl gap-10 px-6 py-16 md:grid-cols-2">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-[#0b2545]">How we protect your account</h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">
            Security runs quietly in the background of every session, learning how you normally bank so genuine
            customers are never slowed down.
          </p>
        </div>
        <ol className="space-y-4 text-sm">
          {OUTCOMES.map(([title, desc], index) => (
            <li key={title} className="flex gap-4">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-slate-300 bg-white text-xs font-medium text-slate-600">
                {index + 1}
              </span>
              <div>
                <p className="font-medium text-slate-900">{title}</p>
                <p className="mt-0.5 text-slate-600">{desc}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
