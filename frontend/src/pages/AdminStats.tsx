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
  total_request_telemetry_events: number;
  total_ai_turn_telemetry_events: number;
}

interface AuditRow {
  id: number;
  action: string;
  success: boolean;
  created_at: string | null;
  admin_username: string;
  target_username?: string | null;
}

interface PerformanceHistogramBucket {
  bucket: string;
  count: number;
}

interface RequestGroupPerformance {
  count: number;
  avg_ms: number;
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
  db_query_count_avg: number;
  db_query_time_ms_avg: number;
  histogram: PerformanceHistogramBucket[];
}

interface AITurnPerformance {
  count: number;
  first_token_p95_ms: number;
  total_turn_p95_ms: number;
  utility_calls_total: number;
  reasoning_calls_total: number;
  deep_calls_total: number;
  failures_total: number;
  top_failure_reasons: { operation: string; count: number }[];
}

interface AnalysisSlaPerformance {
  count: number;
  p95_seconds: number;
  avg_seconds: number;
}

interface SloTargets {
  chat_p95_first_token_ms: number;
  dashboard_p95_load_ms: number;
  analysis_completion_sla_seconds: number;
}

interface SloStatus {
  chat_first_token_meeting_slo: boolean;
  dashboard_load_meeting_slo: boolean;
  analysis_completion_meeting_slo: boolean;
}

interface AdminPerformanceStats {
  window_hours: number;
  targets: SloTargets;
  status: SloStatus;
  request_groups: Record<string, RequestGroupPerformance>;
  ai_turns: AITurnPerformance;
  analysis_sla: AnalysisSlaPerformance;
}

export default function AdminStats() {
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [performance, setPerformance] = useState<AdminPerformanceStats | null>(null);
  const [sinceHours, setSinceHours] = useState(24);
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const [error, setError] = useState('');

  const load = async (hours = sinceHours) => {
    setLoading(true);
    setError('');
    try {
      const [overview, logs, perf] = await Promise.all([
        apiClient.get<AdminStats>('/api/admin/stats/overview'),
        apiClient.get<AuditRow[]>('/api/admin/audit?limit=50'),
        apiClient.get<AdminPerformanceStats>(`/api/admin/stats/performance?since_hours=${hours}`),
      ]);
      setStats(overview);
      setAudit(logs);
      setPerformance(perf);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load admin stats.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(sinceHours);
  }, [sinceHours]);

  const formatMs = (value: number) => `${Math.round(value).toLocaleString()} ms`;
  const formatSec = (value: number) => `${value.toFixed(1)} s`;
  const formatGroupLabel = (key: string) => {
    if (key === 'chat') return 'Chat';
    if (key === 'dashboard') return 'Dashboard';
    if (key === 'analysis') return 'Analysis';
    if (key === 'logs') return 'Logs';
    return key;
  };

  const maxBucketCount = (rows: PerformanceHistogramBucket[] = []) => {
    const value = rows.reduce((m, b) => Math.max(m, b.count), 0);
    return value > 0 ? value : 1;
  };

  const renderHistogram = (rows: PerformanceHistogramBucket[] = []) => {
    const max = maxBucketCount(rows);
    return (
      <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
        {rows.map((bucket) => (
          <div key={bucket.bucket} className="contents">
            <span className="text-xs text-slate-400">{bucket.bucket}</span>
            <div className="h-5 rounded bg-slate-900/50 border border-slate-700 overflow-hidden">
              <div
                className="h-full bg-cyan-500/50 text-[10px] text-cyan-100 px-1 flex items-center justify-end"
                style={{ width: `${Math.max((bucket.count / max) * 100, bucket.count > 0 ? 8 : 0)}%` }}
                title={`${bucket.count} requests`}
              >
                {bucket.count}
              </div>
            </div>
          </div>
        ))}
      </div>
    );
  };

  const requestGroups = performance?.request_groups || {};
  const aiTurns = performance?.ai_turns;
  const analysisSla = performance?.analysis_sla;

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-5">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-slate-100">Admin Stats</h1>
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-400">Window</label>
          <select
            value={sinceHours}
            onChange={(e) => setSinceHours(Number(e.target.value))}
            className="px-2 py-1.5 text-sm rounded-lg bg-slate-800 border border-slate-600 text-slate-200"
          >
            <option value={24}>24h</option>
            <option value={72}>72h</option>
            <option value={168}>7d</option>
          </select>
          <button
            onClick={() => load(sinceHours)}
            className="px-3 py-2 text-sm border border-slate-600 rounded-lg text-slate-200 hover:bg-slate-700"
          >
            Refresh
          </button>
        </div>
      </div>

      {error && <p className="text-sm text-rose-400">{error}</p>}
      {loading && <p className="text-sm text-slate-400">Loading...</p>}

      {!loading && stats && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <StatCard label="Users" value={`${stats.total_users}`} sub={`${stats.total_admins} admin`} />
            <StatCard label="Active Users" value={`${stats.active_users_7d}`} sub={`7d (${stats.active_users_30d} in 30d)`} />
            <StatCard label="Messages" value={`${stats.total_messages}`} sub="All user messages" />
            <StatCard label="Usage Requests" value={`${stats.total_usage_requests}`} sub="Tracked model requests" />
            <StatCard label="Tokens" value={`${stats.total_tokens_in.toLocaleString()} in`} sub={`${stats.total_tokens_out.toLocaleString()} out`} />
            <StatCard label="Estimated Cost" value={`$${stats.estimated_cost_usd.toFixed(4)}`} sub="All users" />
            <StatCard label="Analysis Runs" value={`${stats.analysis_runs}`} sub="Longitudinal runs" />
            <StatCard label="Proposals" value={`${stats.analysis_proposals}`} sub="Generated proposals" />
            <StatCard
              label="Telemetry Events"
              value={`${stats.total_request_telemetry_events.toLocaleString()} req`}
              sub={`${stats.total_ai_turn_telemetry_events.toLocaleString()} AI turns`}
            />
          </div>

          {performance && (
            <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 space-y-4">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-lg font-semibold text-slate-100">Performance Baseline</h2>
                <p className="text-xs text-slate-400">Window: last {performance.window_hours}h</p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <SloCard
                  label="Chat First Token p95"
                  value={formatMs(aiTurns?.first_token_p95_ms || 0)}
                  target={`Target ${formatMs(performance.targets.chat_p95_first_token_ms)}`}
                  ok={performance.status.chat_first_token_meeting_slo}
                />
                <SloCard
                  label="Dashboard Load p95"
                  value={formatMs(requestGroups.dashboard?.p95_ms || 0)}
                  target={`Target ${formatMs(performance.targets.dashboard_p95_load_ms)}`}
                  ok={performance.status.dashboard_load_meeting_slo}
                />
                <SloCard
                  label="Analysis Completion p95"
                  value={formatSec(analysisSla?.p95_seconds || 0)}
                  target={`Target ${formatSec(performance.targets.analysis_completion_sla_seconds)}`}
                  ok={performance.status.analysis_completion_meeting_slo}
                />
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                <div className="rounded-xl bg-slate-900/40 border border-slate-700 p-3 space-y-2">
                  <h3 className="text-sm font-semibold text-slate-100">AI Turn Stats</h3>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <MetricLine label="Turns" value={`${aiTurns?.count || 0}`} />
                    <MetricLine label="Turn p95" value={formatMs(aiTurns?.total_turn_p95_ms || 0)} />
                    <MetricLine label="Utility Calls" value={`${aiTurns?.utility_calls_total || 0}`} />
                    <MetricLine label="Reasoning Calls" value={`${aiTurns?.reasoning_calls_total || 0}`} />
                    <MetricLine label="Deep Calls" value={`${aiTurns?.deep_calls_total || 0}`} />
                    <MetricLine label="Failures" value={`${aiTurns?.failures_total || 0}`} />
                  </div>
                  <div className="pt-2 border-t border-slate-700">
                    <p className="text-xs text-slate-400 mb-1">Top Failure Operations</p>
                    {aiTurns?.top_failure_reasons?.length ? (
                      <div className="space-y-1">
                        {aiTurns.top_failure_reasons.map((item) => (
                          <div key={item.operation} className="flex items-center justify-between text-xs">
                            <span className="text-slate-300 truncate">{item.operation}</span>
                            <span className="text-rose-300">{item.count}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs text-slate-500">No failures captured in this window.</p>
                    )}
                  </div>
                </div>

                <div className="rounded-xl bg-slate-900/40 border border-slate-700 p-3 space-y-2">
                  <h3 className="text-sm font-semibold text-slate-100">Request Group Latency (p95)</h3>
                  <div className="space-y-2">
                    {Object.entries(requestGroups).map(([key, group]) => (
                      <div key={key} className="rounded-lg border border-slate-700 bg-slate-900/40 p-2.5 space-y-1">
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-slate-200">{formatGroupLabel(key)}</span>
                          <span className="text-cyan-300">{formatMs(group.p95_ms)}</span>
                        </div>
                        <div className="flex items-center justify-between text-[11px] text-slate-400">
                          <span>{group.count} req</span>
                          <span>{group.db_query_count_avg.toFixed(1)} DB q avg</span>
                          <span>{group.db_query_time_ms_avg.toFixed(1)}ms DB avg</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="rounded-xl bg-slate-900/40 border border-slate-700 p-3 space-y-3">
                <h3 className="text-sm font-semibold text-slate-100">Latency Histograms</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {Object.entries(requestGroups).map(([key, group]) => (
                    <div key={key} className="rounded-lg border border-slate-700 bg-slate-900/50 p-2.5 space-y-2">
                      <p className="text-xs text-slate-200">{formatGroupLabel(key)}</p>
                      {renderHistogram(group.histogram)}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

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

function MetricLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-slate-800/70 border border-slate-700 px-2 py-1.5 flex items-center justify-between">
      <span className="text-slate-400">{label}</span>
      <span className="text-slate-100">{value}</span>
    </div>
  );
}

function SloCard({
  label,
  value,
  target,
  ok,
}: {
  label: string;
  value: string;
  target: string;
  ok: boolean;
}) {
  return (
    <div className="bg-slate-900/40 border border-slate-700 rounded-xl p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-slate-400">{label}</p>
        <span
          className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full ${
            ok
              ? 'bg-emerald-900/40 border border-emerald-700 text-emerald-300'
              : 'bg-rose-900/40 border border-rose-700 text-rose-300'
          }`}
        >
          {ok ? 'on target' : 'over target'}
        </span>
      </div>
      <p className="text-xl font-semibold text-slate-100 mt-1">{value}</p>
      <p className="text-xs text-slate-500 mt-1">{target}</p>
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
