import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import CardSwap, { SwapCard } from '../components/CardSwap';

const MEDIA = `${import.meta.env.BASE_URL}media`;
const tabular = { fontVariantNumeric: 'tabular-nums' as const };
const ORANGE_GRADIENT = 'linear-gradient(135deg,#ff8a1f,#ff4d2e)';

const NAV = [
  ['Features', '#features'],
  ['Cards', '#cards'],
  ['Security', '#security'],
  ['FAQ', '#faq'],
] as const;

export function BackgroundVideo() {
  return (
    <div className="pointer-events-none fixed inset-0 -z-0 overflow-hidden bg-[#07080d]" aria-hidden="true">
      <video
        className="h-full w-full object-cover opacity-70 [filter:invert(1)_contrast(1.15)_brightness(.9)] motion-reduce:hidden"
        src={`${MEDIA}/hero.mp4`}
        autoPlay
        loop
        muted
        playsInline
        preload="auto"
      />
      <div className="absolute inset-0 bg-[radial-gradient(70%_70%_at_50%_40%,transparent,rgba(7,8,13,.75))]" />
    </div>
  );
}

export function LandingHeader() {
  return (
    <header className="absolute inset-x-0 top-0 z-30">
      <div className="mx-auto mt-4 flex h-14 max-w-6xl items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-5 backdrop-blur-md">
        <Link to="/" className="flex items-center gap-2.5">
          <img src={`${import.meta.env.BASE_URL}logo.png`} alt="" className="h-8 w-8 rounded-lg" />
          <span className="text-base font-semibold tracking-tight text-white">NovaTrust</span>
        </Link>

        <nav className="hidden items-center gap-8 text-sm text-white/70 md:flex">
          {NAV.map(([label, href]) => (
            <a key={label} href={href} className="transition-colors hover:text-white">
              {label}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <Link to="/login" className="px-3 py-2 text-sm text-white/80 transition-colors hover:text-white">
            Log in
          </Link>
          <a
            href="#top"
            onClick={(e) => {
              e.preventDefault();
              window.scrollTo({ top: 0, behavior: 'smooth' });
              document.getElementById('hero-email')?.focus({ preventScroll: true });
            }}
            className="rounded-lg bg-white/15 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-white/25"
          >
            Get started
          </a>
        </div>
      </div>
    </header>
  );
}

function GlassCard({ className = '', style }: { className?: string; style?: React.CSSProperties }) {
  return (
    <div
      className={`relative aspect-[1.586] w-[280px] overflow-hidden rounded-2xl border border-white/20 p-5 text-white shadow-2xl backdrop-blur-xl ${className}`}
      style={{ background: 'linear-gradient(135deg,rgba(255,255,255,.22),rgba(255,255,255,.04))', ...style }}
    >
      <div className="flex items-start justify-between">
        <span className="text-sm font-semibold tracking-tight">NovaTrust</span>
        <span className="flex">
          <span className="h-6 w-6 rounded-full bg-red-500/90" />
          <span className="-ml-2.5 h-6 w-6 rounded-full bg-amber-400/90" />
        </span>
      </div>
      <div className="mt-6 h-6 w-9 rounded-md bg-gradient-to-br from-amber-200/80 to-amber-500/60" />
      <p className="mt-4 whitespace-nowrap text-base tracking-[0.14em]" style={tabular}>4804 9556 8008 8300</p>
      <div className="mt-3 flex items-end justify-between text-[10px] uppercase tracking-widest text-white/70">
        <span>Demo Customer</span>
        <span style={tabular}>01/29</span>
      </div>
    </div>
  );
}

export function Hero() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  return (
    <section className="relative isolate min-h-[100svh] overflow-hidden">
      <div className="absolute inset-0 -z-10 bg-[radial-gradient(60%_60%_at_75%_40%,rgba(255,110,40,.28),transparent_70%),linear-gradient(to_bottom,rgba(7,8,13,.25),rgba(7,8,13,.6))]" />

      <div className="mx-auto grid min-h-[100svh] max-w-6xl items-center gap-10 px-6 pb-24 pt-32 md:grid-cols-[1.05fr_1fr]">
        <div>
          <p className="text-sm text-white/60">Your finances in your pocket</p>
          <h1 className="mt-3 text-4xl font-semibold leading-[1.1] tracking-tight text-white md:text-6xl">
            Smart banking for your every transaction
          </h1>
          <p className="mt-5 max-w-md text-base leading-relaxed text-white/60">
            Pay, save and move money in seconds. Every session is quietly checked in the background, so genuine
            customers never notice.
          </p>

          <form
            className="mt-8 flex max-w-md items-center gap-2 rounded-2xl border border-white/10 bg-white/5 p-2 backdrop-blur-md"
            onSubmit={(e) => {
              e.preventDefault();
              navigate(email ? `/signup?email=${encodeURIComponent(email)}` : '/signup');
            }}
          >
            <span className="pl-3 text-white/40" aria-hidden="true">✉</span>
            <label htmlFor="hero-email" className="sr-only">Email</label>
            <input
              id="hero-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Enter your email"
              className="min-w-0 flex-1 bg-transparent px-1 py-2 text-sm text-white placeholder:text-white/40 focus:outline-none"
            />
            <button
              type="submit"
              className="rounded-xl px-4 py-2 text-sm font-semibold text-white shadow-[0_0_24px_-4px_rgba(255,110,40,.7)] transition-transform hover:scale-105"
              style={{ background: ORANGE_GRADIENT }}
            >
              Get started
            </button>
          </form>

          <div className="mt-5 flex flex-wrap gap-x-6 gap-y-2 text-sm">
            <a href="#features" className="text-white/80 underline-offset-4 hover:text-white hover:underline">
              Explore features
            </a>
            <a href="#security" className="text-white/60 underline-offset-4 hover:text-white hover:underline">
              How protection works
            </a>
            <Link to="/system-flow" className="text-white/60 underline-offset-4 hover:text-white hover:underline">
              How protection works
            </Link>
          </div>
        </div>

        <div className="relative mx-auto hidden h-[440px] w-full max-w-[520px] md:block">
          <div
            className="absolute inset-[10%] rounded-full opacity-60 blur-3xl"
            style={{ background: 'radial-gradient(circle at 30% 30%,#ffc233,#ff5a1f 60%,transparent 72%)' }}
          />
          <CardSwap width={340} height={230} cardDistance={44} verticalDistance={50} delay={4500} pauseOnHover>
            <SwapCard className="overflow-hidden">
              <img src={`${MEDIA}/card-black.jpg`} alt="NovaTrust black card" className="h-full w-full object-cover" />
            </SwapCard>
            <SwapCard className="overflow-hidden">
              <img src={`${MEDIA}/card-hand.jpg`} alt="NovaTrust card in hand" className="h-full w-full object-cover" />
            </SwapCard>
            <SwapCard className="flex flex-col justify-between bg-gradient-to-br from-[#1b1d2a] to-[#07080d] p-5 text-white">
              <span className="text-xs text-white/50">Available balance</span>
              <span className="text-3xl font-semibold" style={tabular}>$24,092.67</span>
              <span className="text-xs text-emerald-300">Protected by NeuroShield</span>
            </SwapCard>
          </CardSwap>
        </div>
      </div>

      <div className="absolute inset-x-0 bottom-6 mx-auto hidden max-w-6xl gap-4 px-6 md:flex">
        {[
          ['Therapy Session', '$400.15', '4:36 pm'],
          ['Grocery store', '$42.18', '2:10 pm'],
          ['Electricity', '$96.40', 'Yesterday'],
        ].map(([name, amount, time]) => (
          <div
            key={name}
            className="flex flex-1 items-center justify-between rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-xs text-white/80 backdrop-blur-md"
          >
            <span>
              {name}
              <span className="block text-[10px] text-white/40">{time}</span>
            </span>
            <span style={tabular}>{amount}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

const SERVICES = [
  {
    to: '/dashboard',
    cta: 'Open your account',
    title: 'Everyday banking',
    desc: 'Current and savings accounts with instant notifications and card controls.',
    path: 'M3 10h18M5 6h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2Zm2 9h4',
  },
  {
    to: '/transfer',
    cta: 'Make a transfer',
    title: 'Payments and transfers',
    desc: 'Pay saved payees or new recipients, with an extra check on larger amounts.',
    path: 'M7 7h11l-3-3M17 17H6l3 3',
  },
  {
    to: '/system-flow',
    cta: 'See it in action',
    title: 'Session protection',
    desc: 'Sign-ins and transfers are checked in the background. Unusual activity is paused for review.',
    path: 'M12 3 5 6v5c0 4.4 3 8.3 7 9.5 4-1.2 7-5.1 7-9.5V6l-7-3Zm-3 9 2 2 4-4',
  },
];

export function Services() {
  return (
    <section id="features" className="bg-[#07080d]/60 backdrop-blur-[2px]">
      <div className="mx-auto max-w-6xl px-6 py-24">
        <h2 className="text-3xl font-semibold tracking-tight text-white">What you can do</h2>
        <div className="mt-10 grid gap-5 md:grid-cols-3">
          {SERVICES.map((service) => (
            <Link
              key={service.title}
              to={service.to}
              className="block rounded-2xl border border-white/10 bg-white/[0.04] p-6 transition-all duration-300 hover:-translate-y-1 hover:bg-white/[0.07] hover:border-white/20"
            >
              <span className="flex h-10 w-10 items-center justify-center rounded-xl text-white" style={{ background: ORANGE_GRADIENT }}>
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d={service.path} />
                </svg>
              </span>
              <h3 className="mt-5 text-base font-semibold text-white">{service.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-white/60">{service.desc}</p>
              <p className="mt-4 text-sm font-medium text-orange-400">{service.cta} →</p>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}

export function Cards() {
  return (
    <section id="cards" className="border-t border-white/10 bg-[#0a0b12]/70 backdrop-blur-sm">
      <div className="mx-auto grid max-w-6xl items-center gap-12 px-6 py-24 md:grid-cols-2">
        <div>
          <h2 className="text-3xl font-semibold tracking-tight text-white">A card that stays in your control</h2>
          <p className="mt-4 max-w-md text-sm leading-relaxed text-white/60">
            Freeze it, set limits and see every payment the moment it happens. Your balance and card activity sit
            in one place.
          </p>
          <div className="mt-8 rounded-2xl border border-white/10 bg-white/[0.04] p-6">
            <div className="flex items-center justify-between">
              <p className="text-sm text-white/60">Current account</p>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-400/10 px-2.5 py-0.5 text-xs font-medium text-emerald-300">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                Protected
              </span>
            </div>
            <p className="mt-3 text-3xl font-semibold tracking-tight text-white" style={tabular}>£4,218.60</p>
            <p className="mt-1 text-xs text-white/40">Available balance · example</p>
          </div>
          <Link to="/dashboard" className="mt-6 inline-block text-sm font-medium text-orange-400 hover:text-orange-300">
            View your dashboard →
          </Link>
        </div>
        <div className="relative mx-auto h-[300px] w-full max-w-[420px]">
          <GlassCard className="absolute left-0 top-0 rotate-[-10deg]" style={{ background: 'linear-gradient(135deg,rgba(255,255,255,.14),rgba(255,255,255,.02))' }} />
          <GlassCard className="absolute bottom-0 right-0 rotate-[6deg]" style={{ background: 'linear-gradient(135deg,rgba(255,138,31,.55),rgba(255,77,46,.25))' }} />
        </div>
      </div>
    </section>
  );
}

const OUTCOMES = [
  ['Continuous protection', 'Every sign-in and payment is checked in real time against how you normally bank.'],
  ['Instant alerts', 'We let you know straight away if something does not look like you.'],
  ['Around-the-clock team', 'Our security specialists review unusual activity 24 hours a day.'],
];

export function SecurityExplainer() {
  return (
    <section id="security" className="border-t border-white/10 bg-[#07080d]/70 backdrop-blur-sm">
      <div className="mx-auto grid max-w-6xl gap-10 px-6 py-24 md:grid-cols-2">
        <div>
          <h2 className="text-3xl font-semibold tracking-tight text-white">How we protect your account</h2>
          <p className="mt-4 text-sm leading-relaxed text-white/60">
            Security runs quietly in the background of every session, learning how you normally bank so genuine
            customers are never slowed down.
          </p>
        </div>
        <ol className="space-y-5 text-sm">
          {OUTCOMES.map(([title, desc], index) => (
            <li key={title} className="flex gap-4">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-white/20 text-xs font-medium text-white/80">
                {index + 1}
              </span>
              <div>
                <p className="font-medium text-white">{title}</p>
                <p className="mt-0.5 text-white/60">{desc}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

const FAQ = [
  ['Is this a real bank?', 'No. NovaTrust is a demonstration bank used to simulate sessions for the NeuroSOC project.'],
  ['What happens if my session looks unusual?', 'It is paused for review. Reloading restores access if the check clears.'],
  ['Can I try an attack scenario?', 'Yes. Open the security demo to walk through each verdict.'],
];

export function Faq() {
  return (
    <section id="faq" className="border-t border-white/10 bg-[#0a0b12]/70 backdrop-blur-sm">
      <div className="mx-auto max-w-3xl px-6 py-24">
        <h2 className="text-3xl font-semibold tracking-tight text-white">Frequently asked</h2>
        <div className="mt-8 divide-y divide-white/10 border-y border-white/10">
          {FAQ.map(([q, a]) => (
            <details key={q} className="group py-4">
              <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium text-white">
                {q}
                <span className="text-white/40 transition-transform group-open:rotate-45">+</span>
              </summary>
              <p className="mt-3 text-sm leading-relaxed text-white/60">{a}</p>
            </details>
          ))}
        </div>
        <div className="mt-10 flex gap-3">
          <Link to="/login" className="rounded-xl px-5 py-2.5 text-sm font-semibold text-white" style={{ background: ORANGE_GRADIENT }}>
            Sign in
          </Link>
          <Link to="/system-flow" className="rounded-xl border border-white/15 px-5 py-2.5 text-sm text-white/80 hover:bg-white/5">
            Security demo
          </Link>
        </div>
      </div>
    </section>
  );
}

export function LandingFooter() {
  return (
    <footer className="border-t border-white/10 bg-[#07080d]/70 backdrop-blur-sm">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 px-6 py-8 text-xs text-white/40 md:flex-row md:items-center md:justify-between">
        <p>© NovaTrust — demonstration bank for the NeuroSOC project. Not a real financial institution.</p>
        <div className="flex gap-5">
          <a href="#" className="hover:text-white/70">Privacy</a>
          <a href="#" className="hover:text-white/70">Terms</a>
          <a href="#security" className="hover:text-white/70">Security</a>
        </div>
      </div>
    </footer>
  );
}
