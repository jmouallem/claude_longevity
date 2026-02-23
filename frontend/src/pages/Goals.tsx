import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { apiClient } from '../api/client';
import { useAuthStore } from '../stores/authStore';
import GoalChatPanel from '../components/GoalChatPanel';

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
}

interface PlanStats {
  total: number;
  completed: number;
  pending: number;
  missed?: number;
}

interface PlanSnapshot {
  cycle: { today: string; start: string; end: string; cycle_type: string };
  stats: PlanStats;
  reward: { completed_daily_streak: number };
  tasks: PlanTask[];
}

interface RollingSnapshot {
  timezone?: string | null;
  start_date: string;
  window_days: number;
  days: PlanSnapshot[];
  weekly: { stats: PlanStats };
  monthly: { stats: PlanStats };
}

type ViewMode = 'today' | 'next5';

const TIME_BLOCKS = [
  { key: 'morning', label: 'Morning', badge: 'AM' },
  { key: 'afternoon', label: 'Afternoon', badge: 'PM' },
  { key: 'evening', label: 'Evening', badge: 'PM' },
  { key: 'anytime', label: 'Anytime', badge: 'All' },
];

const GOAL_TYPE_COLORS: Record<string, string> = {
  weight_loss: 'text-orange-400',
  cardiovascular: 'text-rose-400',
  fitness: 'text-blue-400',
  metabolic: 'text-purple-400',
  energy: 'text-yellow-400',
  sleep: 'text-indigo-400',
  habit: 'text-teal-400',
  custom: 'text-emerald-400',
};

function greetingFor(name: string): string {
  const hour = new Date().getHours();
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
  return name ? `${greeting}, ${name}.` : `${greeting}.`;
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
  return [
    `Goal-refinement kickoff${namePart}:`,
    `Please review and refine my existing goals: ${listedGoals}.`,
    'Help me keep only high-value goals, adjust targets/timelines where needed, and update any goal records.',
    'After we finalize changes, remind me to return to the Goals page to review todays timeline.',
  ].join(' ');
}

function formatDateLabel(isoDate: string): string {
  return new Date(`${isoDate}T00:00:00`).toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  });
}

function completionPct(stats: PlanStats | undefined): number {
  if (!stats || !stats.total) return 0;
  return Math.round((stats.completed / stats.total) * 100);
}

function GoalCard({ goal }: { goal: UserGoal }) {
  const pct = goal.progress_pct ?? 0;
  const color = GOAL_TYPE_COLORS[goal.goal_type] || 'text-emerald-400';

  return (
    <div className="flex-shrink-0 w-44 bg-slate-800 border border-slate-700 rounded-xl p-3 space-y-2">
      <p className={`text-xs font-semibold uppercase tracking-wide ${color}`}>{goal.goal_type.replace('_', ' ')}</p>
      <p className="text-sm font-medium text-slate-100 leading-snug line-clamp-2">{goal.title}</p>
      {goal.target_value != null && goal.target_unit && (
        <p className="text-xs text-slate-400">
          {goal.current_value != null ? `${goal.current_value}` : '?'} to {goal.target_value} {goal.target_unit}
        </p>
      )}
      <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div
          className="h-full bg-emerald-500 rounded-full transition-all duration-500"
          style={{ width: `${Math.min(100, pct)}%` }}
        />
      </div>
      <p className="text-xs text-slate-500">{Math.round(pct)}% to goal</p>
      {goal.target_date && <p className="text-xs text-slate-500">by {goal.target_date}</p>}
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
      className={`flex items-center gap-3 py-2.5 px-3 rounded-lg transition-colors ${
        isDone ? 'opacity-60' : isMissed ? 'opacity-40' : 'hover:bg-slate-700/50'
      }`}
    >
      <span className="text-[11px] select-none flex-shrink-0 w-7 text-center text-slate-400">
        {isDone ? '[x]' : isMissed ? '[-]' : '[ ]'}
      </span>

      <div className="flex-1 min-w-0">
        <p className={`text-sm text-slate-200 ${isDone ? 'line-through text-slate-500' : ''}`}>{task.title}</p>
        {task.description && !isDone && <p className="text-xs text-slate-500 mt-0.5 line-clamp-1">{task.description}</p>}
        {task.status === 'pending' && task.progress_pct > 0 && (
          <div className="mt-1 h-0.5 bg-slate-700 rounded-full w-24">
            <div
              className="h-full bg-emerald-500/70 rounded-full"
              style={{ width: `${Math.min(100, task.progress_pct)}%` }}
            />
          </div>
        )}
      </div>

      {!isDone && (
        <button
          onClick={() => onChat(task)}
          className="flex-shrink-0 px-2 py-1 text-xs text-slate-400 hover:text-emerald-400 hover:bg-slate-700 rounded-md transition-colors"
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
  block: { key: string; label: string; badge: string };
  tasks: PlanTask[];
  onChat: (task: PlanTask) => void;
}) {
  if (tasks.length === 0) return null;
  const done = tasks.filter((t) => t.status === 'completed').length;

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2 px-1">
        <span className="inline-flex items-center justify-center rounded-md bg-slate-800 border border-slate-700 text-[10px] text-slate-400 px-1.5 py-0.5">
          {block.badge}
        </span>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">{block.label}</h3>
        <span className="text-xs text-slate-600 ml-auto">
          {done}/{tasks.length}
        </span>
      </div>
      <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 overflow-hidden">
        {tasks.map((task, idx) => (
          <div key={task.id}>
            {idx > 0 && <div className="border-t border-slate-700/30 mx-3" />}
            <TaskRow task={task} onChat={onChat} />
          </div>
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
    <div className="bg-slate-900/60 border border-slate-700 rounded-xl p-3 space-y-3">
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

export default function Goals() {
  const user = useAuthStore((state) => state.user);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const isOnboarding = searchParams.get('onboarding') === '1';

  const [goals, setGoals] = useState<UserGoal[]>([]);
  const [rolling, setRolling] = useState<RollingSnapshot | null>(null);
  const [loadingGoals, setLoadingGoals] = useState(true);
  const [loadingPlan, setLoadingPlan] = useState(true);
  const [viewMode, setViewMode] = useState<ViewMode>('today');

  const [chatOpen, setChatOpen] = useState(false);
  const [chatTask, setChatTask] = useState<PlanTask | null>(null);
  const [chatInitialMessage, setChatInitialMessage] = useState('');

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
      const data = await apiClient.get<RollingSnapshot>('/api/plan/snapshot/rolling?days=5');
      setRolling(data);
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

  const todaySnapshot = rolling?.days?.[0] ?? null;

  const handleChat = useCallback((task: PlanTask) => {
    const dateLabel = task.cycle_start ? formatDateLabel(task.cycle_start) : 'today';
    setChatTask(task);
    setChatInitialMessage(
      `Goal check-in for ${dateLabel}: ${task.title}${task.description ? ` (${task.description})` : ''}`
    );
    setChatOpen(true);
  }, []);

  const handleChatClose = useCallback(() => {
    setChatOpen(false);
    setChatTask(null);
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

  const hasTodayTasks = ((todaySnapshot?.tasks ?? []).filter((t) => t.status !== 'skipped').length) > 0;
  const isLoading = loadingGoals || loadingPlan;

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

  return (
    <div className="min-h-screen bg-slate-900">
      <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
        <div className="space-y-1">
          <h1 className="text-xl font-semibold text-slate-100">{greetingFor(displayName)}</h1>
          <div className="flex items-center gap-3 text-sm text-slate-400 flex-wrap">
            <span>{today}</span>
            {stats && (
              <>
                <span>|</span>
                <span>{stats.completed}/{stats.total} tasks</span>
              </>
            )}
            {streak > 0 && (
              <>
                <span>|</span>
                <span className="text-emerald-400">{streak}-day streak</span>
              </>
            )}
          </div>
        </div>

        {!loadingGoals && (
          goals.length > 0 ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">Your Goals</h2>
                <button
                  onClick={launchGoalSettingChat}
                  className="px-2.5 py-1 text-xs rounded-md border border-slate-700 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-slate-100 transition-colors"
                >
                  Refine with coach
                </button>
              </div>
              <div className="flex gap-3 overflow-x-auto pb-1 -mx-1 px-1 scrollbar-hide">
                {goals.map((goal) => (
                  <GoalCard key={goal.id} goal={goal} />
                ))}
              </div>
            </div>
          ) : (
            <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-5 text-center space-y-3">
              {isOnboarding ? (
                <>
                  <p className="text-slate-200 font-medium">Let's set your goals</p>
                  <p className="text-sm text-slate-400">Tell your coach what you want to achieve and they will build your personalized plan.</p>
                  <button
                    onClick={launchGoalSettingChat}
                    className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium rounded-lg transition-colors"
                  >
                    Start goal-setting with coach
                  </button>
                </>
              ) : (
                <>
                  <p className="text-slate-400 text-sm">No active goals yet.</p>
                  <button
                    onClick={launchGoalSettingChat}
                    className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium rounded-lg transition-colors"
                  >
                    Set goals with coach
                  </button>
                </>
              )}
            </div>
          )
        )}

        {!loadingPlan && rolling && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <div className="bg-slate-800/50 border border-slate-700 rounded-lg px-3 py-2">
              <p className="text-[11px] uppercase tracking-wide text-slate-500">Weekly context</p>
              <p className="text-sm text-slate-100 mt-0.5">{weeklyPct}% complete</p>
            </div>
            <div className="bg-slate-800/50 border border-slate-700 rounded-lg px-3 py-2">
              <p className="text-[11px] uppercase tracking-wide text-slate-500">Rolling 30-day context</p>
              <p className="text-sm text-slate-100 mt-0.5">{monthlyPct}% complete</p>
            </div>
          </div>
        )}

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

          {isLoading && <div className="text-center py-8 text-slate-500 text-sm">Loading your plan...</div>}

          {!isLoading && viewMode === 'today' && !hasTodayTasks && (
            <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-5 text-center space-y-3">
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
              {TIME_BLOCKS.map((block) => (
                <TimeBlock key={block.key} block={block} tasks={todayTasksByTime[block.key] || []} onChat={handleChat} />
              ))}
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
            Full plan
          </button>
        </div>
      </div>

      {chatOpen && chatTask && (
        <GoalChatPanel
          open={chatOpen}
          onClose={handleChatClose}
          taskTitle={chatTask.title}
          taskDescription={chatTask.description}
          initialMessage={chatInitialMessage}
          onTaskUpdated={handleTaskUpdated}
        />
      )}
    </div>
  );
}
