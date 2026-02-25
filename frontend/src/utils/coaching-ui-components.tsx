/* ─── Shared Coaching UI Components ─── */

import { RING_CIRCUMFERENCE, GOAL_TYPE_STYLES, DEFAULT_STYLE, goalProgressPct } from './coaching-ui';
import type { GoalLike } from './coaching-ui';

export function ProgressRing({ pct, color, size = 36 }: { pct: number; color: string; size?: number }) {
  const scale = size / 40;
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" className="shrink-0">
      <circle cx="20" cy="20" r="16" fill="none" stroke="rgba(51,65,85,0.6)" strokeWidth="3.5" />
      <circle
        cx="20" cy="20" r="16" fill="none"
        stroke={color}
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeDasharray={`${(Math.min(100, pct) / 100) * RING_CIRCUMFERENCE} ${RING_CIRCUMFERENCE}`}
        transform="rotate(-90 20 20)"
        className="transition-all duration-700"
      />
      <text
        x="20" y="24"
        textAnchor="middle"
        fontSize={scale < 0.8 ? '10' : '9'}
        fill="white"
        fontWeight="600"
      >
        {Math.round(pct)}%
      </text>
    </svg>
  );
}

export function ProgressJourney({ goal }: { goal: GoalLike }) {
  const style = GOAL_TYPE_STYLES[goal.goal_type] || DEFAULT_STYLE;
  const pct = goalProgressPct(goal);
  const hasData = goal.baseline_value != null && goal.target_value != null;

  if (!hasData) {
    return (
      <div className="mt-3">
        <div className="h-2.5 rounded-full bg-slate-700/50" />
        <p className="text-xs text-slate-500 mt-2 italic">
          Target not set yet — refine this goal to start tracking
        </p>
      </div>
    );
  }

  const baseline = goal.baseline_value!;
  const target = goal.target_value!;
  const current = goal.current_value ?? baseline;
  const unit = goal.target_unit || '';

  return (
    <div className="mt-3 space-y-1.5">
      <div className="relative h-2.5 rounded-full bg-slate-700/50 overflow-hidden">
        <div
          className="absolute inset-y-0 left-0 rounded-full transition-all duration-700"
          style={{ width: `${Math.min(100, Math.max(0, pct))}%`, backgroundColor: style.ring }}
        />
        {pct > 2 && pct < 98 && (
          <div
            className="absolute top-1/2 w-3 h-3 rounded-full border-2 border-slate-900 transition-all duration-700"
            style={{
              left: `${Math.min(96, Math.max(2, pct))}%`,
              backgroundColor: style.ring,
              transform: 'translate(-50%, -50%)',
            }}
          />
        )}
      </div>
      <div className="flex items-center justify-between text-[11px]">
        <span className="text-slate-500">{baseline} {unit}</span>
        {current !== baseline && (
          <span className={`font-semibold ${style.text}`}>{current} {unit}</span>
        )}
        <span className="text-slate-500">{target} {unit}</span>
      </div>
    </div>
  );
}

export function GoalTypeIcon({ goalType, className = '' }: { goalType: string; className?: string }) {
  const c = `w-5 h-5 ${className}`;
  switch (goalType) {
    case 'weight_loss':
      return (<svg className={c} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M10 3v14M6 13l4 4 4-4" /></svg>);
    case 'cardiovascular':
      return (<svg className={c} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M10 17s-7-4.5-7-9a4 4 0 0 1 7-2.5A4 4 0 0 1 17 8c0 4.5-7 9-7 9z" /></svg>);
    case 'fitness':
      return (<svg className={c} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M3 10h14M5 7v6M15 7v6M7 5v10M13 5v10" /></svg>);
    case 'metabolic':
      return (<svg className={c} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M10 2c0 4-4 6-4 10a4 4 0 0 0 8 0c0-4-4-6-4-10z" /></svg>);
    case 'energy':
      return (<svg className={c} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M11 2L5 11h5l-1 7 6-9h-5l1-7z" /></svg>);
    case 'sleep':
      return (<svg className={c} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M17 12A7 7 0 1 1 8 3a5 5 0 0 0 9 9z" /></svg>);
    case 'habit':
      return (<svg className={c} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M14 4l-4 4-4-4M14 16l-4-4-4 4M10 8v4" /></svg>);
    default:
      return (<svg className={c} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M10 3l2 4.5 5 .7-3.6 3.5.8 5L10 14.3 5.8 16.7l.8-5L3 8.2l5-.7L10 3z" /></svg>);
  }
}

/* ─── Domain Icons for Plan tasks ─── */

export function DomainIcon({ domain, className = '' }: { domain: string; className?: string }) {
  const c = `w-4 h-4 ${className}`;
  switch (domain) {
    case 'nutrition':
      return (<svg className={c} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M10 2c0 4-4 6-4 10a4 4 0 0 0 8 0c0-4-4-6-4-10z" /></svg>);
    case 'exercise':
      return (<svg className={c} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M3 10h14M5 7v6M15 7v6M7 5v10M13 5v10" /></svg>);
    case 'sleep':
      return (<svg className={c} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M17 12A7 7 0 1 1 8 3a5 5 0 0 0 9 9z" /></svg>);
    case 'supplements':
    case 'medication':
      return (<svg className={c} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="4" width="12" height="12" rx="3" /><path d="M4 10h12M10 4v12" /></svg>);
    case 'hydration':
      return (<svg className={c} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M10 2c-3 5-6 7.5-6 11a6 6 0 0 0 12 0c0-3.5-3-6-6-11z" /></svg>);
    case 'mindfulness':
    case 'stress':
      return (<svg className={c} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="10" cy="10" r="8" /><path d="M10 6v4l2.5 2.5" /></svg>);
    default:
      return (<svg className={c} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M10 3l2 4.5 5 .7-3.6 3.5.8 5L10 14.3 5.8 16.7l.8-5L3 8.2l5-.7L10 3z" /></svg>);
  }
}
