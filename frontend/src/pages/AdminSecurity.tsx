import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiClient } from '../api/client';
import { useAuthStore } from '../stores/authStore';

export default function AdminSecurity() {
  const navigate = useNavigate();
  const { user, loadUser, logout } = useAuthStore();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmNewPassword, setConfirmNewPassword] = useState('');
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  const changePassword = async () => {
    setMessage('');
    if (!currentPassword || !newPassword) {
      setMessage('Current and new password are required.');
      return;
    }
    if (newPassword.length < 8) {
      setMessage('New password must be at least 8 characters.');
      return;
    }
    if (newPassword !== confirmNewPassword) {
      setMessage('New password and confirmation do not match.');
      return;
    }

    setSaving(true);
    try {
      await apiClient.post('/api/admin/password/change', {
        current_password: currentPassword,
        new_password: newPassword,
      });
      await loadUser();
      setMessage('Password updated. For security, sign in again.');
      setTimeout(() => {
        logout();
        navigate('/login');
      }, 900);
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to update password.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto px-4 py-6 space-y-5">
      <h1 className="text-2xl font-bold text-slate-100">Admin Security</h1>
      {user?.force_password_change && (
        <div className="rounded-lg border border-amber-700/60 bg-amber-900/20 p-3">
          <p className="text-sm text-amber-200">Password change required before accessing other admin pages.</p>
        </div>
      )}

      <div className="bg-slate-800 rounded-xl p-6 border border-slate-700 space-y-4">
        <h2 className="text-lg font-semibold text-slate-100">Change Password</h2>
        <div className="space-y-3">
          <div>
            <label className="block text-sm text-slate-400 mb-1">Current Password</label>
            <input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-amber-500"
            />
          </div>
          <div>
            <label className="block text-sm text-slate-400 mb-1">New Password</label>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-amber-500"
            />
          </div>
          <div>
            <label className="block text-sm text-slate-400 mb-1">Confirm New Password</label>
            <input
              type="password"
              value={confirmNewPassword}
              onChange={(e) => setConfirmNewPassword(e.target.value)}
              className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-amber-500"
            />
          </div>
        </div>
        {message && <p className="text-sm text-slate-300">{message}</p>}
        <button
          onClick={changePassword}
          disabled={saving}
          className="px-4 py-2 bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg"
        >
          {saving ? 'Updating...' : 'Update Password'}
        </button>
      </div>
    </div>
  );
}
