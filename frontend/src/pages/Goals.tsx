import { useCallback, useEffect, useState } from 'react';
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

interface PlanSnapshot {
  cycle: { today: string };
  stats: { total: number; completed: number; pending: number };
  reward: { completed_daily_streak: number };
  tasks: PlanTask[];
}

const TIME_BLOCKS = [
  { key: 'morning', label: 'Morning', icon: '☀️' },
  { key: 'afternoon', label: 'Afternoon', icon: '🌤️' },
  { key: 'evening', label: 'Evening', icon: '🌙' },
  { key: 'anytime', label: 'Anytime', icon: '📋' },
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

function GoalCard({ goal }: { goal: UserGoal }) {
  const pct = goal.progress_pct ?? 0;
  const color = GOAL_TYPE_COLORS[goal.goal_type] || 'text-emerald-400';

  return (
    <div className="flex-shrink-0 w-44 bg-slate-800 border border-slate-700 rounded-xl p-3 space-y-2">
      <p className={`text-xs font-semibold uppercase tracking-wide ${color}`}>{goal.goal_type.replace('_', ' ')}</p>
      <p className="text-sm font-medium text-slate-100 leading-snug line-clamp-2">{goal.title}</p>
      {goal.target_value != null && goal.target_unit && (
        <p className="text-xs text-slate-400">
          {goal.current_value != null ? `${goal.current_value}` : '?'} → {goal.target_value} {goal.target_unit}
        </p>
      )}
      <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div
          className="h-full bg-emerald-500 rounded-full transition-all duration-500"
          style={{ width: `${Math.min(100, pct)}%` }}
        />
      </div>
      <p className="text-xs text-slate-500">{Math.round(pct)}% to goal</p>
      {goal.target_date && (
        <p className="text-xs text-slate-500">by {goal.target_date}</p>
      )}
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
      {/* Status icon */}
      <span className="text-base select-none flex-shrink-0 w-5 text-center">
        {isDone ? '✓' : isMissed ? '✗' : '○'}
      </span>

      {/* Title */}
      <div className="flex-1 min-w-0">
        <p className={`text-sm text-slate-200 ${isDone ? 'line-through text-slate-500' : ''}`}>
          {task.title}
        </p>
        {task.description && !isDone && (
          <p className="text-xs text-slate-500 mt-0.5 line-clamp-1">{task.description}</p>
        )}
        {task.status === 'pending' && task.progress_pct > 0 && (
          <div className="mt-1 h-0.5 bg-slate-700 rounded-full w-24">
            <div
              className="h-full bg-emerald-500/70 rounded-full"
              style={{ width: `${Math.min(100, task.progress_pct)}%` }}
            />
          </div>
        )}
      </div>

      {/* Chat button */}
      {!isDone && (
        <button
          onClick={() => onChat(task)}
          className="flex-shrink-0 px-2 py-1 text-xs text-slate-400 hover:text-emerald-400 hover:bg-slate-700 rounded-md transition-colors"
          title="Check in with coach"
        >
          💬
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
  block: { key: string; label: string; icon: string };
  tasks: PlanTask[];
  onChat: (task: PlanTask) => void;
}) {
  if (tasks.length === 0) return null;
  const done = tasks.filter((t) => t.status === 'completed').length;

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2 px-1">
        <span className="text-sm">{block.icon}</span>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
          {block.label}
        </h3>
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

export default function Goals() {
  const user = useAuthStore((state) => state.user);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const isOnboarding = searchParams.get('onboarding') === '1';

  const [goals, setGoals] = useState<UserGoal[]>([]);
  const [snapshot, setSnapshot] = useState<PlanSnapshot | null>(null);
  const [loadingGoals, setLoadingGoals] = useState(true);
  const [loadingPlan, setLoadingPlan] = useState(true);

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
      const data = await apiClient.get<PlanSnapshot>('/api/plan/snapshot?cycle_type=daily');
      setSnapshot(data);
    } catch {
      setSnapshot(null);
    } finally {
      setLoadingPlan(false);
    }
  }, []);

  useEffect(() => {
    fetchGoals();
    fetchPlan();
  }, [fetchGoals, fetchPlan]);

  const handleChat = useCallback(
    (task: PlanTask) => {
      setChatTask(task);
      setChatInitialMessage(`Goal check-in: ${task.title}${task.description ? ` (${task.description})` : ''}`);
      setChatOpen(true);
    },
    []
  );

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
  const today = snapshot?.cycle?.today
    ? new Date(snapshot.cycle.today + 'T00:00:00').toLocaleDateString('en-US', {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
      })
    : new Date().toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });

  const stats = snapshot?.stats;
  const streak = snapshot?.reward?.completed_daily_streak ?? 0;

  // Group tasks by time_of_day (only daily tasks)
  const dailyTasks = (snapshot?.tasks ?? []).filter(
    (t) => t.status !== 'skipped'
  );

  const tasksByTime: Record<string, PlanTask[]> = { morning: [], afternoon: [], evening: [], anytime: [] };
  for (const task of dailyTasks) {
    const slot = task.time_of_day || 'anytime';
    const key = tasksByTime[slot] ? slot : 'anytime';
    tasksByTime[key].push(task);
  }

  // Sort each block by priority_score desc
  for (const key of Object.keys(tasksByTime)) {
    tasksByTime[key].sort((a, b) => (b.priority_score || 0) - (a.priority_score || 0));
  }

  const hasAnyTasks = dailyTasks.length > 0;
  const isLoading = loadingGoals || loadingPlan;

  return (
    <div className="min-h-screen bg-slate-900">
      <div className="max-w-2xl mx-auto px-4 py-6 space-y-6">

        {/* Header */}
        <div className="space-y-1">
          <h1 className="text-xl font-semibold text-slate-100">
            {greetingFor(displayName)}
          </h1>
          <div className="flex items-center gap-3 text-sm text-slate-400">
            <span>{today}</span>
            {stats && (
              <>
                <span>·</span>
                <span>{stats.completed}/{stats.total} tasks</span>
              </>
            )}
            {streak > 0 && (
              <>
                <span>·</span>
                <span className="text-emerald-400">{streak}-day streak 🔥</span>
              </>
            )}
          </div>
        </div>

        {/* Goals section */}
        {!loadingGoals && (
          goals.length > 0 ? (
            <div className="space-y-2">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">Your Goals</h2>
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
                  <p className="text-sm text-slate-400">
                    Tell your coach what you want to achieve and they'll build your personalized plan.
                  </p>
                  <button
                    onClick={() => navigate('/chat')}
                    className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium rounded-lg transition-colors"
                  >
                    Start goal-setting with coach →
                  </button>
                </>
              ) : (
                <>
                  <p className="text-slate-400 text-sm">No active goals yet.</p>
                  <button
                    onClick={() => navigate('/chat')}
                    className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium rounded-lg transition-colors"
                  >
                    Set goals with coach →
                  </button>
                </>
              )}
            </div>
          )
        )}

        {/* Today's Plan */}
        <div className="space-y-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">Today's Plan</h2>

          {isLoading && (
            <div className="text-center py-8 text-slate-500 text-sm">Loading your plan...</div>
          )}

          {!isLoading && !hasAnyTasks && (
            <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-5 text-center space-y-3">
              <p className="text-slate-400 text-sm">No tasks for today yet.</p>
              <button
                onClick={() => navigate('/chat')}
                className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium rounded-lg transition-colors"
              >
                Chat with coach →
              </button>
            </div>
          )}

          {!isLoading && hasAnyTasks && (
            <div className="space-y-4">
              {TIME_BLOCKS.map((block) => (
                <TimeBlock
                  key={block.key}
                  block={block}
                  tasks={tasksByTime[block.key] || []}
                  onChat={handleChat}
                />
              ))}
            </div>
          )}
        </div>

        {/* Quick links */}
        <div className="flex flex-wrap gap-2 pt-2">
          <button
            onClick={() => navigate('/chat')}
            className="px-3 py-1.5 text-xs text-slate-400 border border-slate-700 rounded-lg hover:bg-slate-800 hover:text-slate-200 transition-colors"
          >
            Open Coach Chat
          </button>
          <button
            onClick={() => navigate('/plan')}
            className="px-3 py-1.5 text-xs text-slate-400 border border-slate-700 rounded-lg hover:bg-slate-800 hover:text-slate-200 transition-colors"
          >
            Full Plan →
          </button>
        </div>
      </div>

      {/* Inline Goal Chat Panel */}
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
