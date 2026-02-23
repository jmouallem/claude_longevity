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
import AdminStats from './pages/AdminStats';
import AdminUsers from './pages/AdminUsers';
import AdminSecurity from './pages/AdminSecurity';
import AdminFeedback from './pages/AdminFeedback';
import { apiClient } from './api/client';
import { useAuthStore } from './stores/authStore';

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
        <Route path="feedback" element={<Feedback />} />
        <Route path="settings" element={<Settings />} />
        <Route path="specialists" element={<Specialists />} />
        <Route path="*" element={<Navigate to="/chat" replace />} />
      </Routes>
      {showIntakePrompt && (
        <IntakePromptModal
          onDismiss={() => setShowIntakePrompt(false)}
          onCompleted={() => {
            setShowIntakePrompt(false);
            window.dispatchEvent(new Event('intake:check'));
          }}
        />
      )}
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route element={<ProtectedRoute />}>
        <Route path="/*" element={<AuthenticatedLayout />} />
      </Route>
      <Route path="/" element={<Navigate to="/chat" replace />} />
    </Routes>
  );
}
