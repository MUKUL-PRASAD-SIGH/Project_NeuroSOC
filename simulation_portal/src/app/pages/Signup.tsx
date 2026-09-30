import { FormEvent, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AuthShell, ORANGE_GRADIENT, authButtonClass, authInputClass, authLabelClass } from '../components/AuthShell';

// The demo bank has no account-creation backend: sign-up validates the form and
// hands the visitor to the sign-in page with their email filled in.
export default function Signup() {
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [email, setEmail] = useState(() => new URLSearchParams(window.location.search).get('email') ?? '');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    if (password !== confirm) {
      setError('Passwords do not match.');
      return;
    }
    navigate(`/login?email=${encodeURIComponent(email)}&registered=1`);
  };

  return (
    <AuthShell
      title="Open your account"
      subtitle="Create a NovaTrust profile in under a minute."
      footer={
        <>
          Already have an account?{' '}
          <Link to="/login" className="font-medium text-orange-400 hover:text-orange-300">Sign in</Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-5">
        <div>
          <label htmlFor="name" className={authLabelClass}>Full name</label>
          <input id="name" value={name} onChange={(e) => setName(e.target.value)} required className={authInputClass} placeholder="Jane Doe" autoComplete="name" />
        </div>
        <div>
          <label htmlFor="email" className={authLabelClass}>Email address</label>
          <input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required className={authInputClass} placeholder="you@example.com" autoComplete="email" />
        </div>
        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <label htmlFor="password" className={authLabelClass}>Password</label>
            <input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required className={authInputClass} placeholder="••••••••" autoComplete="new-password" />
          </div>
          <div>
            <label htmlFor="confirm" className={authLabelClass}>Confirm</label>
            <input id="confirm" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required className={authInputClass} placeholder="••••••••" autoComplete="new-password" />
          </div>
        </div>
        <button type="submit" className={authButtonClass} style={{ background: ORANGE_GRADIENT }}>Create account</button>
        {error ? (
          <div role="alert" className="rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">{error}</div>
        ) : null}
      </form>
    </AuthShell>
  );
}
