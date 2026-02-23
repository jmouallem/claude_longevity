import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { apiClient } from '../api/client';

type CycleType = 'daily' | 'weekly' | 'monthly';
type VisibilityMode = 'top3' | 'all';
type TaskStatus = 'pending' | 'completed' | 'missed' | 'skipped';

interface PlanTask {
  id: number;
  cycle_type: CycleType | string;
  cycle_start: string;
  cycle_end: string;
  target_metric: string;
  title: string;
  description: string | null;
  domain: string;
  framework_type: string | null;
  framework_name: string | null;
  priority_score: number;
  target_value: number | null;
  target_unit: string | null;
  status: TaskStatus;
  progress_pct: number;
  due_at: string | null;
  completed_at: string | null;
}

interface PlanStats {
  total: number;
  completed: number;
  missed: number;
  pending: number;
  skipped: number;
  completion_ratio: number;
}

interface PlanReward {
  points_30d: number;
  badges: string[];
  completed_daily_streak: number;
  missed_daily_streak: number;
}

interface PlanPreference {
  visibility_mode: VisibilityMode;
  max_visible_tasks: number;
  coaching_why: string | null;
}

interface PlanNotification {
  id: number;
  category: string;
  title: string;
  message: string;
  is_read: boolean;
  created_at: string | null;
}

interface PlanAdjustment {
  id: number;
  cycle_anchor: string | null;
  title: string;
  rationale: string;
  status: string;
  source: string;
  applied_at: string | null;
  undo_expires_at: string | null;
  undo_available: boolean;
}

interface PlanSnapshot {
  cycle: {
    cycle_type: CycleType | string;
    start: string;
    end: string;
    today: string;
    timezone?: string | null;
  };
  preferences: PlanPreference;
  stats: PlanStats;
  reward: PlanReward;
  tasks: PlanTask[];
  upcoming_tasks: PlanTask[];
  notifications: PlanNotification[];
  adjustments: PlanAdjustment[];
}

interface FrameworkItem {
  id: number;
  framework_type: string;
  framework_type_label: string;
  classifier_label: string;
  name: string;
  priority_score: number;
  is_active: boolean;
  source: string;
  rationale?: string | null;
}

interface FrameworkEducation {
  framework_types: Record<
    string,
    {
      label: string;
      classifier_label: string;
      description?: string;
      examples?: string[];
    }
  >;
  grouped: Record<string, FrameworkItem[]>;
}

function percentage(value: number): string {
  return `${Math.round(Math.max(0, value))}%`;
}

function statusPill(task: PlanTask) {
  if (task.status === 'completed') return 'bg-emerald-900/50 text-emerald-300 border-emerald-700/40';
  if (task.status === 'missed') return 'bg-rose-900/50 text-rose-300 border-rose-700/40';
  if (task.status === 'skipped') return 'bg-amber-900/50 text-amber-300 border-amber-700/40';
  return 'bg-slate-800 text-slate-300 border-slate-600/70';
}

export default function Plan() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const [cycle, setCycle] = useState<CycleType>('daily');
  const [snapshot, setSnapshot] = useState<PlanSnapshot | null>(null);
  const [frameworkEducation, setFrameworkEducation] = useState<FrameworkEducation | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [busyTaskId, setBusyTaskId] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [visibilityMode, setVisibilityMode] = useState<VisibilityMode>('top3');
  const [maxVisible, setMaxVisible] = useState(3);
  const [why, setWhy] = useState('');
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [onboardingStep, setOnboardingStep] = useState(1);
  const [selectedFrameworkIds, setSelectedFrameworkIds] = useState<number[]>([]);
  const [applyingFrameworks, setApplyingFrameworks] = useState(false);
  const [cyclePreview, setCyclePreview] = useState<Record<CycleType, PlanSnapshot | null>>({
    daily: null,
    weekly: null,
    monthly: null,
  });

  const fetchSnapshot = useCallback(async (cycleType: CycleType) => {
    setLoading(true);
    setError('');
    try {
      const [data, frameworkData] = await Promise.all([
        apiClient.get<PlanSnapshot>(`/api/plan/snapshot?cycle_type=${cycleType}`),
        apiClient.get<FrameworkEducation>('/api/plan/framework-education'),
      ]);
      setSnapshot(data);
      setFrameworkEducation(frameworkData);
      setVisibilityMode((data.preferences.visibility_mode || 'top3') as VisibilityMode);
      setMaxVisible(data.preferences.max_visible_tasks || 3);
      setWhy(data.preferences.coaching_why || '');
      const activeIds = Object.values(frameworkData.grouped || {})
        .flat()
        .filter((item) => item.is_active)
        .map((item) => item.id);
      setSelectedFrameworkIds((prev) => (prev.length > 0 ? prev : activeIds));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load plan.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchSnapshot(cycle);
  }, [cycle, fetchSnapshot]);

  useEffect(() => {
    if (!frameworkEducation) return;
    const activeCount = Object.values(frameworkEducation.grouped || {})
      .flat()
      .filter((item) => item.is_active).length;
    const shouldShow = searchParams.get('onboarding') === '1' || activeCount === 0;
    setShowOnboarding(shouldShow);
    if (shouldShow) {
      setOnboardingStep(1);
    }
  }, [frameworkEducation, searchParams]);

  const updatePreference = async () => {
    setSaving(true);
    setError('');
    try {
      await apiClient.put('/api/plan/preferences', {
        visibility_mode: visibilityMode,
        max_visible_tasks: maxVisible,
        coaching_why: why.trim() || null,
      });
      await fetchSnapshot(cycle);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to update preferences.');
    } finally {
      setSaving(false);
    }
  };

  const setTaskStatus = async (taskId: number, status: 'pending' | 'completed' | 'skipped') => {
    setBusyTaskId(taskId);
    setError('');
    try {
      await apiClient.post(`/api/plan/tasks/${taskId}/status`, { status });
      await fetchSnapshot(cycle);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to update task.');
    } finally {
      setBusyTaskId(null);
    }
  };

  const markNotificationRead = async (notificationId: number) => {
    try {
      await apiClient.post(`/api/plan/notifications/${notificationId}/read`, {});
      await fetchSnapshot(cycle);
    } catch {
      // no-op on read failures
    }
  };

  const undoAdjustment = async (adjustmentId: number) => {
    setError('');
    try {
      await apiClient.post(`/api/plan/adjustments/${adjustmentId}/undo`, {});
      await fetchSnapshot(cycle);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to undo adjustment.');
    }
  };

  const closeOnboarding = () => {
    setShowOnboarding(false);
    if (searchParams.get('onboarding') === '1') {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.delete('onboarding');
      setSearchParams(nextParams, { replace: true });
    }
  };

  const toggleFrameworkSelection = (id: number) => {
    setSelectedFrameworkIds((prev) =>
      prev.includes(id) ? prev.filter((itemId) => itemId !== id) : [...prev, id],
    );
  };

  const applyFrameworkSelection = async () => {
    setApplyingFrameworks(true);
    setError('');
    try {
      await apiClient.post('/api/plan/framework-selection', {
        selected_framework_ids: selectedFrameworkIds,
      });
      await fetchSnapshot(cycle);
      setOnboardingStep(2);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to apply framework selection.');
    } finally {
      setApplyingFrameworks(false);
    }
  };

  const loadCyclePreview = useCallback(async () => {
    try {
      const [daily, weekly, monthly] = await Promise.all([
        apiClient.get<PlanSnapshot>('/api/plan/snapshot?cycle_type=daily'),
        apiClient.get<PlanSnapshot>('/api/plan/snapshot?cycle_type=weekly'),
        apiClient.get<PlanSnapshot>('/api/plan/snapshot?cycle_type=monthly'),
      ]);
      setCyclePreview({ daily, weekly, monthly });
    } catch {
      // keep onboarding functional even if preview fetch fails
    }
  }, []);

  useEffect(() => {
    if (!showOnboarding || onboardingStep !== 2) return;
    void loadCyclePreview();
  }, [showOnboarding, onboardingStep, loadCyclePreview]);

  const unreadNotifications = useMemo(
    () => (snapshot?.notifications || []).filter((n) => !n.is_read),
    [snapshot?.notifications],
  );
  const frameworkGroups = useMemo(
    () => frameworkEducation?.grouped || {},
    [frameworkEducation?.grouped],
  );

  if (loading && !snapshot) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-3.5rem)]">
        <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Plan</h1>
          <p className="text-sm text-slate-400">
            Foundation - Execute - Reflect - Loop
          </p>
        </div>
        <div className="inline-flex rounded-lg border border-slate-700 bg-slate-800/80 p-0.5">
          {[
            { key: 'daily', label: 'Daily' },
            { key: 'weekly', label: 'Weekly' },
            { key: 'monthly', label: '30-Day' },
          ].map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setCycle(tab.key as CycleType)}
              className={[
                'px-3 py-1.5 text-sm rounded-md transition-colors',
                cycle === tab.key ? 'bg-emerald-600 text-white' : 'text-slate-300 hover:bg-slate-700/70',
              ].join(' ')}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {showOnboarding && snapshot && frameworkEducation && (
        <div className="rounded-xl border border-emerald-700/40 bg-emerald-950/10 p-4 space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-slate-100">Post-Intake Plan Setup</h2>
              <p className="text-xs text-slate-400 mt-1">
                Step {onboardingStep} of 3: choose frameworks, confirm targets, then start execution.
              </p>
            </div>
            <button
              type="button"
              onClick={closeOnboarding}
              className="px-2.5 py-1 text-xs rounded-md border border-slate-600 text-slate-300 hover:bg-slate-700"
            >
              Skip for now
            </button>
          </div>

          {onboardingStep === 1 && (
            <div className="space-y-3">
              <p className="text-sm text-slate-300">
                Select the strategies you want active now. You can change this later in Settings at any time.
              </p>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                {Object.entries(frameworkEducation.framework_types).map(([frameworkType, meta]) => {
                  const items = frameworkGroups[frameworkType] || [];
                  return (
                    <div key={frameworkType} className="rounded-lg border border-slate-700 bg-slate-900/40 p-3 space-y-2">
                      <div>
                        <p className="text-sm font-medium text-slate-100">{meta.label}</p>
                        <p className="text-xs text-slate-400">{meta.classifier_label}</p>
                      </div>
                      <details className="text-xs text-slate-400">
                        <summary className="cursor-pointer">Framework description and examples</summary>
                        <p className="mt-1">{meta.description || 'No description available.'}</p>
                        {!!meta.examples?.length && (
                          <p className="mt-1">Examples: {meta.examples.join(', ')}</p>
                        )}
                      </details>
                      <div className="flex flex-wrap gap-2">
                        {items.map((item) => {
                          const selected = selectedFrameworkIds.includes(item.id);
                          return (
                            <button
                              key={item.id}
                              type="button"
                              onClick={() => toggleFrameworkSelection(item.id)}
                              className={[
                                'px-2.5 py-1 text-xs rounded-md border transition-colors',
                                selected
                                  ? 'border-emerald-500 bg-emerald-600/20 text-emerald-200'
                                  : 'border-slate-600 text-slate-300 hover:bg-slate-700',
                              ].join(' ')}
                            >
                              {item.name}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-xs text-slate-400">
                  Selected strategies: {selectedFrameworkIds.length}
                </p>
                <button
                  type="button"
                  onClick={applyFrameworkSelection}
                  disabled={applyingFrameworks}
                  className="px-3 py-1.5 text-xs rounded-md bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-50"
                >
                  {applyingFrameworks ? 'Applying...' : 'Apply Selection'}
                </button>
              </div>
            </div>
          )}

          {onboardingStep === 2 && (
            <div className="space-y-3">
              <p className="text-sm text-slate-300">
                These are your plan targets. Daily, weekly, and rolling 30-day goals will auto-adjust based on progress.
              </p>
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                {([
                  ['daily', 'Daily'],
                  ['weekly', 'Weekly'],
                  ['monthly', '30-Day'],
                ] as Array<[CycleType, string]>).map(([key, label]) => {
                  const preview = cyclePreview[key];
                  const topTasks = (preview?.upcoming_tasks || []).slice(0, 3);
                  return (
                    <div key={key} className="rounded-lg border border-slate-700 bg-slate-900/40 p-3 space-y-2">
                      <p className="text-sm font-medium text-slate-100">{label}</p>
                      <p className="text-xs text-slate-400">
                        {preview ? `${Math.round(preview.stats.completion_ratio * 100)}% completion` : 'Loading preview...'}
                      </p>
                      {topTasks.length === 0 ? (
                        <p className="text-xs text-slate-500">No pending tasks in this window.</p>
                      ) : (
                        <ul className="text-xs text-slate-300 space-y-1">
                          {topTasks.map((task) => (
                            <li key={task.id}>- {task.title}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  );
                })}
              </div>
              <div className="flex flex-wrap items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setOnboardingStep(1)}
                  className="px-3 py-1.5 text-xs rounded-md border border-slate-600 text-slate-300 hover:bg-slate-700"
                >
                  Back
                </button>
                <button
                  type="button"
                  onClick={() => setOnboardingStep(3)}
                  className="px-3 py-1.5 text-xs rounded-md bg-emerald-600 hover:bg-emerald-500 text-white"
                >
                  Start Execution
                </button>
              </div>
            </div>
          )}

          {onboardingStep === 3 && (
            <div className="space-y-3">
              <p className="text-sm text-slate-300">
                Start with the next top goals now. Complete one, then move to the next.
              </p>
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                {(snapshot.upcoming_tasks || []).slice(0, 3).map((task) => (
                  <div key={task.id} className="rounded-lg border border-slate-700 bg-slate-900/40 p-3 space-y-2">
                    <p className="text-sm font-medium text-slate-100">{task.title}</p>
                    {task.description && <p className="text-xs text-slate-400">{task.description}</p>}
                    <button
                      type="button"
                      onClick={() => setTaskStatus(task.id, 'completed')}
                      disabled={busyTaskId === task.id}
                      className="px-2.5 py-1 text-xs rounded-md bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-50"
                    >
                      {busyTaskId === task.id ? 'Saving...' : 'Mark Complete'}
                    </button>
                  </div>
                ))}
              </div>
              <div className="flex flex-wrap items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={closeOnboarding}
                  className="px-3 py-1.5 text-xs rounded-md border border-slate-600 text-slate-300 hover:bg-slate-700"
                >
                  Stay on Plan
                </button>
                <button
                  type="button"
                  onClick={() => {
                    closeOnboarding();
                    navigate('/chat');
                  }}
                  className="px-3 py-1.5 text-xs rounded-md bg-emerald-600 hover:bg-emerald-500 text-white"
                >
                  Go to Guided Chat
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="text-sm text-rose-300 bg-rose-900/20 border border-rose-700/40 rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      {snapshot && (
        <div className="grid grid-cols-1 xl:grid-cols-[1.45fr_1fr] gap-4">
          <div className="space-y-4">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                <p className="text-xs text-slate-400">Completion</p>
                <p className="text-xl font-semibold text-slate-100 mt-1">{percentage(snapshot.stats.completion_ratio * 100)}</p>
              </div>
              <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                <p className="text-xs text-slate-400">Points (30d)</p>
                <p className="text-xl font-semibold text-emerald-300 mt-1">{snapshot.reward.points_30d}</p>
              </div>
              <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                <p className="text-xs text-slate-400">Streak</p>
                <p className="text-xl font-semibold text-slate-100 mt-1">{snapshot.reward.completed_daily_streak}d</p>
              </div>
              <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                <p className="text-xs text-slate-400">Window</p>
                <p className="text-sm font-medium text-slate-100 mt-1">
                  {snapshot.cycle.start}
                  {snapshot.cycle.start !== snapshot.cycle.end ? ` -> ${snapshot.cycle.end}` : ''}
                </p>
              </div>
            </div>

            <div className="rounded-xl border border-slate-700 bg-slate-800 p-4 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-sm font-semibold text-slate-100">Execution Tasks</h2>
                <span className="text-xs text-slate-400">
                  {snapshot.stats.completed} completed | {snapshot.stats.pending} pending | {snapshot.stats.missed} missed
                </span>
              </div>
              <div className="space-y-2 max-h-[420px] overflow-y-auto pr-1">
                {snapshot.tasks.length === 0 ? (
                  <p className="text-sm text-slate-400">No tasks for this cycle yet.</p>
                ) : (
                  snapshot.tasks.map((task) => (
                    <div key={task.id} className="rounded-lg border border-slate-700 bg-slate-900/40 p-3">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-slate-100">{task.title}</p>
                          {task.description && <p className="text-xs text-slate-400 mt-0.5">{task.description}</p>}
                        </div>
                        <span className={`text-[10px] px-2 py-0.5 rounded-full border ${statusPill(task)}`}>{task.status}</span>
                      </div>
                      <div className="mt-2">
                        <div className="flex justify-between text-[11px] text-slate-400 mb-1">
                          <span>{Math.round(task.progress_pct)}%</span>
                          <span>
                            {task.target_value != null ? `${task.target_value}${task.target_unit ? ` ${task.target_unit}` : ''}` : ''}
                          </span>
                        </div>
                        <div className="h-2 rounded-full bg-slate-700 overflow-hidden">
                          <div
                            className={`h-full ${task.status === 'completed' ? 'bg-emerald-500' : task.status === 'missed' ? 'bg-rose-500' : 'bg-sky-500'} transition-all duration-300`}
                            style={{ width: `${Math.min(task.progress_pct, 100)}%` }}
                          />
                        </div>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          onClick={() => setTaskStatus(task.id, task.status === 'completed' ? 'pending' : 'completed')}
                          disabled={busyTaskId === task.id}
                          className="px-2.5 py-1 text-xs rounded-md bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-50"
                        >
                          {task.status === 'completed' ? 'Mark Pending' : 'Mark Complete'}
                        </button>
                        <button
                          type="button"
                          onClick={() => setTaskStatus(task.id, 'skipped')}
                          disabled={busyTaskId === task.id}
                          className="px-2.5 py-1 text-xs rounded-md border border-slate-600 text-slate-200 hover:bg-slate-700 disabled:opacity-50"
                        >
                          Skip
                        </button>
                        {task.framework_name && (
                          <span className="text-[11px] text-cyan-300">{task.framework_name}</span>
                        )}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>

          <div className="space-y-4">
            <div className="rounded-xl border border-slate-700 bg-slate-800 p-4 space-y-3">
              <h2 className="text-sm font-semibold text-slate-100">Display Preferences</h2>
              <div className="space-y-2">
                <label className="text-xs text-slate-400 block">Task visibility</label>
                <div className="inline-flex rounded-lg border border-slate-600 bg-slate-900/40 p-0.5">
                  <button
                    type="button"
                    onClick={() => setVisibilityMode('top3')}
                    className={`px-2.5 py-1 text-xs rounded-md ${visibilityMode === 'top3' ? 'bg-emerald-600 text-white' : 'text-slate-300 hover:bg-slate-700'}`}
                  >
                    Top 3
                  </button>
                  <button
                    type="button"
                    onClick={() => setVisibilityMode('all')}
                    className={`px-2.5 py-1 text-xs rounded-md ${visibilityMode === 'all' ? 'bg-emerald-600 text-white' : 'text-slate-300 hover:bg-slate-700'}`}
                  >
                    All
                  </button>
                </div>
              </div>
              <div className="space-y-1">
                <label className="text-xs text-slate-400 block">Visible task limit</label>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={maxVisible}
                  onChange={(e) => setMaxVisible(Math.max(1, Math.min(10, Number(e.target.value || 3))))}
                  className="w-24 bg-slate-700 border border-slate-600 rounded px-2 py-1.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-slate-400 block">Your reminder &quot;why&quot;</label>
                <textarea
                  rows={2}
                  value={why}
                  onChange={(e) => setWhy(e.target.value)}
                  placeholder="e.g. I want stable blood pressure and more energy for my family."
                  className="w-full bg-slate-700 border border-slate-600 rounded px-2 py-1.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500"
                />
              </div>
              <button
                type="button"
                onClick={updatePreference}
                disabled={saving}
                className="px-3 py-1.5 text-xs rounded-md bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-50"
              >
                {saving ? 'Saving...' : 'Save Preferences'}
              </button>
            </div>

            <div className="rounded-xl border border-slate-700 bg-slate-800 p-4 space-y-2">
              <h2 className="text-sm font-semibold text-slate-100">Unread Prompts</h2>
              {unreadNotifications.length === 0 ? (
                <p className="text-xs text-slate-400">No missed-goal prompts right now.</p>
              ) : (
                <div className="space-y-2">
                  {unreadNotifications.slice(0, 5).map((n) => (
                    <button
                      key={n.id}
                      type="button"
                      onClick={() => markNotificationRead(n.id)}
                      className="w-full text-left rounded-md border border-slate-700 bg-slate-900/40 px-2.5 py-2 hover:border-slate-500"
                    >
                      <p className="text-xs font-medium text-slate-100">{n.title}</p>
                      <p className="text-[11px] text-slate-400 mt-1">{n.message}</p>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="rounded-xl border border-slate-700 bg-slate-800 p-4 space-y-2">
              <h2 className="text-sm font-semibold text-slate-100">Auto Adjustments</h2>
              {snapshot.adjustments.length === 0 ? (
                <p className="text-xs text-slate-400">No adjustments yet.</p>
              ) : (
                <div className="space-y-2 max-h-[200px] overflow-y-auto pr-1">
                  {snapshot.adjustments.map((adj) => (
                    <div key={adj.id} className="rounded-md border border-slate-700 bg-slate-900/40 px-2.5 py-2">
                      <p className="text-xs font-medium text-slate-100">{adj.title}</p>
                      <p className="text-[11px] text-slate-400 mt-0.5">{adj.rationale}</p>
                      <p className="text-[10px] text-slate-500 mt-1">
                        {adj.applied_at ? new Date(adj.applied_at).toLocaleString() : ''}
                      </p>
                      {adj.undo_available && (
                        <button
                          type="button"
                          onClick={() => undoAdjustment(adj.id)}
                          className="mt-2 px-2 py-1 text-[11px] rounded border border-slate-600 text-slate-200 hover:bg-slate-700"
                        >
                          Undo
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {frameworkEducation && (
        <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
          <h2 className="text-sm font-semibold text-slate-100 mb-2">Framework Education</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {Object.entries(frameworkEducation.framework_types).map(([key, value]) => (
              <details key={key} className="rounded-md border border-slate-700 bg-slate-900/35 px-3 py-2">
                <summary className="text-sm text-slate-100 cursor-pointer">{value.label}</summary>
                <p className="text-xs text-slate-400 mt-2">{value.description || ''}</p>
                {!!value.examples?.length && (
                  <p className="text-[11px] text-slate-500 mt-1">Examples: {value.examples.join(', ')}</p>
                )}
              </details>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
