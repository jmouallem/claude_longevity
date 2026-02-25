import { useEffect, useState } from 'react';
import { useNavigate, useParams, Link } from 'react-router-dom';
import { apiClient } from '../api/client';
import { useAuthStore } from '../stores/authStore';

interface InviteStatus {
  valid: boolean;
  display_name?: string;
  username?: string;
  expires_at?: string;
  reason?: string;
}

export default function InviteRedeem() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const loadUser = useAuthStore((state) => state.loadUser);

  const [loading, setLoading] = useState(true);
  const [inviteStatus, setInviteStatus] = useState<InviteStatus | null>(null);
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!token) return;
    (async () => {
      try {
        const status = await apiClient.get<InviteStatus>(`/api/auth/invite/${token}`);
        setInviteStatus(status);
      } catch {
        setInviteStatus({ valid: false, reason: 'Failed to validate invite link' });
      } finally {
        setLoading(false);
      }
    })();
  }, [token]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (password.length < 6) {
      setError('Password must be at least 6 characters.');
      return;
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }

    setSubmitting(true);
    try {
      await apiClient.post(`/api/auth/invite/${token}`, { password });
      await loadUser();
      navigate('/goals', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to set password. The link may have expired.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-emerald-500">Longevity Coach</h1>
          <p className="text-sm text-slate-400 mt-1">Set up your account</p>
        </div>

        <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 space-y-5">
          {loading && (
            <div className="text-center py-6">
              <div className="w-6 h-6 border-2 border-emerald-500/40 border-t-emerald-500 rounded-full animate-spin mx-auto" />
              <p className="text-sm text-slate-400 mt-3">Validating invite...</p>
            </div>
          )}

          {!loading && inviteStatus && !inviteStatus.valid && (
            <div className="text-center space-y-4">
              <div className="w-12 h-12 mx-auto rounded-full bg-rose-900/30 border border-rose-700/30 flex items-center justify-center">
                <svg className="w-6 h-6 text-rose-400" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                  <circle cx="10" cy="10" r="9" />
                  <path d="M7 7l6 6M13 7l-6 6" />
                </svg>
              </div>
              <p className="text-slate-200 font-medium">Invite not valid</p>
              <p className="text-sm text-slate-400">{inviteStatus.reason}</p>
              <Link
                to="/login"
                className="inline-block px-4 py-2 text-sm bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg transition-colors"
              >
                Go to login
              </Link>
            </div>
          )}

          {!loading && inviteStatus && inviteStatus.valid && (
            <>
              <div className="text-center space-y-1">
                <p className="text-lg font-semibold text-slate-100">
                  Welcome, {inviteStatus.display_name}
                </p>
                <p className="text-sm text-slate-400">
                  Your account <span className="text-slate-300 font-medium">{inviteStatus.username}</span> is ready. Set a password to get started.
                </p>
              </div>

              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Password</label>
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="At least 6 characters"
                    required
                    minLength={6}
                    className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2.5 text-slate-100 text-sm focus:outline-none focus:border-emerald-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Confirm password</label>
                  <input
                    type="password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Enter password again"
                    required
                    minLength={6}
                    className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2.5 text-slate-100 text-sm focus:outline-none focus:border-emerald-500"
                  />
                </div>

                {error && (
                  <p className="text-sm text-rose-400">{error}</p>
                )}

                <button
                  type="submit"
                  disabled={submitting}
                  className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
                >
                  {submitting ? 'Setting up...' : 'Set password & sign in'}
                </button>
              </form>
            </>
          )}
        </div>

        <p className="text-center text-xs text-slate-500">
          Already have an account?{' '}
          <Link to="/login" className="text-emerald-400 hover:text-emerald-300">Sign in</Link>
        </p>
      </div>
    </div>
  );
}
