import { useEffect, useState } from 'react';
import { apiClient } from '../api/client';

interface AdminUser {
  id: number;
  username: string;
  display_name: string;
  role: string;
  ai_provider: string;
  reasoning_model: string | null;
  utility_model: string | null;
  deep_thinking_model: string | null;
  has_api_key: boolean;
  passkey_count: number;
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

interface ModelOption {
  id: string;
  name: string;
}

interface PresetOption {
  label: string;
  description: string;
  reasoning: string;
  utility: string;
  deep_thinking: string;
}

interface AdminModelOptionsResponse {
  provider: string;
  reasoning_models: ModelOption[];
  utility_models: ModelOption[];
  deep_thinking_models: ModelOption[];
  default_reasoning: string;
  default_utility: string;
  default_deep_thinking: string;
  presets: Record<string, PresetOption>;
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
  const [aiLoading, setAiLoading] = useState(false);
  const [selectedAiUserId, setSelectedAiUserId] = useState<number | null>(null);
  const [aiProvider, setAiProvider] = useState('anthropic');
  const [aiPreset, setAiPreset] = useState('');
  const [aiApiKey, setAiApiKey] = useState('');
  const [aiClearApiKey, setAiClearApiKey] = useState(false);
  const [aiReasoningModel, setAiReasoningModel] = useState('');
  const [aiUtilityModel, setAiUtilityModel] = useState('');
  const [aiDeepThinkingModel, setAiDeepThinkingModel] = useState('');
  const [modelOptions, setModelOptions] = useState<AdminModelOptionsResponse | null>(null);

  const loadModelOptions = async (
    providerValue: string,
    seed?: { reasoning: string; utility: string; deep: string },
  ) => {
    setAiLoading(true);
    try {
      const out = await apiClient.get<AdminModelOptionsResponse>(
        `/api/admin/model-options?provider=${encodeURIComponent(providerValue)}`
      );
      setModelOptions(out);
      const availableReasoning = new Set((out.reasoning_models || []).map((m) => m.id));
      const availableUtility = new Set((out.utility_models || []).map((m) => m.id));
      const availableDeep = new Set((out.deep_thinking_models || []).map((m) => m.id));

      const desiredReasoning = seed?.reasoning || aiReasoningModel;
      const desiredUtility = seed?.utility || aiUtilityModel;
      const desiredDeep = seed?.deep || aiDeepThinkingModel;

      setAiReasoningModel(
        desiredReasoning && availableReasoning.has(desiredReasoning) ? desiredReasoning : out.default_reasoning
      );
      setAiUtilityModel(
        desiredUtility && availableUtility.has(desiredUtility) ? desiredUtility : out.default_utility
      );
      setAiDeepThinkingModel(
        desiredDeep && availableDeep.has(desiredDeep) ? desiredDeep : out.default_deep_thinking
      );
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to load model options.');
    } finally {
      setAiLoading(false);
    }
  };

  const openAiSetup = async (u: AdminUser) => {
    setSelectedAiUserId(u.id);
    setSelectedUserId(null);
    setAiPreset('');
    setAiApiKey('');
    setAiClearApiKey(false);
    const providerValue = (u.ai_provider || 'anthropic').trim() || 'anthropic';
    setAiProvider(providerValue);
    await loadModelOptions(providerValue, {
      reasoning: (u.reasoning_model || '').trim(),
      utility: (u.utility_model || '').trim(),
      deep: (u.deep_thinking_model || '').trim(),
    });
  };

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

  const resetPasskeys = async (userId: number, username: string) => {
    const confirmed = window.confirm(`Clear all biometric passkeys for ${username}?`);
    if (!confirmed) return;
    setActionLoading(true);
    setMessage('');
    try {
      const result = await apiClient.post<{ status: string; deleted: number }>(`/api/admin/users/${userId}/reset-passkeys`, {});
      setMessage(`Removed ${result.deleted} passkey(s) for ${username}.`);
      await loadUsers();
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to reset passkeys.');
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

  const applyAiConfig = async () => {
    if (!selectedAiUserId) return;
    setActionLoading(true);
    setMessage('');
    try {
      await apiClient.put(`/api/admin/users/${selectedAiUserId}/ai-config`, {
        ai_provider: aiProvider,
        preset: aiPreset || undefined,
        api_key: aiApiKey.trim() || undefined,
        clear_api_key: aiClearApiKey,
        reasoning_model: aiReasoningModel || undefined,
        utility_model: aiUtilityModel || undefined,
        deep_thinking_model: aiDeepThinkingModel || undefined,
      });
      setMessage('AI configuration updated for user.');
      setAiApiKey('');
      setAiClearApiKey(false);
      await loadUsers();
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to update AI configuration.');
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
                      Provider: {u.ai_provider || 'anthropic'} | API key: {u.has_api_key ? 'set' : 'not set'} | Passkeys: {u.passkey_count} | Force password change: {u.force_password_change ? 'yes' : 'no'}
                      {u.created_at ? ` | Created ${new Date(u.created_at).toLocaleDateString()}` : ''}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => openAiSetup(u)}
                      disabled={actionLoading || aiLoading}
                      className="px-3 py-1.5 text-xs rounded-md border border-emerald-700/70 text-emerald-300 hover:bg-emerald-900/20 disabled:opacity-60"
                    >
                      AI Setup
                    </button>
                    <button
                      onClick={() => {
                        setSelectedUserId(u.id);
                        setSelectedAiUserId(null);
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
                      onClick={() => resetPasskeys(u.id, u.username)}
                      disabled={actionLoading}
                      className="px-3 py-1.5 text-xs rounded-md border border-amber-700/70 text-amber-300 hover:bg-amber-900/20 disabled:opacity-60"
                    >
                      Reset Passkeys
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

                {selectedAiUserId === u.id && (
                  <div className="mt-3 rounded-lg border border-slate-700 bg-slate-900/35 p-3 space-y-3">
                    <p className="text-xs text-slate-400">
                      Configure provider, API key, models, and preset for this user.
                    </p>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                      <label className="text-xs text-slate-400">
                        Provider
                        <select
                          value={aiProvider}
                          onChange={(e) => {
                            const next = e.target.value;
                            setAiProvider(next);
                            setAiPreset('');
                            void loadModelOptions(next);
                          }}
                          className="mt-1 w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-amber-500"
                        >
                          <option value="anthropic">Anthropic</option>
                          <option value="openai">OpenAI</option>
                          <option value="google">Google</option>
                        </select>
                      </label>
                      <label className="text-xs text-slate-400">
                        Preset
                        <select
                          value={aiPreset}
                          onChange={(e) => {
                            const next = e.target.value;
                            setAiPreset(next);
                            if (next && modelOptions?.presets?.[next]) {
                              const preset = modelOptions.presets[next];
                              setAiReasoningModel(preset.reasoning);
                              setAiUtilityModel(preset.utility);
                              setAiDeepThinkingModel(preset.deep_thinking);
                            }
                          }}
                          className="mt-1 w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-amber-500"
                        >
                          <option value="">Custom</option>
                          {Object.entries(modelOptions?.presets || {}).map(([key, preset]) => (
                            <option key={key} value={key}>{preset.label}</option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                      <label className="text-xs text-slate-400">
                        Reasoning Model
                        <select
                          value={aiReasoningModel}
                          onChange={(e) => setAiReasoningModel(e.target.value)}
                          className="mt-1 w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-amber-500"
                        >
                          {(modelOptions?.reasoning_models || []).map((m) => (
                            <option key={m.id} value={m.id}>{m.name}</option>
                          ))}
                        </select>
                      </label>
                      <label className="text-xs text-slate-400">
                        Utility Model
                        <select
                          value={aiUtilityModel}
                          onChange={(e) => setAiUtilityModel(e.target.value)}
                          className="mt-1 w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-amber-500"
                        >
                          {(modelOptions?.utility_models || []).map((m) => (
                            <option key={m.id} value={m.id}>{m.name}</option>
                          ))}
                        </select>
                      </label>
                      <label className="text-xs text-slate-400">
                        Deep-thinking Model
                        <select
                          value={aiDeepThinkingModel}
                          onChange={(e) => setAiDeepThinkingModel(e.target.value)}
                          className="mt-1 w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-amber-500"
                        >
                          {(modelOptions?.deep_thinking_models || []).map((m) => (
                            <option key={m.id} value={m.id}>{m.name}</option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <div className="flex flex-wrap gap-2 items-center">
                      <input
                        type="password"
                        value={aiApiKey}
                        onChange={(e) => setAiApiKey(e.target.value)}
                        placeholder="New API key (leave blank to keep existing)"
                        className="flex-1 min-w-[260px] bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-amber-500"
                      />
                      <label className="inline-flex items-center gap-2 text-xs text-slate-300">
                        <input
                          type="checkbox"
                          checked={aiClearApiKey}
                          onChange={(e) => setAiClearApiKey(e.target.checked)}
                          className="accent-rose-500"
                        />
                        Clear existing key
                      </label>
                    </div>

                    <div className="flex gap-2">
                      <button
                        onClick={applyAiConfig}
                        disabled={actionLoading || aiLoading}
                        className="px-3 py-2 text-sm rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-60"
                      >
                        Apply AI Config
                      </button>
                      <button
                        onClick={() => setSelectedAiUserId(null)}
                        className="px-3 py-2 text-sm rounded-lg border border-slate-600 text-slate-300 hover:bg-slate-700"
                      >
                        Cancel
                      </button>
                    </div>
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
