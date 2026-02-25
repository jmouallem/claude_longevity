/* ─── Shared Coaching UI Constants & Helpers ─── */

export interface PlanStats {
  total: number;
  completed: number;
  pending: number;
  missed?: number;
}

export interface GoalLike {
  title: string;
  goal_type: string;
  target_value?: number;
  target_unit?: string;
  baseline_value?: number;
  current_value?: number;
  target_date?: string;
  progress_pct?: number;
}

/* ─── Constants ─── */

export const TIME_BLOCKS = [
  { key: 'morning', label: 'Morning' },
  { key: 'afternoon', label: 'Afternoon' },
  { key: 'evening', label: 'Evening' },
  { key: 'anytime', label: 'Anytime' },
];

export const GOAL_TYPE_LABELS: Record<string, string> = {
  weight_loss: 'Lose Weight',
  cardiovascular: 'Heart Health',
  fitness: 'Get Stronger',
  metabolic: 'Blood Sugar & Metabolism',
  energy: 'More Energy',
  sleep: 'Better Sleep',
  habit: 'Build a Habit',
  custom: 'Personal Goal',
};

export const GOAL_TYPE_STYLES: Record<string, {
  text: string;
  ring: string;
  gradientFrom: string;
  gradientTo: string;
  border: string;
}> = {
  weight_loss:    { text: 'text-orange-400',  ring: '#fb923c', gradientFrom: 'from-orange-950/40',  gradientTo: 'to-slate-800', border: 'border-orange-800/30' },
  cardiovascular: { text: 'text-rose-400',    ring: '#fb7185', gradientFrom: 'from-rose-950/40',    gradientTo: 'to-slate-800', border: 'border-rose-800/30' },
  fitness:        { text: 'text-blue-400',    ring: '#60a5fa', gradientFrom: 'from-blue-950/40',    gradientTo: 'to-slate-800', border: 'border-blue-800/30' },
  metabolic:      { text: 'text-purple-400',  ring: '#c084fc', gradientFrom: 'from-purple-950/40',  gradientTo: 'to-slate-800', border: 'border-purple-800/30' },
  energy:         { text: 'text-yellow-400',  ring: '#facc15', gradientFrom: 'from-yellow-950/40',  gradientTo: 'to-slate-800', border: 'border-yellow-800/30' },
  sleep:          { text: 'text-indigo-400',  ring: '#818cf8', gradientFrom: 'from-indigo-950/40',  gradientTo: 'to-slate-800', border: 'border-indigo-800/30' },
  habit:          { text: 'text-teal-400',    ring: '#2dd4bf', gradientFrom: 'from-teal-950/40',    gradientTo: 'to-slate-800', border: 'border-teal-800/30' },
  custom:         { text: 'text-emerald-400', ring: '#34d399', gradientFrom: 'from-emerald-950/40', gradientTo: 'to-slate-800', border: 'border-emerald-800/30' },
};

export const DEFAULT_STYLE = GOAL_TYPE_STYLES.custom;

export const RING_CIRCUMFERENCE = 2 * Math.PI * 16;

/* ─── Helpers ─── */

export function greetingFor(name: string): string {
  const hour = new Date().getHours();
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
  return name ? `${greeting}, ${name}` : `${greeting}`;
}

export function completionPct(stats: PlanStats | undefined): number {
  if (!stats || !stats.total) return 0;
  return Math.round((stats.completed / stats.total) * 100);
}

export function daysRemaining(targetDate: string): number | null {
  if (!targetDate) return null;
  const target = new Date(`${targetDate}T00:00:00`);
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  return Math.ceil((target.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
}

export function goalProgressPct(goal: GoalLike): number {
  if (goal.progress_pct != null && goal.progress_pct > 0) return goal.progress_pct;
  if (goal.baseline_value == null || goal.target_value == null || goal.current_value == null) return 0;
  const range = goal.target_value - goal.baseline_value;
  if (range === 0) return goal.current_value === goal.target_value ? 100 : 0;
  const progress = goal.current_value - goal.baseline_value;
  return Math.max(0, Math.min(100, Math.round((progress / range) * 100)));
}

export function milestoneMessage(goal: GoalLike): string | null {
  const pct = goalProgressPct(goal);
  if (pct <= 0 || goal.baseline_value == null || goal.current_value == null || goal.target_value == null) return null;

  const change = Math.abs(goal.current_value - goal.baseline_value);
  const unit = goal.target_unit || '';
  const direction = goal.target_value < goal.baseline_value ? 'Down' : 'Up';
  const changeStr = change % 1 === 0 ? change.toString() : change.toFixed(1);

  if (pct >= 100) return `Goal reached! ${direction} ${changeStr} ${unit}`;
  if (pct >= 75) return `Almost there! ${direction} ${changeStr} ${unit} — ${pct}% of the way`;
  if (pct >= 50) return `Halfway! ${direction} ${changeStr} ${unit} — ${pct}% done`;
  if (pct >= 25) return `${direction} ${changeStr} ${unit} — ${pct}% of the way there`;
  return `${direction} ${changeStr} ${unit} — keep going!`;
}

export function motivationalLine(goals: GoalLike[], stats: PlanStats | undefined, streak: number): string {
  if (stats && stats.total > 0 && stats.completed === stats.total) {
    return "You crushed today's goals — well done!";
  }
  if (streak >= 7) return `${streak}-day streak — you're on fire!`;
  if (streak >= 3) return `${streak}-day streak — keep the momentum going!`;

  const goalsWithProgress = goals
    .filter(g => g.target_value != null && goalProgressPct(g) > 0)
    .sort((a, b) => goalProgressPct(b) - goalProgressPct(a));

  if (goalsWithProgress.length > 0) {
    const best = goalsWithProgress[0];
    const pct = goalProgressPct(best);
    const label = GOAL_TYPE_LABELS[best.goal_type] || best.title;
    if (pct >= 50) return `More than halfway to "${label}" — ${pct}% there!`;
    if (pct > 0) return `Making progress on "${label}" — ${pct}% and counting.`;
  }

  if (stats && stats.completed > 0) {
    return `${stats.completed} of ${stats.total} tasks done today. Keep it up!`;
  }

  return "Every small step counts. Here's your plan for today.";
}
