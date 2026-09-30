import { useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { clearPortalSession, readPortalSession, setDebugToken } from '../../lib/portalSession';
import { useBehavioralTracker } from '../../hooks/useBehavioralTracker';
import { getMockDashboardData } from '../../lib/portalMock';

const CANARY_TOKEN = 'NT_CANARY_7f8e9d2a1b3c4e5f6g7h8i9j0k';
const INTERNAL_EXPORT_ENDPOINT = '/api/internal/user-export';

const GRADIENT = 'linear-gradient(135deg,#ff8a1f,#ff4d2e)';
const tabular = { fontVariantNumeric: 'tabular-nums' as const };
const money = (value: number) =>
  value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const ACTIONS = [
  { to: '/transfer', title: 'Transfer money', desc: 'Send to another account', path: 'M8 7h12m0 0-4-4m4 4-4 4m0 6H4m0 0 4 4m-4-4 4-4' },
  { to: null, title: 'Cards', desc: 'Manage debit and credit cards', path: 'M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 0 0 3-3V8a3 3 0 0 0-3-3H6a3 3 0 0 0-3 3v8a3 3 0 0 0 3 3Z' },
  { to: null, title: 'Statements', desc: 'View account statements', path: 'M9 12h6m-6 4h6m2 5H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5.586a1 1 0 0 1 .707.293l5.414 5.414a1 1 0 0 1 .293.707V19a2 2 0 0 1-2 2Z' },
  { to: null, title: 'Settings', desc: 'Manage your account', path: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1l2-1.6-2-3.4-2.4 1a7.5 7.5 0 0 0-1.7-1L15 3h-4l-.4 3a7.5 7.5 0 0 0-1.7 1l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2l-2 1.6 2 3.4 2.4-1a7.5 7.5 0 0 0 1.7 1l.4 3h4l.4-3a7.5 7.5 0 0 0 1.7-1l2.4 1 2-3.4-2-1.6c.1-.3.1-.7.1-1Z' },
];

const actionClass =
  'block w-full rounded-2xl border border-white/10 bg-white/[0.04] p-5 text-left transition-colors hover:bg-white/[0.08]';

function ActionBody({ action }: { action: (typeof ACTIONS)[number] }) {
  return (
    <>
      <span className="flex h-11 w-11 items-center justify-center rounded-xl text-white" style={{ background: GRADIENT }}>
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d={action.path} />
        </svg>
      </span>
      <h3 className="mt-4 text-sm font-semibold text-white">{action.title}</h3>
      <p className="mt-1 text-xs leading-relaxed text-white/50">{action.desc}</p>
    </>
  );
}

function useCountUp(target: number, durationMs = 1400) {
  const [value, setValue] = useState(0);
  useEffect(() => {
    let frame = 0;
    const started = performance.now();
    const tick = (now: number) => {
      const progress = Math.min(1, (now - started) / durationMs);
      setValue(target * (1 - Math.pow(1 - progress, 3)));
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, durationMs]);
  return value;
}

export default function Dashboard() {
  const navigate = useNavigate();
  const session = readPortalSession();
  const tracker = useBehavioralTracker({
    userId: session.userId || session.email || 'anonymous',
    sessionId: session.sessionId,
    page: '/dashboard',
  });
  const dashboardData = getMockDashboardData(session.userId || session.email);
  const displayName = session.displayName || dashboardData.displayName;
  const balance = session.account?.balance ?? dashboardData.account.balance;
  const accountMasked = session.account?.accountMasked || dashboardData.account.accountMasked;
  const transactions = [
    ...recentTransfers.map((transfer) => ({
      id: transfer.id,
      date: transfer.date,
      description: transfer.description,
      amount: -transfer.amount,
      type: 'debit',
    })),
    ...dashboardData.transactions.map((transaction) => ({
      id: transaction.id,
      date: transaction.date,
      description: transaction.merchant,
      amount: transaction.amount,
      type: transaction.type === 'CREDIT' ? 'credit' : 'debit',
    })),
  ];
  const totalIn = transactions.filter((t) => t.type === 'credit').reduce((sum, t) => sum + Math.abs(t.amount), 0);
  const totalOut = transactions.filter((t) => t.type !== 'credit').reduce((sum, t) => sum + Math.abs(t.amount), 0);

  useEffect(() => {
    if (!session.userId || !session.authenticated) {
      navigate('/login', { replace: true });
      return;
    }

    if (session.sandbox?.active || session.verdict === 'HACKER') {
      navigate('/security-alert', { replace: true });
      return;
    }

    setDebugToken(CANARY_TOKEN);
    tracker.startTracking();

    return () => {
      tracker.stopTracking();
    };
  }, [
    navigate,
    session.authenticated,
    session.sandbox?.active,
    session.userId,
    session.verdict,
    tracker.startTracking,
    tracker.stopTracking,
  ]);

  const handleLogout = () => {
    clearPortalSession();
    navigate('/');
  };

  return (
    <div className="min-h-screen bg-[#07080d] text-white antialiased" style={{ fontFamily: 'Inter, system-ui, sans-serif' }}>
      {/* Hidden canary token in HTML comment */}
      {/* ref: NT_CANARY_7f8e9d2a1b3c4e5f6g7h8i9j0k */}
      <div hidden aria-hidden="true" data-export-endpoint={INTERNAL_EXPORT_ENDPOINT} />
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(50%_40%_at_85%_0%,rgba(255,110,40,.18),transparent_70%)]" />

      <header className="relative z-10">
        <div className="mx-auto mt-4 flex h-14 max-w-6xl items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-5 backdrop-blur-md">
          <Link to="/" className="flex items-center gap-2.5">
            <img src={`${import.meta.env.BASE_URL}logo.png`} alt="" className="h-8 w-8 rounded-lg" />
            <span className="text-base font-semibold tracking-tight">NovaTrust</span>
          </Link>
          <nav className="flex items-center gap-1 text-sm text-white/70">
            <Link to="/transfer" className="rounded-lg px-3 py-2 transition-colors hover:bg-white/10 hover:text-white">Transfer</Link>
            <button onClick={handleLogout} className="rounded-lg bg-white/10 px-4 py-2 font-medium text-white transition-colors hover:bg-white/20">
              Sign out
            </button>
          </nav>
        </div>
      </header>

      <main className="relative z-10 mx-auto max-w-6xl px-6 py-10">
        <motion.div variants={rise} initial="hidden" animate="show" custom={0}>
          <p className="text-sm text-white/50">Here's your account summary</p>
          <h2 className="mt-1 text-3xl font-semibold tracking-tight md:text-4xl">Welcome back, {displayName.split(' ')[0]}</h2>
        </motion.div>

        <div className="mt-8 grid gap-5 lg:grid-cols-[1.4fr_1fr]">
          <motion.section
            className="relative overflow-hidden rounded-3xl border border-white/10 p-8"
            style={{ background: 'linear-gradient(135deg,rgba(255,138,31,.35),rgba(255,77,46,.12) 45%,rgba(255,255,255,.04))' }}
            variants={rise}
            initial="hidden"
            animate="show"
            custom={1}
          >
            <div className="flex items-start justify-between">
              <div>
                <p className="text-sm text-white/80">Checking account</p>
                <p className="mt-1 text-xs text-white/50" style={tabular}>{accountMasked}</p>
              </div>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-400/10 px-2.5 py-0.5 text-xs font-medium text-emerald-300">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                Protected
              </span>
            </div>
            <p className="mt-10 text-sm text-white/60">Available balance</p>
            <p className="mt-1 text-5xl font-semibold tracking-tight md:text-6xl" style={tabular}>${money(animatedBalance)}</p>
            <div className="mt-8 grid grid-cols-2 gap-4 border-t border-white/10 pt-5 text-sm">
              <div>
                <p className="text-white/50">Money in</p>
                <p className="mt-1 font-medium text-emerald-300" style={tabular}>+${money(totalIn)}</p>
              </div>
              <div>
                <p className="text-white/50">Money out</p>
                <p className="mt-1 font-medium text-white" style={tabular}>-${money(totalOut)}</p>
              </div>
            </div>
          </motion.section>

          <motion.div className="grid grid-cols-2 gap-4" variants={rise} initial="hidden" animate="show" custom={2}>
            {ACTIONS.map((action) =>
              action.to ? (
                <Link key={action.title} to={action.to} className={actionClass}>
                  <ActionBody action={action} />
                </Link>
              ) : (
                <button key={action.title} type="button" className={actionClass}>
                  <ActionBody action={action} />
                </button>
              ),
            )}
          </motion.div>
        </div>

        <motion.section
          className="mt-5 rounded-3xl border border-white/10 bg-white/[0.04]"
          variants={rise}
          initial="hidden"
          animate="show"
          custom={3}
        >
          <div className="flex items-center justify-between border-b border-white/10 px-6 py-5">
            <h3 className="text-lg font-semibold tracking-tight">Recent transactions</h3>
            <span className="text-xs text-white/40">{transactions.length} items</span>
          </div>
          <div className="divide-y divide-white/10">
            {transactions.map((transaction, index) => {
              const credit = transaction.type === 'credit';
              return (
                <motion.div
                  key={transaction.id}
                  className="flex items-center justify-between px-6 py-4 transition-colors hover:bg-white/[0.04]"
                  variants={rise}
                  initial="hidden"
                  animate="show"
                  custom={4 + index}
                >
                  <div className="flex items-center gap-4">
                    <span className={`flex h-10 w-10 items-center justify-center rounded-full ${credit ? 'bg-emerald-400/10 text-emerald-300' : 'bg-white/10 text-white/70'}`}>
                      <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden="true">
                        <path d={credit ? 'M12 5v14m7-7H5' : 'M5 12h14'} />
                      </svg>
                    </span>
                    <div>
                      <p className="text-sm font-medium text-white">{transaction.description}</p>
                      <p className="text-xs text-white/40">{transaction.date}</p>
                    </div>
                  </div>
                  <p className={`text-sm font-semibold ${credit ? 'text-emerald-300' : 'text-white'}`} style={tabular}>
                    {credit ? '+' : '-'}${money(Math.abs(transaction.amount))}
                  </p>
                </motion.div>
              );
            })}
          </div>
        </motion.section>
      </main>
    </div>
  );
}
