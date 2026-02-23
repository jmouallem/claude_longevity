import { useCallback, useEffect, useState } from 'react';
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom';
import ProtectedRoute from './components/ProtectedRoute';
import Navbar from './components/Navbar';
import AdminNavbar from './components/AdminNavbar';
import IntakePromptModal from './components/IntakePromptModal';
import Login from './pages/Login';
import Register from './pages/Register';
import Chat from './pages/Chat';
import Dashboard from './pages/Dashboard';
import History from './pages/History';
import Settings from './pages/Settings';
import Specialists from './pages/Specialists';
import Feedback from './pages/Feedback';
import Menu from './pages/Menu';
import Plan from './pages/Plan';
import AdminStats from './pages/AdminStats';
import AdminUsers from './pages/AdminUsers';
import AdminSecurity from './pages/AdminSecurity';
import AdminFeedback from './pages/AdminFeedback';
import { apiClient } from './api/client';
import { useAuthStore } from './stores/authStore';
import { PWA_UPDATE_EVENT, type PwaUpdateDetail } from './pwa';

interface IntakePromptStatus {
  should_prompt: boolean;
  has_api_key?: boolean;
  models_ready?: boolean;
  reason?: string;
}

// Layout with Navbar for authenticated pages
function AuthenticatedLayout() {
  const user = useAuthStore((state) => state.user);
  const [showIntakePrompt, setShowIntakePrompt] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  const checkIntakePrompt = useCallback(async () => {
    try {
      const status = await apiClient.get<IntakePromptStatus>('/api/intake/prompt-status');
      setShowIntakePrompt(Boolean(status.should_prompt));
      const missingSetup =
        status.reason === 'missing_api_key' ||
        status.reason === 'missing_models' ||
        status.has_api_key === false ||
        status.models_ready === false;
      if (missingSetup && !location.pathname.startsWith('/settings')) {
        navigate('/settings', { replace: true });
      }
    } catch {
      // Ignore prompt failures so normal navigation still works.
    }
  }, [location.pathname, navigate]);

  useEffect(() => {
    if (user?.role === 'admin') {
      return;
    }
    checkIntakePrompt();
  }, [checkIntakePrompt, user?.role]);

  useEffect(() => {
    if (user?.role === 'admin') {
      return;
    }
    const onPromptCheck = () => {
      checkIntakePrompt();
    };
    window.addEventListener('intake:check', onPromptCheck);
    return () => window.removeEventListener('intake:check', onPromptCheck);
  }, [checkIntakePrompt, user?.role]);

  if (user?.role === 'admin') {
    const forcePasswordChange = Boolean(user.force_password_change);
    return (
      <div className="min-h-screen bg-slate-900">
        <AdminNavbar />
        <Routes>
          <Route path="admin/stats" element={forcePasswordChange ? <Navigate to="/admin/security" replace /> : <AdminStats />} />
          <Route path="admin/users" element={forcePasswordChange ? <Navigate to="/admin/security" replace /> : <AdminUsers />} />
          <Route path="admin/feedback" element={forcePasswordChange ? <Navigate to="/admin/security" replace /> : <AdminFeedback />} />
          <Route path="admin/security" element={<AdminSecurity />} />
          <Route path="*" element={<Navigate to={forcePasswordChange ? "/admin/security" : "/admin/stats"} replace />} />
        </Routes>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900">
      <Navbar />
      <Routes>
        <Route path="chat" element={<Chat />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="history" element={<History />} />
        <Route path="menu" element={<Menu />} />
        <Route path="plan" element={<Plan />} />
        <Route path="feedback" element={<Feedback />} />
        <Route path="settings" element={<Settings />} />
        <Route path="specialists" element={<Specialists />} />
        <Route path="*" element={<Navigate to="/chat" replace />} />
      </Routes>
      {showIntakePrompt && (
        <IntakePromptModal
          onDismiss={() => setShowIntakePrompt(false)}
          onCompleted={(nextRoute) => {
            setShowIntakePrompt(false);
            window.dispatchEvent(new Event('intake:check'));
            navigate(nextRoute || '/plan?onboarding=1');
          }}
        />
      )}
    </div>
  );
}

export default function App() {
  const [pendingUpdate, setPendingUpdate] = useState<ServiceWorkerRegistration | null>(null);

  useEffect(() => {
    const handlePwaUpdate = (event: Event) => {
      const detail = (event as CustomEvent<PwaUpdateDetail>).detail;
      if (!detail?.registration) return;
      setPendingUpdate((prev) => prev ?? detail.registration);
    };

    window.addEventListener(PWA_UPDATE_EVENT, handlePwaUpdate);
    return () => {
      window.removeEventListener(PWA_UPDATE_EVENT, handlePwaUpdate);
    };
  }, []);

  const applyUpdate = () => {
    pendingUpdate?.waiting?.postMessage({ type: 'SKIP_WAITING' });
    window.location.reload();
  };

  return (
    <>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/*" element={<AuthenticatedLayout />} />
        </Route>
        <Route path="/" element={<Navigate to="/chat" replace />} />
      </Routes>

      {pendingUpdate && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-[90] w-[calc(100%-1.5rem)] max-w-md rounded-lg border border-emerald-500/40 bg-slate-900/95 px-3 py-2 shadow-xl">
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-slate-200">Update available. Reload to get the latest version.</p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setPendingUpdate(null)}
                className="px-2 py-1 text-xs rounded-md border border-slate-600 text-slate-300 hover:bg-slate-800"
              >
                Later
              </button>
              <button
                type="button"
                onClick={applyUpdate}
                className="px-2.5 py-1 text-xs rounded-md bg-emerald-600 text-white hover:bg-emerald-500"
              >
                Reload
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
