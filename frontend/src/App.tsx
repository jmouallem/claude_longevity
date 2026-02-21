import { useCallback, useEffect, useState } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import ProtectedRoute from './components/ProtectedRoute';
import Navbar from './components/Navbar';
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
import { apiClient } from './api/client';

interface IntakePromptStatus {
  should_prompt: boolean;
}

// Layout with Navbar for authenticated pages
function AuthenticatedLayout() {
  const [showIntakePrompt, setShowIntakePrompt] = useState(false);

  const checkIntakePrompt = useCallback(async () => {
    try {
      const status = await apiClient.get<IntakePromptStatus>('/api/intake/prompt-status');
      setShowIntakePrompt(Boolean(status.should_prompt));
    } catch {
      // Ignore prompt failures so normal navigation still works.
    }
  }, []);

  useEffect(() => {
    checkIntakePrompt();
  }, [checkIntakePrompt]);

  useEffect(() => {
    const onPromptCheck = () => {
      checkIntakePrompt();
    };
    window.addEventListener('intake:check', onPromptCheck);
    return () => window.removeEventListener('intake:check', onPromptCheck);
  }, [checkIntakePrompt]);

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
