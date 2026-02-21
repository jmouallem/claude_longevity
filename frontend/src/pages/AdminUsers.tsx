import { useEffect, useState } from 'react';
import { apiClient } from '../api/client';

interface AdminUser {
  id: number;
  username: string;
  display_name: string;
  role: string;
  has_api_key: boolean;
  force_password_change: boolean;
  created_at: string | null;
}

interface AdminUsersResponse {
  total: number;
  users: AdminUser[];
}

interface AdminDeleteUserResponse {
  status: string;
  removed_files: number;
}

export default function AdminUsers() {
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [newPassword, setNewPassword] = useState('');
  const [actionLoading, setActionLoading] = useState(false);

  const loadUsers = async (query?: string) => {
    setLoading(true);
    setError('');
    try {
      const q = encodeURIComponent((query ?? search).trim());
      const data = await apiClient.get<AdminUsersResponse>(`/api/admin/users?search=${q}&limit=200&offset=0&include_admins=false`);
      setUsers(data.users);
      setTotal(data.total);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load users.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadUsers('');
  }, []);

  const resetPassword = async () => {
    if (!selectedUserId) return;
    if (newPassword.length < 8) {
      setMessage('New password must be at least 8 characters.');
      return;
    }
    setActionLoading(true);
    setMessage('');
    try {
      await apiClient.post(`/api/admin/users/${selectedUserId}/reset-password`, { new_password: newPassword });
      setMessage('Password reset and user sessions invalidated.');
      setNewPassword('');
      setSelectedUserId(null);
      await loadUsers();
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to reset password.');
    } finally {
      setActionLoading(false);
    }
  };

  const resetData = async (userId: number, username: string) => {
    const confirmed = window.confirm(`Reset all data for ${username}? Password will be kept and sessions invalidated.`);
    if (!confirmed) return;
    setActionLoading(true);
    setMessage('');
    try {
      await apiClient.post(`/api/admin/users/${userId}/reset-data`, {});
      setMessage(`Data reset completed for ${username}.`);
      await loadUsers();
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to reset user data.');
    } finally {
      setActionLoading(false);
    }
  };

  const deleteUser = async (userId: number, username: string) => {
    const confirmed = window.confirm(
      `Delete user "${username}" permanently?\n\nThis removes profile, history, logs, messages, and uploaded files. This cannot be undone.`
    );
    if (!confirmed) return;

    setActionLoading(true);
    setMessage('');
    try {
      const result = await apiClient.delete<AdminDeleteUserResponse>(`/api/admin/users/${userId}`);
      setSelectedUserId((current) => (current === userId ? null : current));
      setNewPassword('');
      setMessage(`Deleted ${username}. Removed files: ${result.removed_files}.`);
      await loadUsers();
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to delete user.');
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-slate-100">User Administration</h1>
        <div className="flex gap-2">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search username or display name"
            className="w-72 bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-amber-500"
          />
          <button
            onClick={() => loadUsers(search)}
            className="px-3 py-2 text-sm border border-slate-600 rounded-lg text-slate-200 hover:bg-slate-700"
          >
            Search
          </button>
        </div>
      </div>

      {error && <p className="text-sm text-rose-400">{error}</p>}
      {message && <p className="text-sm text-emerald-400">{message}</p>}

      <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
        <p className="text-sm text-slate-400 mb-3">Total users: {total}</p>
        {loading ? (
          <p className="text-sm text-slate-400">Loading...</p>
        ) : users.length === 0 ? (
          <p className="text-sm text-slate-400">No users found.</p>
        ) : (
          <div className="space-y-2">
            {users.map((u) => (
              <div key={u.id} className="rounded-lg border border-slate-700 bg-slate-900/35 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="text-sm text-slate-100 font-medium">{u.display_name} ({u.username})</p>
                    <p className="text-xs text-slate-400 mt-1">
                      API key: {u.has_api_key ? 'set' : 'not set'} | Force password change: {u.force_password_change ? 'yes' : 'no'}
                      {u.created_at ? ` | Created ${new Date(u.created_at).toLocaleDateString()}` : ''}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => {
                        setSelectedUserId(u.id);
                        setNewPassword('');
                      }}
                      disabled={actionLoading}
                      className="px-3 py-1.5 text-xs rounded-md border border-slate-600 text-slate-200 hover:bg-slate-700 disabled:opacity-60"
                    >
                      Reset Password
                    </button>
                    <button
                      onClick={() => resetData(u.id, u.username)}
                      disabled={actionLoading}
                      className="px-3 py-1.5 text-xs rounded-md border border-rose-700/70 text-rose-300 hover:bg-rose-900/20 disabled:opacity-60"
                    >
                      Reset Data
                    </button>
                    <button
                      onClick={() => deleteUser(u.id, u.username)}
                      disabled={actionLoading}
                      className="px-3 py-1.5 text-xs rounded-md border border-rose-700 bg-rose-900/30 text-rose-200 hover:bg-rose-800/40 disabled:opacity-60"
                    >
                      Delete User
                    </button>
                  </div>
                </div>

                {selectedUserId === u.id && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <input
                      type="text"
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      placeholder="New password (min 8 chars)"
                      className="flex-1 min-w-[220px] bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-amber-500"
                    />
                    <button
                      onClick={resetPassword}
                      disabled={actionLoading}
                      className="px-3 py-2 text-sm rounded-lg bg-amber-600 hover:bg-amber-500 text-white disabled:opacity-60"
                    >
                      Confirm Reset
                    </button>
                    <button
                      onClick={() => setSelectedUserId(null)}
                      className="px-3 py-2 text-sm rounded-lg border border-slate-600 text-slate-300 hover:bg-slate-700"
                    >
                      Cancel
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
