import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiClient } from '../api/client';
import { motivationalLine, TIME_BLOCKS } from '../utils/coaching-ui';
import type { GoalLike, PlanStats } from '../utils/coaching-ui';
import { ProgressRing, DomainIcon } from '../utils/coaching-ui-components';

/* ─── Types ─── */

interface CalendarDay {
  date: string;
  total: number;
  completed: number;
  missed: number;
  completion_ratio: number;
  is_past: boolean;
  is_today: boolean;
}

interface CalendarData {
  start: string;
  end: string;
  days: CalendarDay[];
}

interface PlanTask {
  id: number;
  title: string;
  description: string | null;
  domain: string;
  status: string;
  progress_pct: number;
  time_of_day: string;
  priority_score: number;
  target_value: number | null;
  target_unit: string | null;
  framework_name: string | null;
}

interface PlanSnapshot {
  cycle: { cycle_type: string; start: string; end: string; today: string };
  stats: PlanStats;
  reward: { completed_daily_streak: number; points_30d: number };
  tasks: PlanTask[];
  notifications: PlanNotification[];
  adjustments: PlanAdjustment[];
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
  title: string;
  rationale: string;
  status: string;
  applied_at: string | null;
  undo_available: boolean;
}

interface FrameworkEducation {
  framework_types: Record<
    string,
    { label: string; classifier_label: string; description?: string; examples?: string[] }
  >;
  grouped: Record<string, { id: number; name: string; is_active: boolean }[]>;
}

interface UserGoal extends GoalLike {
  id: number;
  status: string;
  priority: number;
}

/* ─── Helpers ─── */

function toIsoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function formatDateLabel(isoDate: string): string {
  return new Date(`${isoDate}T00:00:00`).toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'short',
    day: 'numeric',
  });
}

function monthLabel(year: number, month: number): string {
  return new Date(year, month, 1).toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
}

/* ─── SVG Icons ─── */

function StatusIcon({ status }: { status: string }) {
  if (status === 'completed') {
    return (
      <svg width="16" height="16" viewBox="0 0 20 20" className="text-emerald-400 shrink-0">
        <circle cx="10" cy="10" r="9" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M6 10.5l2.5 2.5 5.5-5.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (status === 'missed') {
    return (
      <svg width="16" height="16" viewBox="0 0 20 20" className="text-rose-400/60 shrink-0">
        <circle cx="10" cy="10" r="9" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M7 7l6 6M13 7l-6 6" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  }
  if (status === 'skipped') {
    return (
      <svg width="16" height="16" viewBox="0 0 20 20" className="text-amber-400/60 shrink-0">
        <circle cx="10" cy="10" r="9" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M7 10h6" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg width="16" height="16" viewBox="0 0 20 20" className="text-slate-500 shrink-0">
      <circle cx="10" cy="10" r="9" fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

function ChevronLeft() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M15 18l-6-6 6-6" />
    </svg>
  );
}

function ChevronRight() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 18l6-6-6-6" />
    </svg>
  );
}

/* ─── Notification category colors ─── */

const NOTIF_BORDER: Record<string, string> = {
  goal: 'border-l-emerald-500',
  streak: 'border-l-amber-500',
  missed: 'border-l-rose-500',
  adjustment: 'border-l-blue-500',
  reminder: 'border-l-sky-500',
};

/* ─── Calendar Grid ─── */

const WEEKDAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'];

function CalendarGrid({
  data,
  currentMonth,
  selectedDate,
  onSelectDate,
}: {
  data: CalendarData;
  currentMonth: { year: number; month: number };
  selectedDate: string | null;
  onSelectDate: (date: string) => void;
}) {
  const dayMap = useMemo(() => new Map(data.days.map((d) => [d.date, d])), [data.days]);

  const cells = useMemo(() => {
    const firstDay = new Date(currentMonth.year, currentMonth.month, 1);
    const startOffset = (firstDay.getDay() + 6) % 7;
    const gridStart = new Date(firstDay);
    gridStart.setDate(gridStart.getDate() - startOffset);

    const result: Array<{ date: string; dayNum: number; inMonth: boolean; day: CalendarDay | undefined }> = [];
    for (let i = 0; i < 42; i++) {
      const d = new Date(gridStart);
      d.setDate(gridStart.getDate() + i);
      const iso = toIsoDate(d);
      result.push({
        date: iso,
        dayNum: d.getDate(),
        inMonth: d.getMonth() === currentMonth.month && d.getFullYear() === currentMonth.year,
        day: dayMap.get(iso),
      });
    }

    while (result.length > 35 && result.slice(-7).every((c) => !c.inMonth)) {
      result.splice(-7, 7);
    }

    return result;
  }, [currentMonth, dayMap]);

  function cellColor(cell: typeof cells[0]): string {
    if (!cell.inMonth) return '';
    const d = cell.day;
    if (!d || d.total === 0) return '';
    if (d.completion_ratio >= 1) return 'bg-emerald-500/20';
    if (d.completed > 0) return 'bg-amber-500/15';
    if (d.is_past) return 'bg-rose-500/10';
    return '';
  }

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800/60 p-3">
      <div className="grid grid-cols-7 gap-1 mb-1">
        {WEEKDAYS.map((wd) => (
          <div key={wd} className="text-center text-[10px] font-semibold uppercase tracking-wider text-slate-500 py-1">
            {wd}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {cells.map((cell) => {
          const isSelected = cell.date === selectedDate;
          const isToday = cell.day?.is_today ?? false;
          const hasTasks = (cell.day?.total ?? 0) > 0;

          return (
            <button
              key={cell.date}
              type="button"
              onClick={() => cell.inMonth && onSelectDate(cell.date)}
              disabled={!cell.inMonth}
              className={`
                relative aspect-square flex flex-col items-center justify-center rounded-lg text-sm transition-all
                ${!cell.inMonth ? 'text-slate-700 cursor-default' : 'cursor-pointer hover:bg-slate-700/50'}
                ${cell.inMonth ? cellColor(cell) : ''}
                ${isSelected ? 'ring-2 ring-emerald-400 bg-emerald-600/15' : ''}
                ${isToday && !isSelected ? 'ring-2 ring-emerald-400/60 font-bold' : ''}
              `}
            >
              <span className={`${cell.inMonth ? 'text-slate-200' : 'text-slate-700'} ${isToday ? 'font-bold text-emerald-300' : ''}`}>
                {cell.dayNum}
              </span>
              {cell.inMonth && hasTasks && (
                <div className="flex gap-0.5 mt-0.5">
                  <span className={`w-1 h-1 rounded-full ${
                    (cell.day?.completion_ratio ?? 0) >= 1 ? 'bg-emerald-400' :
                    (cell.day?.completed ?? 0) > 0 ? 'bg-amber-400' :
                    cell.day?.is_past ? 'bg-rose-400/60' : 'bg-slate-500'
                  }`} />
                </div>
              )}
            </button>
          );
        })}
      </div>

      {/* Calendar Legend */}
      <div className="flex items-center gap-4 mt-3 pt-2 border-t border-slate-700/50">
        <div className="flex items-center gap-1.5 text-[10px] text-slate-400">
          <span className="w-2.5 h-2.5 rounded-sm bg-emerald-500/25 border border-emerald-500/40" />
          All done
        </div>
        <div className="flex items-center gap-1.5 text-[10px] text-slate-400">
          <span className="w-2.5 h-2.5 rounded-sm bg-amber-500/20 border border-amber-500/40" />
          Partial
        </div>
        <div className="flex items-center gap-1.5 text-[10px] text-slate-400">
          <span className="w-2.5 h-2.5 rounded-sm bg-rose-500/15 border border-rose-500/40" />
          Missed
        </div>
      </div>
    </div>
  );
}

/* ─── Day Detail Panel ─── */

function DayDetail({
  snapshot,
  dateStr,
  loading,
}: {
  snapshot: PlanSnapshot | null;
  dateStr: string;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="rounded-xl border border-slate-700 bg-slate-800/60 p-4">
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-8 bg-slate-700/40 rounded-lg animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (!snapshot) return null;

  const tasks = snapshot.tasks.filter((t) => t.status !== 'skipped');
  const dayPct = snapshot.stats.total > 0
    ? Math.round((snapshot.stats.completed / snapshot.stats.total) * 100)
    : 0;

  // Group tasks by time_of_day
  const grouped = new Map<string, PlanTask[]>();
  for (const block of TIME_BLOCKS) {
    grouped.set(block.key, []);
  }
  for (const task of tasks) {
    const key = grouped.has(task.time_of_day) ? task.time_of_day : 'anytime';
    grouped.get(key)!.push(task);
  }

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800/60 p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-100">{formatDateLabel(dateStr)}</h3>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-400">
            {snapshot.stats.completed}/{snapshot.stats.total} completed
          </span>
          <ProgressRing pct={dayPct} color="#34d399" size={32} />
        </div>
      </div>

      {tasks.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 py-6">
          <div className="w-10 h-10 rounded-full bg-slate-700/50 flex items-center justify-center text-slate-500">
            <svg className="w-5 h-5" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10 3l2 4.5 5 .7-3.6 3.5.8 5L10 14.3 5.8 16.7l.8-5L3 8.2l5-.7L10 3z" />
            </svg>
          </div>
          <p className="text-sm text-slate-500">No tasks for this day.</p>
          <p className="text-xs text-slate-600">Tasks appear once your coach generates a plan.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {TIME_BLOCKS.map((block) => {
            const blockTasks = grouped.get(block.key) || [];
            if (blockTasks.length === 0) return null;
            return (
              <div key={block.key}>
                <h4 className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">
                  {block.label}
                </h4>
                <div className="space-y-1.5">
                  {blockTasks.map((task) => (
                    <div key={task.id} className="flex items-start gap-2.5 py-2 px-2 rounded-lg hover:bg-slate-700/20 transition-colors">
                      <StatusIcon status={task.status} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <DomainIcon domain={task.domain} className="text-slate-500 shrink-0" />
                          <p className={`text-sm ${task.status === 'completed' ? 'text-slate-500 line-through' : 'text-slate-200'}`}>
                            {task.title}
                          </p>
                        </div>
                        <div className="flex items-center gap-2 mt-0.5">
                          {task.framework_name && (
                            <span className="text-[10px] text-cyan-400/70">{task.framework_name}</span>
                          )}
                          {task.target_value != null && task.target_unit && (
                            <span className="text-[10px] text-slate-500">
                              {task.target_value} {task.target_unit}
                            </span>
                          )}
                        </div>
                        {task.progress_pct > 0 && task.status !== 'completed' && (
                          <div className="mt-1.5 flex items-center gap-2">
                            <div className="flex-1 h-1 rounded-full bg-slate-700 overflow-hidden">
                              <div
                                className="h-full rounded-full bg-emerald-500/70 transition-all duration-500"
                                style={{ width: `${Math.min(task.progress_pct, 100)}%` }}
                              />
                            </div>
                            <span className="text-[10px] text-slate-500">{Math.round(task.progress_pct)}%</span>
                          </div>
                        )}
                      </div>
                      {task.status === 'completed' && task.progress_pct > 0 && (
                        <span className="text-[10px] text-emerald-400 shrink-0">{Math.round(task.progress_pct)}%</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ─── Sidebar Panels ─── */

function NotificationsPanel({
  notifications,
  onMarkRead,
}: {
  notifications: PlanNotification[];
  onMarkRead: (id: number) => void;
}) {
  const unread = notifications.filter((n) => !n.is_read);

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800/60 p-4 space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-100">Notifications</h2>
        {unread.length > 0 && (
          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-600 text-white">
            {unread.length}
          </span>
        )}
      </div>
      {unread.length === 0 ? (
        <div className="flex flex-col items-center gap-1.5 py-4">
          <svg className="w-6 h-6 text-slate-600" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M6 10.5l2.5 2.5 5.5-5.5" />
          </svg>
          <p className="text-xs text-slate-500">You're all caught up.</p>
        </div>
      ) : (
        <div className="space-y-2 max-h-[200px] overflow-y-auto">
          {unread.slice(0, 5).map((n) => (
            <button
              key={n.id}
              type="button"
              onClick={() => onMarkRead(n.id)}
              className={`w-full text-left rounded-lg border border-slate-700/50 border-l-[3px] ${
                NOTIF_BORDER[n.category] || 'border-l-slate-500'
              } bg-slate-900/40 px-3 py-2 hover:border-slate-600 transition-colors`}
            >
              <p className="text-xs font-medium text-slate-100">{n.title}</p>
              <p className="text-[11px] text-slate-400 mt-0.5">{n.message}</p>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function AdjustmentsPanel({
  adjustments,
  onUndo,
}: {
  adjustments: PlanAdjustment[];
  onUndo: (id: number) => void;
}) {
  return (
    <div className="rounded-xl border border-blue-800/30 bg-blue-950/10 p-4 space-y-2">
      <h2 className="text-sm font-semibold text-slate-100">Auto Adjustments</h2>
      {adjustments.length === 0 ? (
        <div className="flex flex-col items-center gap-1.5 py-4">
          <svg className="w-6 h-6 text-slate-600" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 10h12M10 4v12" />
          </svg>
          <p className="text-xs text-slate-500 text-center">No auto-adjustments yet — these appear as your coach fine-tunes your plan.</p>
        </div>
      ) : (
        <div className="space-y-2 max-h-[200px] overflow-y-auto">
          {adjustments.map((adj) => (
            <div key={adj.id} className="rounded-lg border border-blue-800/20 bg-slate-900/40 px-3 py-2">
              <p className="text-xs font-medium text-slate-100">{adj.title}</p>
              <p className="text-[11px] text-slate-400 mt-0.5">{adj.rationale}</p>
              {adj.undo_available && (
                <button
                  type="button"
                  onClick={() => onUndo(adj.id)}
                  className="mt-1.5 px-2 py-0.5 text-[11px] rounded border border-slate-600 text-slate-200 hover:bg-slate-700 transition-colors"
                >
                  Undo
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function FrameworkPanel({ education }: { education: FrameworkEducation }) {
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800/60 p-4 space-y-2">
      <h2 className="text-sm font-semibold text-slate-100">Frameworks</h2>
      <div className="space-y-1.5">
        {Object.entries(education.framework_types).map(([key, value]) => (
          <details key={key} className="rounded-lg border border-slate-700/50 bg-slate-900/40 px-3 py-2">
            <summary className="text-xs text-slate-200 cursor-pointer">{value.label}</summary>
            <p className="text-[11px] text-slate-400 mt-1.5">{value.description || 'No description.'}</p>
            {!!value.examples?.length && (
              <p className="text-[10px] text-slate-500 mt-1">Examples: {value.examples.join(', ')}</p>
            )}
          </details>
        ))}
      </div>
    </div>
  );
}

/* ─── Main Component ─── */

export default function Plan() {
  const [currentMonth, setCurrentMonth] = useState(() => {
    const now = new Date();
    return { year: now.getFullYear(), month: now.getMonth() };
  });
  const [calendarData, setCalendarData] = useState<CalendarData | null>(null);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [daySnapshot, setDaySnapshot] = useState<PlanSnapshot | null>(null);
  const [loadingCalendar, setLoadingCalendar] = useState(true);
  const [loadingDay, setLoadingDay] = useState(false);
  const [frameworkEducation, setFrameworkEducation] = useState<FrameworkEducation | null>(null);
  const [error, setError] = useState('');
  const [todaySnapshot, setTodaySnapshot] = useState<PlanSnapshot | null>(null);
  const [goals, setGoals] = useState<UserGoal[]>([]);

  const fetchCalendar = useCallback(async (year: number, month: number) => {
    setLoadingCalendar(true);
    setError('');
    const start = new Date(year, month, 1);
    const end = new Date(year, month + 1, 0);
    const startStr = toIsoDate(start);
    const endStr = toIsoDate(end);

    try {
      const [cal, fw, snap, goalsData] = await Promise.all([
        apiClient.get<CalendarData>(`/api/plan/calendar?start=${startStr}&end=${endStr}`),
        apiClient.get<FrameworkEducation>('/api/plan/framework-education'),
        apiClient.get<PlanSnapshot>(`/api/plan/snapshot/day?date=${toIsoDate(new Date())}`).catch(() => null),
        apiClient.get<UserGoal[]>('/api/goals?status=active').catch(() => [] as UserGoal[]),
      ]);
      setCalendarData(cal);
      setFrameworkEducation(fw);
      setTodaySnapshot(snap);
      setGoals(goalsData);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load calendar.');
    } finally {
      setLoadingCalendar(false);
    }
  }, []);

  useEffect(() => {
    void fetchCalendar(currentMonth.year, currentMonth.month);
  }, [currentMonth, fetchCalendar]);

  const selectDate = useCallback(async (dateStr: string) => {
    if (dateStr === selectedDate) {
      setSelectedDate(null);
      setDaySnapshot(null);
      return;
    }
    setSelectedDate(dateStr);
    setLoadingDay(true);
    try {
      const snap = await apiClient.get<PlanSnapshot>(`/api/plan/snapshot/day?date=${dateStr}`);
      setDaySnapshot(snap);
    } catch {
      setDaySnapshot(null);
    } finally {
      setLoadingDay(false);
    }
  }, [selectedDate]);

  const markNotificationRead = useCallback(async (id: number) => {
    try {
      await apiClient.post(`/api/plan/notifications/${id}/read`, {});
      if (selectedDate) {
        const snap = await apiClient.get<PlanSnapshot>(`/api/plan/snapshot/day?date=${selectedDate}`);
        setDaySnapshot(snap);
      }
    } catch {
      // no-op
    }
  }, [selectedDate]);

  const undoAdjustment = useCallback(async (id: number) => {
    setError('');
    try {
      await apiClient.post(`/api/plan/adjustments/${id}/undo`, {});
      void fetchCalendar(currentMonth.year, currentMonth.month);
      if (selectedDate) {
        const snap = await apiClient.get<PlanSnapshot>(`/api/plan/snapshot/day?date=${selectedDate}`);
        setDaySnapshot(snap);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to undo adjustment.');
    }
  }, [currentMonth, selectedDate, fetchCalendar]);

  const prevMonth = useCallback(() => {
    setCurrentMonth((prev) => {
      const m = prev.month - 1;
      return m < 0 ? { year: prev.year - 1, month: 11 } : { year: prev.year, month: m };
    });
    setSelectedDate(null);
    setDaySnapshot(null);
  }, []);

  const nextMonth = useCallback(() => {
    setCurrentMonth((prev) => {
      const m = prev.month + 1;
      return m > 11 ? { year: prev.year + 1, month: 0 } : { year: prev.year, month: m };
    });
    setSelectedDate(null);
    setDaySnapshot(null);
  }, []);

  const notifications = useMemo(() => daySnapshot?.notifications || [], [daySnapshot]);
  const adjustments = useMemo(() => daySnapshot?.adjustments || [], [daySnapshot]);

  const todayStats = todaySnapshot?.stats;
  const todayStreak = todaySnapshot?.reward?.completed_daily_streak ?? 0;

  if (loadingCalendar && !calendarData) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-3.5rem)]">
        <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-4">
      {/* ─── Header with stats + streak ─── */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Plan</h1>
          {todayStats && todayStats.total > 0 && (
            <p className="text-sm text-slate-300 mt-1">
              {motivationalLine(goals, todayStats, todayStreak)}
            </p>
          )}
        </div>
        <div className="flex items-center gap-3">
          {/* Today's stats pill */}
          {todayStats && todayStats.total > 0 && (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-800 border border-slate-700">
              <span className="text-xs text-slate-300 font-medium">
                {todayStats.completed}/{todayStats.total} today
              </span>
              {todayStreak > 0 && (
                <span className="flex items-center gap-1 text-amber-400">
                  <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path d="M10 2c0 4-4 6-4 10a4 4 0 0 0 8 0c0-4-4-6-4-10z" /></svg>
                  <span className="text-xs font-semibold">{todayStreak}</span>
                </span>
              )}
            </div>
          )}

          {/* Month navigation */}
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={prevMonth}
              className="p-1.5 text-slate-400 hover:text-white hover:bg-slate-700 rounded-lg transition-colors"
              aria-label="Previous month"
            >
              <ChevronLeft />
            </button>
            <span className="text-sm font-medium text-slate-100 min-w-[140px] text-center">
              {monthLabel(currentMonth.year, currentMonth.month)}
            </span>
            <button
              type="button"
              onClick={nextMonth}
              className="p-1.5 text-slate-400 hover:text-white hover:bg-slate-700 rounded-lg transition-colors"
              aria-label="Next month"
            >
              <ChevronRight />
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="text-sm text-rose-300 bg-rose-900/20 border border-rose-700/40 rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      {/* Main layout: calendar + sidebar */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-4">
        <div className="space-y-4">
          {calendarData && (
            <CalendarGrid
              data={calendarData}
              currentMonth={currentMonth}
              selectedDate={selectedDate}
              onSelectDate={selectDate}
            />
          )}
          {selectedDate && (
            <DayDetail
              snapshot={daySnapshot}
              dateStr={selectedDate}
              loading={loadingDay}
            />
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-4">
          <NotificationsPanel notifications={notifications} onMarkRead={markNotificationRead} />
          <AdjustmentsPanel adjustments={adjustments} onUndo={undoAdjustment} />
          {frameworkEducation && <FrameworkPanel education={frameworkEducation} />}
        </div>
      </div>
    </div>
  );
}
