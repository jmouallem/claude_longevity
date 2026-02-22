import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { apiClient } from '../api/client';
import { useAuthStore } from '../stores/authStore';
import { APP_NAME } from '../constants/branding';
import { isWebAuthnSupported } from '../utils/webauthn';

export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [passkeyEnabled, setPasskeyEnabled] = useState(false);
  const [passkeyStatusLoading, setPasskeyStatusLoading] = useState(true);
  const { login, loginWithPasskey, loading, error, clearError } = useAuthStore();
  const navigate = useNavigate();

  useEffect(() => {
    const loadStatus = async () => {
      if (!isWebAuthnSupported()) {
        setPasskeyEnabled(false);
        setPasskeyStatusLoading(false);
        return;
      }
      try {
        const status = await apiClient.get<{ enabled: boolean }>('/api/auth/passkey/status');
        setPasskeyEnabled(Boolean(status.enabled));
      } catch {
        setPasskeyEnabled(false);
      } finally {
        setPasskeyStatusLoading(false);
      }
    };
    loadStatus();
  }, []);

  const navigateByRole = () => {
    const loggedInUser = useAuthStore.getState().user;
    if (loggedInUser?.role === 'admin') {
      navigate(loggedInUser.force_password_change ? '/admin/security' : '/admin/stats');
      return;
    }
    navigate('/chat');
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await login(username, password);
      navigateByRole();
    } catch {
      // error is set in store
    }
  };

  const handlePasskey = async () => {
    try {
      await loginWithPasskey(username || undefined);
      navigateByRole();
    } catch {
      // error is set in store
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-900 px-4">
      <div className="w-full max-w-md">
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-emerald-500">{APP_NAME}</h1>
          <p className="mt-2 text-slate-400">Sign in to your account</p>
        </div>

        {/* Card */}
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-8 shadow-xl">
          {error && (
            <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
              {error}
            </div>
          )}
          {!passkeyStatusLoading && passkeyEnabled && (
            <div className="space-y-4 mb-5">
              <button
                type="button"
                onClick={handlePasskey}
                disabled={loading}
                className="w-full py-2.5 px-4 bg-emerald-600 hover:bg-emerald-500 disabled:bg-emerald-600/50 disabled:cursor-not-allowed text-white font-medium rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2 focus:ring-offset-slate-800"
              >
                {loading ? 'Starting...' : 'Sign In with Biometrics'}
              </button>
              <div className="flex items-center gap-3">
                <div className="h-px bg-slate-700 flex-1" />
                <span className="text-xs uppercase tracking-wide text-slate-500">or password</span>
                <div className="h-px bg-slate-700 flex-1" />
              </div>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label htmlFor="username" className="block text-sm font-medium text-slate-300 mb-1.5">
                Username
              </label>
              <input
                id="username"
                type="text"
                value={username}
                onChange={(e) => { setUsername(e.target.value); clearError(); }}
                required
                className="w-full px-3 py-2.5 bg-slate-700 border border-slate-600 rounded-lg text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent transition-colors"
                placeholder="Enter your username"
              />
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-slate-300 mb-1.5">
                Password
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => { setPassword(e.target.value); clearError(); }}
                required
                className="w-full px-3 py-2.5 bg-slate-700 border border-slate-600 rounded-lg text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent transition-colors"
                placeholder="Enter your password"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 px-4 bg-emerald-600 hover:bg-emerald-500 disabled:bg-emerald-600/50 disabled:cursor-not-allowed text-white font-medium rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2 focus:ring-offset-slate-800"
            >
              {loading ? 'Signing in...' : 'Sign In'}
            </button>
          </form>

          <p className="mt-6 text-center text-sm text-slate-400">
            Don't have an account?{' '}
            <Link to="/register" className="text-emerald-400 hover:text-emerald-300 font-medium transition-colors">
              Create one
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
