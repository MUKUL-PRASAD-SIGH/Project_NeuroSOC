import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

const MEDIA = `${import.meta.env.BASE_URL}media`;
export const ORANGE_GRADIENT = 'linear-gradient(135deg,#ff8a1f,#ff4d2e)';

export const authInputClass =
  'w-full rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white placeholder:text-white/30 outline-none transition-colors focus:border-orange-400/60 focus:bg-white/[0.08]';
export const authLabelClass = 'mb-2 block text-xs font-medium uppercase tracking-wide text-white/50';
export const authButtonClass =
  'w-full rounded-xl py-3 text-sm font-semibold text-white shadow-[0_0_24px_-4px_rgba(255,110,40,.7)] transition-transform hover:scale-[1.02] disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:scale-100';

export function AuthShell({ title, subtitle, children, footer }: {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <div className="relative min-h-screen overflow-hidden bg-[#07080d] text-white antialiased" style={{ fontFamily: 'Inter, system-ui, sans-serif' }}>
      <video
        className="pointer-events-none absolute inset-0 h-full w-full object-cover opacity-50 [filter:invert(1)_contrast(1.15)_brightness(.9)] motion-reduce:hidden"
        src={`${MEDIA}/hero.mp4`}
        autoPlay
        loop
        muted
        playsInline
        aria-hidden="true"
      />
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_60%_at_80%_30%,rgba(255,110,40,.25),transparent_70%),linear-gradient(to_bottom,rgba(7,8,13,.5),rgba(7,8,13,.85))]" />

      <div className="relative z-10 mx-auto grid min-h-screen max-w-6xl items-center gap-12 px-6 py-10 md:grid-cols-2">
        <div className="mx-auto w-full max-w-md">
          <Link to="/" className="mb-8 flex items-center gap-2.5">
            <img src={`${MEDIA.replace(/media$/, '')}logo.png`} alt="" className="h-9 w-9 rounded-lg" />
            <span className="text-lg font-semibold tracking-tight">NovaTrust</span>
          </Link>
          <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-2 text-sm text-white/60">{subtitle}</p>

          <div className="mt-8 rounded-3xl border border-white/10 bg-white/5 p-7 backdrop-blur-xl">{children}</div>

          <div className="mt-6 text-center text-sm text-white/60">{footer}</div>
          <div className="mt-6 flex items-center justify-center gap-2 text-xs text-white/40">
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 3 5 6v5c0 4.4 3 8.3 7 9.5 4-1.2 7-5.1 7-9.5V6l-7-3Zm-3 9 2 2 4-4" />
            </svg>
            Sessions are checked in the background
          </div>
        </div>

        <div className="relative mx-auto hidden aspect-square w-full max-w-[460px] md:block">
          <div className="absolute inset-[8%] rounded-full opacity-70 blur-2xl" style={{ background: 'radial-gradient(circle at 30% 30%,#ffc233,#ff5a1f 60%,transparent 72%)' }} />
          <img
            src={`${MEDIA}/card-hand.jpg`}
            alt=""
            className="absolute inset-0 h-full w-full rounded-[2rem] object-cover shadow-2xl shadow-black/60 ring-1 ring-white/10"
          />
        </div>
      </div>
    </div>
  );
}
