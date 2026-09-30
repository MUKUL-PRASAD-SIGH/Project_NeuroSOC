import { useState, useEffect, FormEvent } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { loginBank, reportHoneypotHit } from '../../lib/portalApi';
import { useBehavioralTracker } from '../../hooks/useBehavioralTracker';
import { readPortalSession, writePortalSession } from '../../lib/portalSession';
import { AuthShell, ORANGE_GRADIENT, authButtonClass, authInputClass, authLabelClass } from '../components/AuthShell';

export default function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState(() => new URLSearchParams(window.location.search).get('email') ?? '');
  const [password, setPassword] = useState('');
  const [usernameConfirm, setUsernameConfirm] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const storedSession = readPortalSession();
  const registered = new URLSearchParams(window.location.search).get('registered') === '1';
  const tracker = useBehavioralTracker({
    userId: email || storedSession.email || 'anonymous',
    sessionId: storedSession.sessionId,
    page: '/login',
  });

  useEffect(() => {
    tracker.startTracking();
    return () => tracker.stopTracking();
  }, [tracker.startTracking, tracker.stopTracking]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      await tracker.flushEvents();

      if (usernameConfirm) {
        const honeypot = await reportHoneypotHit('login_form', email || 'anonymous', tracker.sessionId);
        writePortalSession({
          sessionId: honeypot.sessionId,
          email,
          userId: email || 'anonymous',
          verdict: honeypot.verdict,
          confidence: honeypot.confidence,
          sandbox: honeypot.sandbox || null,
          authenticated: Boolean(honeypot.sandbox?.active),
        });
        navigate(honeypot.sandbox?.active ? '/dashboard' : '/security-alert');
        return;
      }

      const loginData = await loginBank({
        email,
        password,
        sessionId: tracker.sessionId,
      });

      // The login endpoint already returns the verdict for this session. Reuse it
      // instead of issuing a second history lookup before completing sign-in.
      const verdict = loginData;

      const sandboxed = Boolean(loginData.sandbox?.active || verdict.sandbox?.active);

      writePortalSession({
        sessionId: loginData.sessionId,
        email,
        userId: loginData.user_id,
        displayName: loginData.displayName,
        // A diverted session is signed in to the decoy vault served by the same pages.
        authenticated: loginData.authenticated || sandboxed,
        verdict: verdict.verdict,
        confidence: verdict.confidence,
        sandbox: loginData.sandbox || verdict.sandbox || null,
        account: loginData.account,
      });

      if (!loginData.authenticated && !sandboxed) {
        setError(loginData.error || 'Invalid credentials. Please try again.');
        return;
      }

      navigate(loginData.next || '/dashboard');
    } catch (error) {
      console.error('Login error:', error);
      setError(error instanceof Error ? error.message : 'An error occurred. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell
      title="Welcome back"
      subtitle="Sign in to your NovaTrust account."
      footer={
        <>
          Don't have an account?{' '}
          <Link to="/signup" className="font-medium text-orange-400 hover:text-orange-300">Open an account</Link>
        </>
      }
    >
      {registered ? (
        <div className="mb-5 rounded-xl border border-emerald-400/30 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-300">
          Profile created. This is a demo bank, so sign in with a demo account.
        </div>
      ) : null}
      <form onSubmit={handleSubmit} className="space-y-5">
        <div>
          <label htmlFor="email" className={authLabelClass}>Email address</label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className={authInputClass}
            placeholder="you@example.com"
          />
        </div>

        {/* Honeypot field - hidden from real users */}
        <div style={{ opacity: 0, position: 'absolute', top: '-9999px', left: '-9999px' }} aria-hidden="true">
          <label htmlFor="username_confirm">Confirm Username</label>
          <input
            id="username_confirm"
            name="username_confirm"
            type="text"
            value={usernameConfirm}
            onChange={(e) => setUsernameConfirm(e.target.value)}
            tabIndex={-1}
            autoComplete="off"
          />
        </div>

        <div>
          <label htmlFor="password" className={authLabelClass}>Password</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className={authInputClass}
            placeholder="••••••••"
          />
        </div>

        <div className="flex items-center justify-between text-sm">
          <label className="flex items-center gap-2 text-white/60">
            <input type="checkbox" className="h-4 w-4 accent-orange-500" />
            Remember me
          </label>
          <a href="#" className="text-white/60 hover:text-white">Forgot password?</a>
        </div>

        <button type="submit" disabled={loading} className={authButtonClass} style={{ background: ORANGE_GRADIENT }}>
          {loading ? 'Signing in...' : 'Sign in'}
        </button>

        {error ? (
          <div role="alert" className="rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
            {error}
          </div>
        ) : null}
      </form>
    </AuthShell>
  );
}
