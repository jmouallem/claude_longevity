import { useCallback, useEffect, useState } from 'react';
import { apiClient } from '../api/client';

type FeedbackType = 'bug' | 'enhancement' | 'missing' | 'other';
type FeedbackSource = 'user' | 'agent';

interface AdminFeedbackEntry {
  id: number;
  feedback_type: FeedbackType | string;
  title: string;
  details?: string | null;
  source: FeedbackSource | string;
  specialist_id?: string | null;
  specialist_name?: string | null;
  created_by_user_id?: number | null;
  created_by_username?: string | null;
  created_at?: string | null;
}

interface ClearResult {
  status: string;
  deleted: number;
}

const TYPE_OPTIONS: Array<{ value: ''; label: string } | { value: FeedbackType; label: string }> = [
  { value: '', label: 'All types' },
  { value: 'bug', label: 'bug' },
  { value: 'enhancement', label: 'enhancement' },
  { value: 'missing', label: 'missing' },
  { value: 'other', label: 'other' },
];

const SOURCE_OPTIONS: Array<{ value: ''; label: string } | { value: FeedbackSource; label: string }> = [
  { value: '', label: 'All sources' },
  { value: 'user', label: 'user' },
  { value: 'agent', label: 'agent' },
];

function formatTime(iso?: string | null): string {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function toQuery(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined) return;
    const v = String(value).trim();
    if (!v) return;
    sp.set(key, v);
  });
  return sp.toString();
}

export default function AdminFeedback() {
  const [entries, setEntries] = useState<AdminFeedbackEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');

  const [typeFilter, setTypeFilter] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  const [specialistFilter, setSpecialistFilter] = useState('');
  const [userFilter, setUserFilter] = useState('');
  const [appliedQuery, setAppliedQuery] = useState(() => toQuery({ limit: 500 }));

  const buildQuery = useCallback(
    (overrides?: { feedback_type?: string; source?: string; specialist_id?: string; user?: string }) =>
      toQuery({
        feedback_type: overrides?.feedback_type ?? typeFilter,
        source: overrides?.source ?? sourceFilter,
        specialist_id: overrides?.specialist_id ?? specialistFilter,
        user: overrides?.user ?? userFilter,
        limit: 500,
      }),
    [typeFilter, sourceFilter, specialistFilter, userFilter]
  );

  const load = useCallback(async () => {
    setLoading(true);
    setMessage('');
    try {
      const rows = await apiClient.get<AdminFeedbackEntry[]>(`/api/admin/feedback?${appliedQuery}`);
      setEntries(rows);
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to load feedback');
    } finally {
      setLoading(false);
    }
  }, [appliedQuery]);

  useEffect(() => {
    load();
  }, [load]);

  const resetFilters = () => {
    const resetQuery = toQuery({ limit: 500 });
    setTypeFilter('');
    setSourceFilter('');
    setSpecialistFilter('');
    setUserFilter('');
    setAppliedQuery(resetQuery);
    if (appliedQuery === resetQuery) {
      void load();
    }
  };

  const removeOne = async (id: number) => {
    setMessage('');
    try {
      await apiClient.delete(`/api/admin/feedback/${id}`);
      setEntries((prev) => prev.filter((r) => r.id !== id));
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to delete feedback entry');
    }
  };

  const exportCsv = async () => {
    setMessage('');
    try {
      const token = apiClient.getToken();
      const res = await fetch(`/api/admin/feedback/export?${appliedQuery}`, {
        method: 'GET',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) {
        throw new Error(`Export failed: ${res.status}`);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'feedback_export.csv';
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to export CSV');
    }
  };

  const clearFiltered = async () => {
    const confirmed = window.confirm('Clear feedback entries matching current filters? This cannot be undone.');
    if (!confirmed) return;

    setMessage('');
    try {
      const result = await apiClient.delete<ClearResult>(`/api/admin/feedback?${appliedQuery}`);
      setMessage(`Cleared ${result.deleted} feedback entries.`);
      await load();
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to clear feedback');
    }
  };

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Feedback Administration</h1>
          <p className="text-sm text-slate-400">Global feedback from all users and agent self-reflection.</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={exportCsv}
            className="px-3 py-2 text-sm rounded-lg border border-slate-600 bg-slate-700 hover:bg-slate-600 text-slate-100"
          >
            Export Filtered CSV
          </button>
          <button
            onClick={clearFiltered}
            className="px-3 py-2 text-sm rounded-lg border border-rose-700/70 bg-rose-900/30 hover:bg-rose-900/50 text-rose-200"
          >
            Clear Filtered
          </button>
        </div>
      </div>

      <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 space-y-3">
        <h2 className="text-lg font-semibold text-slate-100">Filters</h2>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <div>
            <label className="block text-xs text-slate-400 mb-1">Type</label>
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm"
            >
              {TYPE_OPTIONS.map((opt) => (
                <option key={opt.value || 'all'} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">Source</label>
            <select
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value)}
              className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm"
            >
              {SOURCE_OPTIONS.map((opt) => (
                <option key={opt.value || 'all'} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">Specialist ID</label>
            <input
              value={specialistFilter}
              onChange={(e) => setSpecialistFilter(e.target.value)}
              placeholder="e.g. nutritionist"
              className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">User</label>
            <input
              value={userFilter}
              onChange={(e) => setUserFilter(e.target.value)}
              placeholder="username or display name"
              className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm"
            />
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              const nextQuery = buildQuery();
              setAppliedQuery(nextQuery);
              if (nextQuery === appliedQuery) {
                void load();
              }
            }}
            className="px-3 py-2 text-sm rounded-lg border border-slate-600 text-slate-200 hover:bg-slate-700"
          >
            Apply Filters
          </button>
          <button
            onClick={resetFilters}
            className="px-3 py-2 text-sm rounded-lg border border-slate-600 text-slate-300 hover:bg-slate-700"
          >
            Reset
          </button>
        </div>
      </div>

      {message && <p className="text-sm text-emerald-300">{message}</p>}

      <div className="bg-slate-800 rounded-xl border border-slate-700">
        <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-100">Feedback</h2>
          <span className="text-xs text-slate-400">{entries.length} entries</span>
        </div>
        <div className="divide-y divide-slate-700">
          {loading ? (
            <div className="px-4 py-6 text-sm text-slate-400">Loading...</div>
          ) : entries.length === 0 ? (
            <div className="px-4 py-6 text-sm text-slate-400">No feedback matched the filters.</div>
          ) : (
            entries.map((item) => (
              <div key={item.id} className="px-4 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-[11px] uppercase tracking-wide px-2 py-0.5 rounded-full bg-slate-700 text-slate-300 border border-slate-600">
                        {item.feedback_type}
                      </span>
                      <span className={`text-[11px] uppercase tracking-wide px-2 py-0.5 rounded-full border ${
                        item.source === 'agent'
                          ? 'bg-violet-900/30 text-violet-300 border-violet-700/60'
                          : 'bg-emerald-900/30 text-emerald-300 border-emerald-700/60'
                      }`}>
                        {item.source}
                      </span>
                      {item.specialist_name && (
                        <span className="text-[11px] px-2 py-0.5 rounded-full bg-sky-900/30 text-sky-300 border border-sky-700/60">
                          {item.specialist_name}
                        </span>
                      )}
                    </div>
                    <p className="text-slate-100 font-medium">{item.title}</p>
                    {item.details && <p className="text-sm text-slate-300 mt-1 whitespace-pre-wrap">{item.details}</p>}
                    <p className="text-[11px] text-slate-500 mt-2">
                      {formatTime(item.created_at)} | by {item.created_by_username || `user:${item.created_by_user_id ?? '-'}`}
                    </p>
                  </div>
                  <button
                    onClick={() => removeOne(item.id)}
                    className="text-sm text-slate-400 hover:text-rose-300"
                    title="Delete entry"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
