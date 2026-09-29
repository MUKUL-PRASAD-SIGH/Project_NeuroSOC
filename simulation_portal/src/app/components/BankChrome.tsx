import { Link } from 'react-router-dom';

export const BANK_NAVY = '#0b2545';

export function BankHeader({ showSignIn = true }: { showSignIn?: boolean }) {
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <Link to="/" className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-md bg-[#0b2545] text-sm font-semibold text-white">
            NT
          </span>
          <span className="text-base font-semibold tracking-tight text-[#0b2545]">NovaTrust</span>
        </Link>

        <nav className="hidden items-center gap-7 text-sm text-slate-600 md:flex">
          {['Personal', 'Business', 'Savings', 'Help'].map((item) => (
            <a key={item} href="#" className="transition-colors hover:text-[#0b2545]">
              {item}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          {showSignIn ? (
            <Link
              to="/login"
              className="rounded-md bg-[#0b2545] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[#13315c]"
            >
              Sign in
            </Link>
          ) : null}
        </div>
      </div>
    </header>
  );
}

export function BankFooter() {
  return (
    <footer className="border-t border-slate-200">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 px-6 py-8 text-xs text-slate-500 md:flex-row md:items-center md:justify-between">
        <p>© 2026 NovaTrust Bank. All rights reserved.</p>
        <div className="flex gap-5">
          <a href="#" className="hover:text-slate-700">Privacy</a>
          <a href="#" className="hover:text-slate-700">Terms</a>
          <a href="#" className="hover:text-slate-700">Security</a>
        </div>
      </div>
    </footer>
  );
}
