import { useEffect, useState } from 'react';
import { apiClient } from '../api/client';

interface AdminStats {
  total_users: number;
  total_admins: number;
  active_users_7d: number;
  active_users_30d: number;
  total_messages: number;
  total_usage_requests: number;
  total_tokens_in: number;
  total_tokens_out: number;
  estimated_cost_usd: number;
  analysis_runs: number;
  analysis_proposals: number;
}

interface AuditRow {
  id: number;
  action: string;
  success: boolean;
  created_at: string | null;
  admin_username: string;
  target_username?: string | null;
}

export default function AdminStats() {
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const [overview, logs] = await Promise.all([
        apiClient.get<AdminStats>('/api/admin/stats/overview'),
        apiClient.get<AuditRow[]>('/api/admin/audit?limit=50'),
      ]);
      setStats(overview);
      setAudit(logs);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load admin stats.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-100">Admin Stats</h1>
        <button
          onClick={load}
          className="px-3 py-2 text-sm border border-slate-600 rounded-lg text-slate-200 hover:bg-slate-700"
        >
          Refresh
        </button>
      </div>

      {error && <p className="text-sm text-rose-400">{error}</p>}

      {loading && <p className="text-sm text-slate-400">Loading...</p>}

      {!loading && stats && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <StatCard label="Users" value={`${stats.total_users}`} sub={`${stats.total_admins} admin`} />
            <StatCard label="Active Users" value={`${stats.active_users_7d}`} sub={`7d (${stats.active_users_30d} in 30d)`} />
            <StatCard label="Messages" value={`${stats.total_messages}`} sub="All user messages" />
            <StatCard label="Usage Requests" value={`${stats.total_usage_requests}`} sub="Tracked utility requests" />
            <StatCard label="Tokens" value={`${stats.total_tokens_in.toLocaleString()} in`} sub={`${stats.total_tokens_out.toLocaleString()} out`} />
            <StatCard label="Estimated Cost" value={`$${stats.estimated_cost_usd.toFixed(4)}`} sub="All users" />
            <StatCard label="Analysis Runs" value={`${stats.analysis_runs}`} sub="Longitudinal runs" />
            <StatCard label="Proposals" value={`${stats.analysis_proposals}`} sub="Generated proposals" />
          </div>

          <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 space-y-3">
            <h2 className="text-lg font-semibold text-slate-100">Admin Audit Log</h2>
            {audit.length === 0 ? (
              <p className="text-sm text-slate-400">No audit entries yet.</p>
            ) : (
              <div className="space-y-2">
                {audit.map((row) => (
                  <div key={row.id} className="rounded-lg bg-slate-900/40 border border-slate-700 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm text-slate-100 font-medium">{row.action}</p>
                      <span className={`text-xs px-2 py-0.5 rounded-full ${row.success ? 'bg-emerald-900/50 text-emerald-300' : 'bg-rose-900/50 text-rose-300'}`}>
                        {row.success ? 'success' : 'failed'}
                      </span>
                    </div>
                    <p className="text-xs text-slate-400 mt-1">
                      Admin: {row.admin_username}
                      {row.target_username ? ` | Target: ${row.target_username}` : ''}
                      {row.created_at ? ` | ${new Date(row.created_at).toLocaleString()}` : ''}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function StatCard({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
      <p className="text-sm text-slate-400">{label}</p>
      <p className="text-2xl font-semibold text-slate-100 mt-1">{value}</p>
      <p className="text-xs text-slate-500 mt-1">{sub}</p>
    </div>
  );
}
