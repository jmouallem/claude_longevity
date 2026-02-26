import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { apiClient } from '../api/client';
import { useAuthStore } from '../stores/authStore';
import GoalChatPanel from '../components/GoalChatPanel';
import {
  TIME_BLOCKS, GOAL_TYPE_LABELS, GOAL_TYPE_STYLES, DEFAULT_STYLE,
  greetingFor, completionPct, daysRemaining, milestoneMessage, motivationalLine,
} from '../utils/coaching-ui';
import type { PlanStats } from '../utils/coaching-ui';
import { ProgressRing, ProgressJourney, GoalTypeIcon } from '../utils/coaching-ui-components';

/* ─── Types ─── */

interface UserGoal {
  id: number;
  title: string;
  description?: string;
  goal_type: string;
  target_value?: number;
  target_unit?: string;
  baseline_value?: number;
  current_value?: number;
  target_date?: string;
  status: string;
  priority: number;
  why?: string;
  created_by?: string;
  progress_pct?: number;
}

interface PlanTask {
  id: number;
  cycle_start: string;
  cycle_end: string;
  title: string;
  description?: string;
  domain: string;
  status: string;
  progress_pct: number;
  time_of_day: string;
  priority_score: number;
  target_value?: number;
  target_unit?: string;
  goal_id?: number;
}

interface PlanSnapshot {
  cycle: { today: string; start: string; end: string; cycle_type: string };
  stats: PlanStats;
  reward: { completed_daily_streak: number };
  tasks: PlanTask[];
  upcoming_tasks?: PlanTask[];
}

interface RollingSnapshot {
  timezone?: string | null;
  start_date: string;
  window_days: number;
  days: PlanSnapshot[];
  weekly: { stats: PlanStats };
  monthly: { stats: PlanStats };
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
  metadata?: Record<string, unknown>;
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

type ViewMode = 'today' | 'next5';
type CycleType = 'daily' | 'weekly' | 'monthly';

/* Constants imported from ../utils/coaching-ui */

/* ─── Helpers ─── */

const KG_TO_LB = 2.20462;

/** Convert weight-related goal values to the user's preferred unit for display. */
function convertGoalUnits(goal: UserGoal, preferredUnit: 'kg' | 'lb'): UserGoal {
  const storedUnit = (goal.target_unit || '').toLowerCase().trim();
  // Only convert weight goals (kg ↔ lb)
  if (
    (storedUnit === 'kg' && preferredUnit === 'lb') ||
    (storedUnit === 'lb' && preferredUnit === 'kg')
  ) {
    const factor = storedUnit === 'kg' ? KG_TO_LB : 1 / KG_TO_LB;
    const displayUnit = preferredUnit;
    return {
      ...goal,
      target_value: goal.target_value != null ? Math.round(goal.target_value * factor * 100) / 100 : goal.target_value,
      baseline_value: goal.baseline_value != null ? Math.round(goal.baseline_value * factor * 100) / 100 : goal.baseline_value,
      current_value: goal.current_value != null ? Math.round(goal.current_value * factor * 100) / 100 : goal.current_value,
      target_unit: displayUnit,
    };
  }
  return goal;
}

function formatGoalForPrompt(goal: UserGoal): string {
  const targetPart =
    goal.target_value != null && goal.target_unit
      ? `target ${goal.target_value} ${goal.target_unit}`
      : 'target not set';
  const datePart = goal.target_date ? `by ${goal.target_date}` : 'date not set';
  return `${goal.title} (${targetPart}, ${datePart})`;
}

function buildGoalKickoffPrompt(args: {
  goals: UserGoal[];
  isOnboarding: boolean;
  displayName: string;
}): string {
  const { goals, isOnboarding, displayName } = args;
  const namePart = displayName ? ` for ${displayName}` : '';
  if (goals.length === 0) {
    return [
      `Goal-setting kickoff${namePart}:`,
      'I want to define 1-3 measurable health goals with target values, deadlines, and why they matter.',
      'Please guide me step-by-step and save each goal using the goal tools.',
      'After we finalize goals, remind me to return to the Goals page to review todays timeline.',
      isOnboarding ? 'I just completed intake, so use my profile context to propose smart starting goals.' : '',
    ]
      .filter(Boolean)
      .join(' ');
  }

  const listedGoals = goals.slice(0, 5).map(formatGoalForPrompt).join('; ');
  const hasIntakeDrafts = isOnboarding && goals.some(g => g.created_by === 'intake');
  return [
    `Goal-refinement kickoff${namePart}:`,
    `Please review and refine my existing goals: ${listedGoals}.`,
    hasIntakeDrafts ? 'These goals were auto-created from my intake answers and may need specific targets and timelines.' : '',
    'Help me keep only high-value goals, adjust targets/timelines where needed, and update any goal records.',
    'After we finalize changes, remind me to return to the Goals page to review todays timeline.',
  ].filter(Boolean).join(' ');
}

function formatDateLabel(isoDate: string): string {
  return new Date(`${isoDate}T00:00:00`).toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  });
}

/* Shared helpers imported from ../utils/coaching-ui */

/* SVG components imported from ../utils/coaching-ui-components */

function StatusIcon({ status }: { status: string }) {
  if (status === 'completed') {
    return (
      <svg width="18" height="18" viewBox="0 0 20 20" className="text-emerald-400 shrink-0">
        <circle cx="10" cy="10" r="9" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M6 10.5l2.5 2.5 5.5-5.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (status === 'missed') {
    return (
      <svg width="18" height="18" viewBox="0 0 20 20" className="text-rose-400/60 shrink-0">
        <circle cx="10" cy="10" r="9" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M7 7l6 6M13 7l-6 6" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg width="18" height="18" viewBox="0 0 20 20" className="text-slate-500 shrink-0">
      <circle cx="10" cy="10" r="9" fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

/* ─── Sub-components ─── */

function GoalHeroCard({
  goal,
  onCheckIn,
}: {
  goal: UserGoal;
  onCheckIn: (goal: UserGoal) => void;
}) {
  const style = GOAL_TYPE_STYLES[goal.goal_type] || DEFAULT_STYLE;
  const label = GOAL_TYPE_LABELS[goal.goal_type] || goal.goal_type.replace('_', ' ');
  const isDraft = goal.target_value == null;
  const days = goal.target_date ? daysRemaining(goal.target_date) : null;
  const milestone = milestoneMessage(goal);

  return (
    <div
      className={`bg-gradient-to-br ${style.gradientFrom} ${style.gradientTo} ${
        isDraft ? 'border-dashed border-2' : 'border'
      } ${style.border} rounded-xl p-5 space-y-3 transition-all duration-300 hover:shadow-lg hover:shadow-slate-950/40`}
    >
      {/* Top row: type + target date */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ backgroundColor: style.ring + '1a' }}
          >
            <GoalTypeIcon goalType={goal.goal_type} className={style.text} />
          </div>
          <span className={`text-xs font-semibold uppercase tracking-wide ${style.text}`}>
            {label}
          </span>
        </div>
        {days != null && (
          <span className={`text-xs ${days <= 0 ? 'text-rose-400 font-medium' : 'text-slate-400'}`}>
            {days > 0 ? `${days} days left` : days === 0 ? 'Due today' : 'Overdue'}
          </span>
        )}
      </div>

      {/* Title */}
      <h3 className="text-lg font-semibold text-slate-100 leading-snug">{goal.title}</h3>

      {/* Why it matters */}
      {goal.why && (
        <p className="text-sm text-slate-400 italic leading-relaxed">
          &ldquo;{goal.why}&rdquo;
        </p>
      )}

      {/* Progress */}
      {isDraft ? (
        <div className="bg-slate-800/40 rounded-lg px-4 py-3 border border-dashed border-slate-600/50">
          <p className="text-sm text-slate-400">
            This goal needs a specific target to track progress.
          </p>
        </div>
      ) : (
        <ProgressJourney goal={goal} />
      )}

      {/* Milestone message */}
      {milestone && !isDraft && (
        <p className={`text-sm font-medium ${style.text}`}>{milestone}</p>
      )}

      {/* Actions */}
      <div className="flex items-center justify-end pt-1">
        <button
          onClick={() => onCheckIn(goal)}
          className={`px-3.5 py-1.5 text-xs font-medium rounded-lg transition-colors ${
            isDraft
              ? `border ${style.border} ${style.text} hover:bg-slate-700/50`
              : 'bg-slate-700/60 text-slate-200 hover:bg-slate-600/60'
          }`}
        >
          {isDraft ? 'Refine goal' : 'Check in'}
        </button>
      </div>
    </div>
  );
}

function TaskRow({
  task,
  onChat,
}: {
  task: PlanTask;
  onChat: (task: PlanTask) => void;
}) {
  const isDone = task.status === 'completed';
  const isMissed = task.status === 'missed';

  return (
    <div
      className={`flex items-center gap-3 py-2.5 px-3 transition-colors ${
        isDone ? 'opacity-60' : isMissed ? 'opacity-40' : 'hover:bg-slate-700/30'
      }`}
    >
      <StatusIcon status={task.status} />

      <div className="flex-1 min-w-0">
        <p className={`text-sm text-slate-200 ${isDone ? 'line-through text-slate-500' : ''}`}>{task.title}</p>
        {task.description && !isDone && <p className="text-xs text-slate-500 mt-0.5 line-clamp-1">{task.description}</p>}
        {task.status === 'pending' && task.progress_pct > 0 && (
          <div className="mt-1 h-0.5 bg-slate-700 rounded-full w-24">
            <div
              className="h-full bg-emerald-500/70 rounded-full transition-all duration-500"
              style={{ width: `${Math.min(100, task.progress_pct)}%` }}
            />
          </div>
        )}
      </div>

      {!isDone && (
        <button
          onClick={() => onChat(task)}
          className="flex-shrink-0 px-2.5 py-1 text-xs text-slate-400 hover:text-emerald-400 hover:bg-slate-700/50 rounded-lg transition-colors"
          title="Check in with coach"
        >
          Chat
        </button>
      )}
    </div>
  );
}

function TimeBlock({
  block,
  tasks,
  onChat,
}: {
  block: { key: string; label: string };
  tasks: PlanTask[];
  onChat: (task: PlanTask) => void;
}) {
  if (tasks.length === 0) return null;
  const done = tasks.filter((t) => t.status === 'completed').length;
  const allDone = done === tasks.length;

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2.5 px-1">
        <span className={`w-1.5 h-1.5 rounded-full transition-colors ${allDone ? 'bg-emerald-400' : 'bg-slate-500'}`} />
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">{block.label}</h3>
        <span className="text-xs text-slate-600 ml-auto">{done}/{tasks.length}</span>
      </div>
      <div className="bg-slate-800/40 rounded-xl border border-slate-700/40 overflow-hidden divide-y divide-slate-700/30">
        {tasks.map((task) => (
          <TaskRow key={task.id} task={task} onChat={onChat} />
        ))}
      </div>
    </div>
  );
}

function GoalTaskGroup({
  goalTitle,
  goalStyle,
  tasks,
  onChat,
}: {
  goalTitle: string;
  goalStyle: typeof DEFAULT_STYLE;
  tasks: PlanTask[];
  onChat: (task: PlanTask) => void;
}) {
  const done = tasks.filter((t) => t.status === 'completed').length;
  const allDone = done === tasks.length;

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2.5 px-1">
        <span className={`w-1.5 h-1.5 rounded-full transition-colors ${allDone ? 'bg-emerald-400' : 'bg-slate-500'}`} />
        <h3 className={`text-xs font-semibold uppercase tracking-wider ${goalStyle.text}`}>{goalTitle}</h3>
        <span className="text-xs text-slate-600 ml-auto">{done}/{tasks.length}</span>
      </div>
      <div className="bg-slate-800/40 rounded-xl border border-slate-700/40 overflow-hidden divide-y divide-slate-700/30">
        {tasks.map((task) => (
          <TaskRow key={task.id} task={task} onChat={onChat} />
        ))}
      </div>
    </div>
  );
}

function DayPlanCard({
  snapshot,
  onChat,
}: {
  snapshot: PlanSnapshot;
  onChat: (task: PlanTask) => void;
}) {
  const dateLabel = formatDateLabel(snapshot.cycle.today);
  const tasks = snapshot.tasks.filter((t) => t.status !== 'skipped');
  const byTime: Record<string, PlanTask[]> = { morning: [], afternoon: [], evening: [], anytime: [] };
  for (const task of tasks) {
    const key = byTime[task.time_of_day] ? task.time_of_day : 'anytime';
    byTime[key].push(task);
  }
  for (const key of Object.keys(byTime)) {
    byTime[key].sort((a, b) => (b.priority_score || 0) - (a.priority_score || 0));
  }

  return (
    <div className="bg-slate-800/30 border border-slate-700/40 rounded-xl p-3 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-slate-100">{dateLabel}</p>
        <p className="text-xs text-slate-400">
          {snapshot.stats.completed}/{snapshot.stats.total} done
        </p>
      </div>
      <div className="space-y-3">
        {TIME_BLOCKS.map((block) => (
          <TimeBlock key={`${snapshot.cycle.today}-${block.key}`} block={block} tasks={byTime[block.key] || []} onChat={onChat} />
        ))}
      </div>
    </div>
  );
}

/* ─── Main Component ─── */

export default function Goals() {
  const user = useAuthStore((state) => state.user);
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const isOnboarding = searchParams.get('onboarding') === '1';

  const [goals, setGoals] = useState<UserGoal[]>([]);
  const [rolling, setRolling] = useState<RollingSnapshot | null>(null);
  const [loadingGoals, setLoadingGoals] = useState(true);
  const [loadingPlan, setLoadingPlan] = useState(true);
  const [viewMode, setViewMode] = useState<ViewMode>('today');

  const [chatOpen, setChatOpen] = useState(false);
  const [chatTitle, setChatTitle] = useState('');
  const [chatDesc, setChatDesc] = useState('');
  const [chatInitialMessage, setChatInitialMessage] = useState('');

  // User preferences from profile
  const [healthGoalsTags, setHealthGoalsTags] = useState<string[]>([]);
  const [weightUnit, setWeightUnit] = useState<'kg' | 'lb'>('kg');

  // Onboarding wizard state
  const [frameworkEducation, setFrameworkEducation] = useState<FrameworkEducation | null>(null);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [onboardingStep, setOnboardingStep] = useState(1);
  const [selectedFrameworkIds, setSelectedFrameworkIds] = useState<number[]>([]);
  const [applyingFrameworks, setApplyingFrameworks] = useState(false);
  const [cyclePreview, setCyclePreview] = useState<Record<CycleType, PlanSnapshot | null>>({
    daily: null,
    weekly: null,
    monthly: null,
  });

  const fetchGoals = useCallback(async () => {
    try {
      const data = await apiClient.get<UserGoal[]>('/api/goals?status=active');
      setGoals(data);
    } catch {
      setGoals([]);
    } finally {
      setLoadingGoals(false);
    }
  }, []);

  const fetchPlan = useCallback(async () => {
    try {
      const [planData, fwData, profileData] = await Promise.all([
        apiClient.get<RollingSnapshot>('/api/plan/snapshot/rolling?days=5'),
        apiClient.get<FrameworkEducation>('/api/plan/framework-education'),
        apiClient.get<{ health_goals?: string | null; weight_unit?: string | null }>('/api/settings/profile').catch(() => null),
      ]);
      setRolling(planData);
      setFrameworkEducation(fwData);

      // Extract user preferences
      if (profileData?.weight_unit === 'lb') setWeightUnit('lb');

      // Parse health goals for framework alignment highlighting
      if (profileData?.health_goals) {
        try {
          const parsed = JSON.parse(profileData.health_goals);
          if (Array.isArray(parsed)) {
            setHealthGoalsTags(parsed.map((v: unknown) => String(v || '').trim()).filter(Boolean));
          }
        } catch {
          // comma-separated fallback
          setHealthGoalsTags(
            profileData.health_goals.split(',').map((s: string) => s.trim()).filter(Boolean)
          );
        }
      }

      const activeIds = Object.values(fwData.grouped || {})
        .flat()
        .filter((item) => item.is_active)
        .map((item) => item.id);
      setSelectedFrameworkIds((prev) => (prev.length > 0 ? prev : activeIds));
    } catch {
      setRolling(null);
    } finally {
      setLoadingPlan(false);
    }
  }, []);

  useEffect(() => {
    fetchGoals();
    fetchPlan();
  }, [fetchGoals, fetchPlan]);

  // Refresh when page becomes visible again (e.g. returning from another tab)
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        fetchGoals();
        fetchPlan();
      }
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [fetchGoals, fetchPlan]);

  // Onboarding trigger
  useEffect(() => {
    if (!frameworkEducation) return;
    const activeCount = Object.values(frameworkEducation.grouped || {})
      .flat()
      .filter((item) => item.is_active).length;
    const shouldShow = isOnboarding || activeCount === 0;
    setShowOnboarding(shouldShow);
    if (shouldShow) setOnboardingStep(1);
  }, [frameworkEducation, isOnboarding]);

  // Load cycle previews for onboarding step 2
  const loadCyclePreview = useCallback(async () => {
    try {
      const [daily, weekly, monthly] = await Promise.all([
        apiClient.get<PlanSnapshot>('/api/plan/snapshot?cycle_type=daily'),
        apiClient.get<PlanSnapshot>('/api/plan/snapshot?cycle_type=weekly'),
        apiClient.get<PlanSnapshot>('/api/plan/snapshot?cycle_type=monthly'),
      ]);
      setCyclePreview({ daily, weekly, monthly });
    } catch {
      // keep onboarding functional
    }
  }, []);

  useEffect(() => {
    if (!showOnboarding || onboardingStep !== 2) return;
    void loadCyclePreview();
  }, [showOnboarding, onboardingStep, loadCyclePreview]);

  const closeOnboarding = useCallback(() => {
    setShowOnboarding(false);
    if (searchParams.get('onboarding') === '1') {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.delete('onboarding');
      setSearchParams(nextParams, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const toggleFrameworkSelection = useCallback((id: number) => {
    setSelectedFrameworkIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }, []);

  const applyFrameworkSelection = useCallback(async () => {
    setApplyingFrameworks(true);
    try {
      await apiClient.post('/api/plan/framework-selection', {
        selected_framework_ids: selectedFrameworkIds,
      });
      await fetchPlan();
      setOnboardingStep(2);
    } catch {
      // handled
    } finally {
      setApplyingFrameworks(false);
    }
  }, [selectedFrameworkIds, fetchPlan]);

  const todaySnapshot = rolling?.days?.[0] ?? null;

  const handleChat = useCallback((task: PlanTask) => {
    const dateLabel = task.cycle_start ? formatDateLabel(task.cycle_start) : 'today';
    setChatTitle(task.title);
    setChatDesc(task.description || '');
    setChatInitialMessage(
      `Goal check-in for ${dateLabel}: ${task.title}${task.description ? ` (${task.description})` : ''} [task_id=${task.id}]`
    );
    setChatOpen(true);
  }, []);

  const handleChatClose = useCallback(() => {
    setChatOpen(false);
    setChatTitle('');
    setChatDesc('');
    setChatInitialMessage('');
  }, []);

  const handleTaskUpdated = useCallback(() => {
    fetchGoals();
    fetchPlan();
  }, [fetchGoals, fetchPlan]);

  const displayName = user?.display_name || user?.username || '';
  const today = todaySnapshot?.cycle?.today
    ? formatDateLabel(todaySnapshot.cycle.today)
    : formatDateLabel(new Date().toISOString().slice(0, 10));

  const stats = todaySnapshot?.stats;
  const streak = todaySnapshot?.reward?.completed_daily_streak ?? 0;
  const weeklyPct = completionPct(rolling?.weekly?.stats);
  const monthlyPct = completionPct(rolling?.monthly?.stats);

  const todayTasksByTime = useMemo(() => {
    const grouped: Record<string, PlanTask[]> = { morning: [], afternoon: [], evening: [], anytime: [] };
    const tasks = (todaySnapshot?.tasks ?? []).filter((t) => t.status !== 'skipped');
    for (const task of tasks) {
      const key = grouped[task.time_of_day] ? task.time_of_day : 'anytime';
      grouped[key].push(task);
    }
    for (const key of Object.keys(grouped)) {
      grouped[key].sort((a, b) => (b.priority_score || 0) - (a.priority_score || 0));
    }
    return grouped;
  }, [todaySnapshot]);

  // Goal-grouped tasks: group today's tasks by the goal they serve
  const goalTaskGroups = useMemo(() => {
    const tasks = (todaySnapshot?.tasks ?? []).filter(t => t.status !== 'skipped');
    const hasGoalLinks = tasks.some(t => t.goal_id != null);
    if (!hasGoalLinks) return null;

    const goalMap = new Map(goals.map(g => [g.id, g]));
    const groups: Record<string, { title: string; style: typeof DEFAULT_STYLE; tasks: PlanTask[] }> = {};

    for (const task of tasks) {
      const goalId = task.goal_id;
      const key = goalId != null ? String(goalId) : 'general';
      if (!groups[key]) {
        const goal = goalId != null ? goalMap.get(goalId) : null;
        groups[key] = {
          title: goal ? (GOAL_TYPE_LABELS[goal.goal_type] || goal.title) : 'General Wellness',
          style: goal ? (GOAL_TYPE_STYLES[goal.goal_type] || DEFAULT_STYLE) : DEFAULT_STYLE,
          tasks: [],
        };
      }
      groups[key].tasks.push(task);
    }

    const entries = Object.entries(groups);
    entries.sort(([a], [b]) => {
      if (a === 'general') return 1;
      if (b === 'general') return -1;
      const goalA = goalMap.get(Number(a));
      const goalB = goalMap.get(Number(b));
      return (goalA?.priority ?? 5) - (goalB?.priority ?? 5);
    });

    return entries.map(([, group]) => group);
  }, [todaySnapshot, goals]);

  const hasTodayTasks = ((todaySnapshot?.tasks ?? []).filter((t) => t.status !== 'skipped').length) > 0;
  const isLoading = loadingGoals || loadingPlan;

  const frameworkGroups = useMemo(
    () => frameworkEducation?.grouped || {},
    [frameworkEducation?.grouped],
  );

  // Goal-matching helpers for framework alignment highlighting
  const normalizeMatch = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  const matchGoalTerm = (goal: string, term: string) => {
    const g = normalizeMatch(goal);
    const t = normalizeMatch(term);
    return Boolean(g && t && (g.includes(t) || t.includes(g)));
  };
  const itemSupportsGoals = useCallback((item: FrameworkItem): boolean => {
    const supports = (item.metadata?.supports as string[]) || [];
    return supports.some(term => healthGoalsTags.some(goal => matchGoalTerm(goal, term)));
  }, [healthGoalsTags]);

  // Tooltip state for framework chips
  const [tooltipItemId, setTooltipItemId] = useState<number | null>(null);

  const launchGoalSettingChat = useCallback(() => {
    const prompt = buildGoalKickoffPrompt({
      goals,
      isOnboarding,
      displayName,
    });
    navigate('/chat', {
      state: {
        chatFill: prompt,
        autoSend: true,
        goalSettingMode: true,
        chatFillNonce: Date.now(),
      },
    });
  }, [displayName, goals, isOnboarding, navigate]);

  const handleGoalCheckIn = useCallback((goal: UserGoal) => {
    if (goal.target_value == null) {
      launchGoalSettingChat();
      return;
    }
    setChatTitle(goal.title);
    setChatDesc(goal.description || '');
    setChatInitialMessage(
      `Goal check-in: ${goal.title}${goal.description ? ` — ${goal.description}` : ''}`
    );
    setChatOpen(true);
  }, [launchGoalSettingChat]);

  const motLine = useMemo(
    () => motivationalLine(goals, stats, streak),
    [goals, stats, streak],
  );

  return (
    <div className="min-h-screen bg-slate-900">
      <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
        {/* ── Header with Motivation ── */}
        <div className="space-y-2">
          <h1 className="text-2xl font-bold text-slate-100">{greetingFor(displayName)}</h1>
          <p className="text-sm text-slate-400">{motLine}</p>
          <div className="flex items-center gap-2.5 text-sm text-slate-400 flex-wrap">
            <span>{today}</span>
            {stats && (
              <span className="bg-slate-800 border border-slate-700 rounded-full px-2.5 py-0.5 text-xs">
                {stats.completed}/{stats.total} tasks
              </span>
            )}
            {streak > 0 && (
              <span className="bg-emerald-900/40 border border-emerald-700/40 text-emerald-300 rounded-full px-2.5 py-0.5 text-xs font-medium">
                {streak}-day streak
              </span>
            )}
          </div>
        </div>

        {/* ── Onboarding Wizard ── */}
        {showOnboarding && frameworkEducation && (
          <div className="rounded-xl border border-emerald-700/40 bg-emerald-950/10 p-4 space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold text-slate-100">Set Up Your Plan</h2>
                <p className="text-xs text-slate-400 mt-1">
                  Step {onboardingStep} of 3: choose frameworks, confirm targets, then start.
                </p>
              </div>
              <button
                type="button"
                onClick={closeOnboarding}
                className="px-2.5 py-1 text-xs rounded-md border border-slate-600 text-slate-300 hover:bg-slate-700 transition-colors"
              >
                Skip for now
              </button>
            </div>

            {onboardingStep === 1 && (
              <div className="space-y-3">
                <p className="text-sm text-slate-300">
                  Select the strategies you want active. You can change this later in Settings.
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {Object.entries(frameworkEducation.framework_types).map(([frameworkType, meta]) => {
                    const items = frameworkGroups[frameworkType] || [];
                    return (
                      <div key={frameworkType} className="rounded-lg border border-slate-700 bg-slate-900/40 p-3 space-y-2">
                        <div>
                          <p className="text-sm font-medium text-slate-100">{meta.label}</p>
                          <p className="text-xs text-slate-400">{meta.classifier_label}</p>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {items.map((item) => {
                            const selected = selectedFrameworkIds.includes(item.id);
                            const goalAligned = healthGoalsTags.length > 0 && itemSupportsGoals(item);
                            const hasMeta = item.metadata && (item.metadata.summary || item.metadata.supports);
                            const showTooltip = tooltipItemId === item.id && hasMeta;
                            const supports = (item.metadata?.supports as string[]) || [];
                            const watchOut = (item.metadata?.watch_out_for as string[]) || [];
                            const summary = (item.metadata?.summary as string) || '';
                            return (
                              <div key={item.id} className="relative">
                                <button
                                  type="button"
                                  onClick={() => toggleFrameworkSelection(item.id)}
                                  onMouseEnter={() => hasMeta && setTooltipItemId(item.id)}
                                  onMouseLeave={() => setTooltipItemId(null)}
                                  onFocus={() => hasMeta && setTooltipItemId(item.id)}
                                  onBlur={() => setTooltipItemId(null)}
                                  className={`px-2.5 py-1 text-xs rounded-md border transition-colors flex items-center gap-1 ${
                                    selected
                                      ? goalAligned
                                        ? 'border-emerald-500 bg-emerald-600/20 text-emerald-200 ring-1 ring-amber-400/60'
                                        : 'border-emerald-500 bg-emerald-600/20 text-emerald-200'
                                      : goalAligned
                                        ? 'border-slate-600 text-slate-300 hover:bg-slate-700 ring-1 ring-amber-400/40'
                                        : 'border-slate-600 text-slate-300 hover:bg-slate-700'
                                  }`}
                                >
                                  {goalAligned && (
                                    <span className="text-amber-400 text-[10px]" title="Supports your goals">★</span>
                                  )}
                                  {item.name}
                                </button>
                                {showTooltip && (
                                  <div className="absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 p-3 rounded-lg border border-slate-600 bg-slate-800 shadow-xl text-xs pointer-events-none">
                                    {summary && (
                                      <p className="text-slate-200 mb-2">{summary}</p>
                                    )}
                                    {supports.length > 0 && (
                                      <div className="mb-2">
                                        <p className="text-slate-400 font-medium mb-1">Supports</p>
                                        <div className="flex flex-wrap gap-1">
                                          {supports.map((s) => (
                                            <span
                                              key={s}
                                              className={`px-1.5 py-0.5 rounded text-[10px] ${
                                                healthGoalsTags.some(g => matchGoalTerm(g, s))
                                                  ? 'bg-amber-500/20 text-amber-300 ring-1 ring-amber-400/40'
                                                  : 'bg-slate-700 text-slate-300'
                                              }`}
                                            >
                                              {s}
                                            </span>
                                          ))}
                                        </div>
                                      </div>
                                    )}
                                    {watchOut.length > 0 && (
                                      <div>
                                        <p className="text-slate-400 font-medium mb-1">Watch out for</p>
                                        <div className="flex flex-wrap gap-1">
                                          {watchOut.map((w) => (
                                            <span key={w} className="px-1.5 py-0.5 rounded text-[10px] bg-rose-500/10 text-rose-300">
                                              {w}
                                            </span>
                                          ))}
                                        </div>
                                      </div>
                                    )}
                                    <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-slate-600" />
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="text-xs text-slate-400">
                    Selected: {selectedFrameworkIds.length}
                  </p>
                  <button
                    type="button"
                    onClick={applyFrameworkSelection}
                    disabled={applyingFrameworks}
                    className="px-3 py-1.5 text-xs rounded-md bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-50 transition-colors"
                  >
                    {applyingFrameworks ? 'Applying...' : 'Apply Selection'}
                  </button>
                </div>
              </div>
            )}

            {onboardingStep === 2 && (
              <div className="space-y-3">
                <p className="text-sm text-slate-300">
                  Your plan targets. Daily, weekly, and 30-day goals auto-adjust based on progress.
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
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
                          {preview ? `${Math.round((preview.stats as PlanStats & { completion_ratio?: number }).completion_ratio
                            ? ((preview.stats as PlanStats & { completion_ratio?: number }).completion_ratio ?? 0) * 100
                            : preview.stats.total ? (preview.stats.completed / preview.stats.total) * 100 : 0)}% completion` : 'Loading...'}
                        </p>
                        {topTasks.length === 0 ? (
                          <p className="text-xs text-slate-500">No pending tasks.</p>
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
                    className="px-3 py-1.5 text-xs rounded-md border border-slate-600 text-slate-300 hover:bg-slate-700 transition-colors"
                  >
                    Back
                  </button>
                  <button
                    type="button"
                    onClick={() => setOnboardingStep(3)}
                    className="px-3 py-1.5 text-xs rounded-md bg-emerald-600 hover:bg-emerald-500 text-white transition-colors"
                  >
                    Looks Good
                  </button>
                </div>
              </div>
            )}

            {onboardingStep === 3 && (
              <div className="space-y-3">
                <p className="text-sm text-slate-300">
                  You're all set. Start with today's top tasks or jump into coaching.
                </p>
                <div className="flex flex-wrap items-center justify-end gap-2">
                  <button
                    type="button"
                    onClick={closeOnboarding}
                    className="px-3 py-1.5 text-xs rounded-md border border-slate-600 text-slate-300 hover:bg-slate-700 transition-colors"
                  >
                    Review goals below
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      closeOnboarding();
                      navigate('/chat');
                    }}
                    className="px-3 py-1.5 text-xs rounded-md bg-emerald-600 hover:bg-emerald-500 text-white transition-colors"
                  >
                    Start coaching
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Goal Hero Cards ── */}
        {!loadingGoals && (
          goals.length > 0 ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">Your Goals</h2>
                <button
                  onClick={launchGoalSettingChat}
                  className="px-2.5 py-1 text-xs rounded-md border border-slate-700 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-slate-100 transition-colors"
                >
                  Refine with coach
                </button>
              </div>
              <div className="space-y-3">
                {goals.map((goal) => (
                  <GoalHeroCard key={goal.id} goal={convertGoalUnits(goal, weightUnit)} onCheckIn={handleGoalCheckIn} />
                ))}
              </div>
            </div>
          ) : (
            <div className="bg-gradient-to-br from-slate-800/80 to-slate-800/40 border border-slate-700/60 rounded-xl p-8 text-center space-y-4">
              {isOnboarding ? (
                <>
                  <div className="w-12 h-12 mx-auto rounded-full bg-emerald-900/30 border border-emerald-700/30 flex items-center justify-center">
                    <svg className="w-6 h-6 text-emerald-400" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M10 3l2 4.5 5 .7-3.6 3.5.8 5L10 14.3 5.8 16.7l.8-5L3 8.2l5-.7L10 3z" />
                    </svg>
                  </div>
                  <h3 className="text-lg font-semibold text-slate-100">Let's set your goals</h3>
                  <p className="text-sm text-slate-400 max-w-sm mx-auto leading-relaxed">
                    Your coach will help you pick 1-3 focused health goals and build a personalized daily plan around them.
                  </p>
                  <button
                    onClick={launchGoalSettingChat}
                    className="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium rounded-lg transition-colors"
                  >
                    Start goal-setting with coach
                  </button>
                </>
              ) : (
                <>
                  <div className="w-12 h-12 mx-auto rounded-full bg-slate-700/50 border border-slate-600/50 flex items-center justify-center">
                    <svg className="w-6 h-6 text-slate-400" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M10 3l2 4.5 5 .7-3.6 3.5.8 5L10 14.3 5.8 16.7l.8-5L3 8.2l5-.7L10 3z" />
                    </svg>
                  </div>
                  <h3 className="text-lg font-semibold text-slate-100">Your journey starts with a goal</h3>
                  <p className="text-sm text-slate-400 max-w-sm mx-auto leading-relaxed">
                    Tell your coach what matters most to you and they'll build a plan around it.
                  </p>
                  <button
                    onClick={launchGoalSettingChat}
                    className="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium rounded-lg transition-colors"
                  >
                    Set goals with coach
                  </button>
                </>
              )}
            </div>
          )
        )}

        {/* ── Weekly / Monthly Context ── */}
        {!loadingPlan && rolling && (
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: 'Weekly', pct: weeklyPct },
              { label: 'Rolling 30-day', pct: monthlyPct },
            ].map(({ label, pct }) => (
              <div key={label} className="bg-slate-800/40 border border-slate-700/40 rounded-xl px-4 py-3 flex items-center gap-3">
                <ProgressRing pct={pct} color="rgb(52,211,153)" size={36} />
                <div className="min-w-0">
                  <p className="text-[11px] uppercase tracking-wide text-slate-500">{label}</p>
                  <p className="text-sm font-medium text-slate-100">{pct}% complete</p>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ── Plan Timeline ── */}
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">Plan timeline</h2>
            <div className="inline-flex rounded-lg border border-slate-700 bg-slate-900 p-0.5">
              <button
                className={`px-3 py-1 text-xs rounded-md transition-colors ${
                  viewMode === 'today' ? 'bg-emerald-600 text-white' : 'text-slate-300 hover:bg-slate-800'
                }`}
                onClick={() => setViewMode('today')}
              >
                Today
              </button>
              <button
                className={`px-3 py-1 text-xs rounded-md transition-colors ${
                  viewMode === 'next5' ? 'bg-emerald-600 text-white' : 'text-slate-300 hover:bg-slate-800'
                }`}
                onClick={() => setViewMode('next5')}
              >
                Next 5
              </button>
            </div>
          </div>

          {isLoading && (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-16 bg-slate-800/40 rounded-xl animate-pulse" />
              ))}
            </div>
          )}

          {!isLoading && viewMode === 'today' && !hasTodayTasks && (
            <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-6 text-center space-y-3">
              <p className="text-slate-400 text-sm">No tasks for today yet.</p>
              <button
                onClick={() => navigate('/chat')}
                className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium rounded-lg transition-colors"
              >
                Chat with coach
              </button>
            </div>
          )}

          {!isLoading && viewMode === 'today' && hasTodayTasks && (
            <div className="space-y-4">
              {goalTaskGroups ? (
                goalTaskGroups.map((group, i) => (
                  <GoalTaskGroup
                    key={i}
                    goalTitle={group.title}
                    goalStyle={group.style}
                    tasks={group.tasks}
                    onChat={handleChat}
                  />
                ))
              ) : (
                TIME_BLOCKS.map((block) => (
                  <TimeBlock key={block.key} block={block} tasks={todayTasksByTime[block.key] || []} onChat={handleChat} />
                ))
              )}
            </div>
          )}

          {!isLoading && viewMode === 'next5' && (
            <div className="space-y-3">
              {(rolling?.days ?? []).map((daySnapshot) => (
                <DayPlanCard key={daySnapshot.cycle.today} snapshot={daySnapshot} onChat={handleChat} />
              ))}
            </div>
          )}
        </div>

        {/* ── Footer Links ── */}
        <div className="flex flex-wrap gap-2 pt-2">
          <button
            onClick={() => navigate('/chat')}
            className="px-3 py-1.5 text-xs text-slate-400 border border-slate-700 rounded-lg hover:bg-slate-800 hover:text-slate-200 transition-colors"
          >
            Open coach chat
          </button>
          <button
            onClick={() => navigate('/plan')}
            className="px-3 py-1.5 text-xs text-slate-400 border border-slate-700 rounded-lg hover:bg-slate-800 hover:text-slate-200 transition-colors"
          >
            Plan calendar
          </button>
        </div>
      </div>

      {chatOpen && (
        <GoalChatPanel
          open={chatOpen}
          onClose={handleChatClose}
          taskTitle={chatTitle}
          taskDescription={chatDesc}
          initialMessage={chatInitialMessage}
          onTaskUpdated={handleTaskUpdated}
        />
      )}
    </div>
  );
}
