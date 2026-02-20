import { useState, useEffect, useCallback } from 'react';
import { apiClient } from '../api/client';
import FastingTimer from '../components/FastingTimer';
import { kgToLb, mlToOz, round1, type HydrationUnit, type WeightUnit } from '../utils/units';

interface DailyTotals {
  date: string;
  food: {
    calories: number;
    protein_g: number;
    carbs_g: number;
    fat_g: number;
    fiber_g: number;
    sodium_mg: number;
    meal_count: number;
  };
  hydration_ml: number;
  exercise_minutes: number;
  exercise_calories_burned: number;
}

interface Vital {
  logged_at: string;
  weight_kg: number | null;
  bp_systolic: number | null;
  bp_diastolic: number | null;
  heart_rate: number | null;
}

interface ProfileData {
  current_weight_kg: number | null;
  goal_weight_kg: number | null;
  weight_unit: WeightUnit;
  hydration_unit: HydrationUnit;
  medical_conditions: string | null;
}

interface WeightPoint {
  date: string;
  weight_kg: number;
}

interface ExercisePlan {
  target_date: string;
  plan_type: string;
  title: string;
  description: string | null;
  target_minutes: number | null;
  completed: boolean;
  status: string;
  completed_minutes: number;
  matching_sessions: number;
}

interface ChecklistItem {
  name: string;
  dose: string;
  timing: string;
  completed: boolean;
}

interface DailyChecklist {
  target_date: string;
  medications: ChecklistItem[];
  supplements: ChecklistItem[];
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function MacroBar({ protein, carbs, fat }: { protein: number; carbs: number; fat: number }) {
  const total = protein + carbs + fat || 1;
  const pPct = (protein / total) * 100;
  const cPct = (carbs / total) * 100;
  const fPct = (fat / total) * 100;

  return (
    <div className="mt-3">
      <div className="flex h-2.5 rounded-full overflow-hidden bg-slate-700">
        <div className="bg-blue-400" style={{ width: `${pPct}%` }} />
        <div className="bg-amber-400" style={{ width: `${cPct}%` }} />
        <div className="bg-rose-400" style={{ width: `${fPct}%` }} />
      </div>
      <div className="flex justify-between text-xs text-slate-400 mt-1.5">
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-blue-400 inline-block" />
          P {Math.round(protein)}g
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-amber-400 inline-block" />
          C {Math.round(carbs)}g
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-rose-400 inline-block" />
          F {Math.round(fat)}g
        </span>
      </div>
    </div>
  );
}

function MacroTargetsCard({
  protein,
  carbs,
  fat,
  proteinTarget,
  carbsTarget,
  fatTarget,
}: {
  protein: number;
  carbs: number;
  fat: number;
  proteinTarget: number;
  carbsTarget: number;
  fatTarget: number;
}) {
  const macros = [
    { key: 'protein', label: 'P', value: protein, target: proteinTarget, color: 'bg-blue-400' },
    { key: 'carbs', label: 'C', value: carbs, target: carbsTarget, color: 'bg-amber-400' },
    { key: 'fat', label: 'F', value: fat, target: fatTarget, color: 'bg-rose-400' },
  ];

  return (
    <div>
      <div className="flex gap-4">
        <div className="h-32 w-10 relative shrink-0 text-[11px] text-slate-500 mt-6">
          <span className="absolute top-0 -translate-y-1/2 left-0">200%</span>
          <span className="absolute top-1/2 -translate-y-1/2 left-0">100%</span>
          <span className="absolute bottom-0 translate-y-1/2 left-0">0%</span>
        </div>
        <div className="flex-1 flex items-start justify-around gap-4">
        {macros.map((m) => {
          const pct = m.target > 0 ? (m.value / m.target) * 100 : 0;
          const fillPct = Math.min(pct, 200) / 2; // 200% => full bar
          return (
            <div key={m.key} className="flex flex-col items-center gap-2 w-20">
              <div className="relative h-32 w-12 mt-6 rounded-md bg-slate-700 border border-slate-600 overflow-hidden">
                <div className="absolute -top-5 left-1/2 -translate-x-1/2 text-xs text-slate-400">
                  {Math.round(pct)}%
                </div>
                <div
                  className={`absolute left-0 right-0 bottom-0 ${m.color} transition-all duration-500`}
                  style={{ height: `${fillPct}%` }}
                />
                <div className="absolute left-0 right-0 border-t border-slate-300/40" style={{ bottom: '50%' }} />
              </div>
              <div className="text-xs font-medium text-slate-200">{m.label}</div>
              <div className="text-[11px] text-slate-400 text-center leading-tight">
                {Math.round(m.value)}g / {Math.round(m.target)}g
              </div>
            </div>
          );
        })}
        </div>
      </div>
      <div className="mt-2 text-[11px] text-slate-500 pl-10">
        100% target line shown at bar midpoint.
      </div>
    </div>
  );
}

function Card({ title, children, className = '' }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-slate-800 rounded-xl p-5 border border-slate-700 ${className}`}>
      <h3 className="text-sm font-medium text-slate-400 mb-3">{title}</h3>
      {children}
    </div>
  );
}

function formatShortDate(isoDate: string): string {
  const d = new Date(`${isoDate}T00:00:00`);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function toIsoDate(d: Date): string {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

function buildWeightSeries(vitals: Vital[], fromDate: string, toDate: string): WeightPoint[] {
  const byDay = new Map<string, WeightPoint>();
  for (const v of vitals) {
    if (v.weight_kg == null) continue;
    const day = v.logged_at.slice(0, 10);
    byDay.set(day, { date: day, weight_kg: v.weight_kg });
  }

  const series: WeightPoint[] = [];
  let cursor = new Date(`${fromDate}T00:00:00`);
  const end = new Date(`${toDate}T00:00:00`);
  while (cursor <= end) {
    const day = toIsoDate(cursor);
    const point = byDay.get(day);
    if (point) series.push(point);
    cursor = new Date(cursor.getTime() + 86400000);
  }
  return series;
}

function WeightTrendChart({
  points,
  goal,
  unit,
  toDisplay,
  fromDate,
  toDate,
}: {
  points: WeightPoint[];
  goal: number | null;
  unit: WeightUnit;
  toDisplay: (kg: number) => number;
  fromDate: string;
  toDate: string;
}) {
  const width = 210;
  const height = 110;
  const padding = { top: 8, right: 8, bottom: 18, left: 8 };
  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;

  const displayValues = points.map((p) => toDisplay(p.weight_kg));
  const goalDisplay = goal != null ? toDisplay(goal) : null;
  const allValues = goalDisplay != null ? [...displayValues, goalDisplay] : displayValues;

  if (allValues.length === 0) {
    return (
      <div className="h-[130px] rounded-lg border border-slate-700 bg-slate-900/40 flex items-center justify-center text-xs text-slate-500">
        No weight data in last 14 days
      </div>
    );
  }

  const minV = Math.min(...allValues);
  const maxV = Math.max(...allValues);
  const range = Math.max(0.5, maxV - minV);
  const yMin = minV - range * 0.15;
  const yMax = maxV + range * 0.15;

  const startMs = new Date(`${fromDate}T00:00:00`).getTime();
  const endMs = new Date(`${toDate}T00:00:00`).getTime();
  const x = (isoDate: string) => {
    const t = new Date(`${isoDate}T00:00:00`).getTime();
    const ratio = endMs === startMs ? 0 : (t - startMs) / (endMs - startMs);
    return padding.left + ratio * innerW;
  };
  const y = (value: number) => {
    const ratio = (value - yMin) / (yMax - yMin);
    return padding.top + (1 - ratio) * innerH;
  };

  const path = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${x(p.date).toFixed(2)} ${y(toDisplay(p.weight_kg)).toFixed(2)}`)
    .join(' ');

  const goalY = goalDisplay != null ? y(goalDisplay) : null;

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-[110px]">
        <rect x={padding.left} y={padding.top} width={innerW} height={innerH} rx={6} fill="rgba(15,23,42,0.35)" />
        {goalY != null && (
          <g>
            <line
              x1={padding.left}
              y1={goalY}
              x2={padding.left + innerW}
              y2={goalY}
              stroke="rgba(16,185,129,0.75)"
              strokeDasharray="4 3"
              strokeWidth="1.5"
            />
            <text x={padding.left + 4} y={goalY - 4} fontSize="9" fill="rgba(52,211,153,0.95)">
              Goal
            </text>
          </g>
        )}
        {points.length > 1 && <path d={path} fill="none" stroke="rgba(96,165,250,0.95)" strokeWidth="2.5" strokeLinecap="round" />}
        {points.map((p) => (
          <circle key={p.date} cx={x(p.date)} cy={y(toDisplay(p.weight_kg))} r="2.5" fill="rgba(147,197,253,1)" />
        ))}
      </svg>
      <div className="flex items-center justify-between text-[11px] text-slate-500 mt-1">
        <span>{formatShortDate(fromDate)}</span>
        <span>2 weeks</span>
        <span>{formatShortDate(toDate)}</span>
      </div>
      <div className="text-[11px] text-slate-500 mt-1">Unit: {unit}</div>
    </div>
  );
}

function VitalsTrendChart({
  vitals,
  fromDate,
  toDate,
}: {
  vitals: Vital[];
  fromDate: string;
  toDate: string;
}) {
  const width = 300;
  const height = 130;
  const padding = { top: 10, right: 12, bottom: 18, left: 12 };
  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;

  const daily = new Map<string, Vital>();
  for (const v of vitals) {
    const day = v.logged_at.slice(0, 10);
    const current = daily.get(day);
    if (!current || current.logged_at < v.logged_at) daily.set(day, v);
  }
  const points = Array.from(daily.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, v]) => ({
      date,
      sys: v.bp_systolic,
      dia: v.bp_diastolic,
      hr: v.heart_rate,
    }));

  const sysValues = points.map((p) => p.sys).filter((v): v is number => v != null);
  const diaValues = points.map((p) => p.dia).filter((v): v is number => v != null);
  const hrValues = points.map((p) => p.hr).filter((v): v is number => v != null);
  const anySeries = sysValues.length > 0 || diaValues.length > 0 || hrValues.length > 0;
  if (!anySeries) {
    return <p className="text-slate-500 text-sm">No BP/HR data in last 2 weeks</p>;
  }

  const all = [...sysValues, ...diaValues, ...hrValues];
  const minV = Math.min(...all) - 8;
  const maxV = Math.max(...all) + 8;
  const startMs = new Date(`${fromDate}T00:00:00`).getTime();
  const endMs = new Date(`${toDate}T00:00:00`).getTime();
  const x = (isoDate: string) => {
    const t = new Date(`${isoDate}T00:00:00`).getTime();
    const ratio = endMs === startMs ? 0 : (t - startMs) / (endMs - startMs);
    return padding.left + ratio * innerW;
  };
  const y = (value: number) => {
    const ratio = (value - minV) / (maxV - minV || 1);
    return padding.top + (1 - ratio) * innerH;
  };
  const buildPath = (selector: (p: typeof points[number]) => number | null) => {
    const series = points.filter((p) => selector(p) != null);
    return series
      .map((p, i) => `${i === 0 ? 'M' : 'L'} ${x(p.date).toFixed(2)} ${y(selector(p) as number).toFixed(2)}`)
      .join(' ');
  };
  const sysPath = buildPath((p) => p.sys);
  const diaPath = buildPath((p) => p.dia);
  const hrPath = buildPath((p) => p.hr);

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-[130px]">
        <rect x={padding.left} y={padding.top} width={innerW} height={innerH} rx={6} fill="rgba(15,23,42,0.35)" />
        {sysPath && <path d={sysPath} fill="none" stroke="rgba(248,113,113,0.95)" strokeWidth="2.2" strokeLinecap="round" />}
        {diaPath && <path d={diaPath} fill="none" stroke="rgba(251,191,36,0.95)" strokeWidth="2.2" strokeLinecap="round" />}
        {hrPath && <path d={hrPath} fill="none" stroke="rgba(34,197,94,0.95)" strokeWidth="2.2" strokeLinecap="round" />}
      </svg>
      <div className="flex items-center justify-between text-[11px] text-slate-500 mt-1">
        <span>{formatShortDate(fromDate)}</span>
        <span>2 weeks</span>
        <span>{formatShortDate(toDate)}</span>
      </div>
      <div className="flex flex-wrap gap-3 text-[11px] text-slate-400 mt-1">
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-400" />Sys</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-400" />Dia</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-400" />HR</span>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [totals, setTotals] = useState<DailyTotals | null>(null);
  const [vitals, setVitals] = useState<Vital[]>([]);
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [exercisePlan, setExercisePlan] = useState<ExercisePlan | null>(null);
  const [checklist, setChecklist] = useState<DailyChecklist | null>(null);
  const [vitalsWindow, setVitalsWindow] = useState<Vital[]>([]);
  const [weightSeries, setWeightSeries] = useState<WeightPoint[]>([]);
  const [weightRange, setWeightRange] = useState<{ from: string; to: string } | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generatingPlan, setGeneratingPlan] = useState(false);
  const [genMessage, setGenMessage] = useState('');
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [t, v, p] = await Promise.all([
        apiClient.get<DailyTotals>(`/api/logs/daily-totals?target_date=${today()}`),
        apiClient.get<Vital[]>(`/api/logs/vitals?target_date=${today()}`),
        apiClient.get<ProfileData>('/api/settings/profile'),
      ]);
      const to = new Date();
      const from = new Date();
      from.setDate(to.getDate() - 13);
      const fromIso = toIsoDate(from);
      const toIso = toIsoDate(to);
      const vitalsRange = await apiClient.get<Vital[]>(
        `/api/logs/vitals?date_from=${fromIso}&date_to=${toIso}`
      );
      const plan = await apiClient.get<ExercisePlan>(`/api/logs/exercise-plan?target_date=${today()}`);
      const c = await apiClient.get<DailyChecklist>(`/api/logs/checklist?target_date=${today()}`);
      setTotals(t);
      setVitals(v);
      setProfile(p);
      setExercisePlan(plan);
      setChecklist(c);
      setVitalsWindow(vitalsRange);
      setWeightSeries(buildWeightSeries(vitalsRange, fromIso, toIso));
      setWeightRange({ from: fromIso, to: toIso });
    } catch {
      // individual cards will show empty state
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const generateSummary = async () => {
    setGenerating(true);
    setGenMessage('');
    try {
      await apiClient.post('/api/summaries/generate?summary_type=daily');
      setGenMessage('Daily summary generated successfully.');
    } catch (e: unknown) {
      setGenMessage(e instanceof Error ? e.message : 'Failed to generate summary.');
    } finally {
      setGenerating(false);
    }
  };

  const generateExercisePlan = async () => {
    setGeneratingPlan(true);
    setGenMessage('');
    try {
      const plan = await apiClient.post<ExercisePlan>(`/api/logs/exercise-plan/generate?target_date=${today()}`);
      setExercisePlan(plan);
      setGenMessage('Exercise plan generated.');
    } catch (e: unknown) {
      setGenMessage(e instanceof Error ? e.message : 'Failed to generate exercise plan.');
    } finally {
      setGeneratingPlan(false);
    }
  };

  const toggleChecklist = async (itemType: 'medication' | 'supplement', itemName: string, completed: boolean) => {
    try {
      await apiClient.put('/api/logs/checklist', {
        target_date: today(),
        item_type: itemType,
        item_name: itemName,
        completed,
      });
      setChecklist((prev) => {
        if (!prev) return prev;
        const key = itemType === 'medication' ? 'medications' : 'supplements';
        return {
          ...prev,
          [key]: prev[key].map((i) => (i.name === itemName ? { ...i, completed } : i)),
        };
      });
    } catch {
      // no-op
    }
  };

  const latestVital = vitals.length > 0 ? vitals[vitals.length - 1] : null;
  const latestWeight = vitals.find((v) => v.weight_kg !== null)?.weight_kg ?? null;
  const protein = totals?.food.protein_g ?? 0;
  const carbs = totals?.food.carbs_g ?? 0;
  const fat = totals?.food.fat_g ?? 0;

  const proteinTargetG = profile?.current_weight_kg
    ? Math.max(80, round1(profile.current_weight_kg * 1.6))
    : 120;
  const calorieTarget = 2200;
  const fatTargetG = round1((calorieTarget * 0.3) / 9);
  const carbsTargetG = round1(Math.max(80, (calorieTarget - proteinTargetG * 4 - fatTargetG * 9) / 4));

  const medicalText = (profile?.medical_conditions || '').toLowerCase();
  const hasBpCondition = medicalText.includes('hypertension') || medicalText.includes('high blood pressure');
  const sodiumUpperLimitMg = hasBpCondition ? 1500 : 2300;
  const sodiumTodayMg = Math.round(totals?.food.sodium_mg ?? 0);
  const sodiumPct = Math.min((sodiumTodayMg / sodiumUpperLimitMg) * 100, 100);
  const sodiumOverMg = Math.max(0, sodiumTodayMg - sodiumUpperLimitMg);

  const hydrationUnit = profile?.hydration_unit ?? 'ml';
  const weightUnit = profile?.weight_unit ?? 'kg';
  const hydrationGoalMl = 2500;
  const hydrationPct = totals ? Math.min((totals.hydration_ml / hydrationGoalMl) * 100, 100) : 0;
  const hydrationValue = totals
    ? (hydrationUnit === 'oz' ? round1(mlToOz(totals.hydration_ml)) : Math.round(totals.hydration_ml))
    : 0;
  const hydrationGoal = hydrationUnit === 'oz'
    ? round1(mlToOz(hydrationGoalMl))
    : hydrationGoalMl;
  const displayWeight = (kgValue: number) => (weightUnit === 'lb' ? round1(kgToLb(kgValue)) : round1(kgValue));

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-3.5rem)]">
        <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Dashboard</h1>
          <p className="text-slate-400 text-sm mt-1">{new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}</p>
        </div>
        <div className="flex items-center gap-3">
          {genMessage && (
            <span className={`text-sm ${genMessage.includes('success') ? 'text-emerald-400' : 'text-rose-400'}`}>
              {genMessage}
            </span>
          )}
          <button
            onClick={generateSummary}
            disabled={generating}
            className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors"
          >
            {generating ? 'Generating...' : 'Generate Daily Summary'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {/* Calories */}
        <Card title="Calories">
          <p className="text-3xl font-bold text-slate-100">
            {totals ? Math.round(totals.food.calories) : 0}
            <span className="text-lg font-normal text-slate-500 ml-1">kcal</span>
          </p>
          {totals && (
            <>
              <p className="text-xs text-slate-500 mt-1">{totals.food.meal_count} meal{totals.food.meal_count !== 1 ? 's' : ''} logged</p>
              <MacroBar protein={totals.food.protein_g} carbs={totals.food.carbs_g} fat={totals.food.fat_g} />
            </>
          )}
        </Card>

        {/* Hydration */}
        <Card title="Hydration">
          <p className="text-3xl font-bold text-slate-100">
            {hydrationValue}
            <span className="text-lg font-normal text-slate-500 ml-1">{hydrationUnit}</span>
          </p>
          <div className="mt-3">
            <div className="flex justify-between text-xs text-slate-500 mb-1">
              <span>{Math.round(hydrationPct)}%</span>
              <span>{hydrationGoal} {hydrationUnit} goal</span>
            </div>
            <div className="h-2.5 rounded-full bg-slate-700 overflow-hidden">
              <div
                className="h-full rounded-full bg-sky-500 transition-all duration-500"
                style={{ width: `${hydrationPct}%` }}
              />
            </div>
          </div>
        </Card>

        {/* Exercise */}
        <Card title="Exercise">
          <p className="text-3xl font-bold text-slate-100">
            {totals ? Math.round(totals.exercise_minutes) : 0}
            <span className="text-lg font-normal text-slate-500 ml-1">min</span>
          </p>
          {totals && totals.exercise_calories_burned > 0 && (
            <p className="text-sm text-slate-400 mt-1">
              {Math.round(totals.exercise_calories_burned)} kcal burned
            </p>
          )}
          <div className="mt-3 p-3 rounded-lg border border-slate-700 bg-slate-900/40">
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs font-medium text-slate-300">
                Plan: {exercisePlan?.title || 'No plan set'}
              </p>
              <span
                className={`text-[10px] px-2 py-0.5 rounded-full ${
                  exercisePlan?.status === 'completed'
                    ? 'bg-emerald-900/50 text-emerald-300'
                    : exercisePlan?.status === 'missed' || exercisePlan?.status === 'off_plan'
                      ? 'bg-rose-900/50 text-rose-300'
                      : 'bg-slate-700 text-slate-300'
                }`}
              >
                {exercisePlan?.status || 'not_set'}
              </span>
            </div>
            {exercisePlan?.description && (
              <p className="text-xs text-slate-400 mt-1">{exercisePlan.description}</p>
            )}
            <div className="mt-2 text-[11px] text-slate-500 flex items-center justify-between">
              <span>Type: {exercisePlan?.plan_type || 'mixed'}</span>
              <span>
                {exercisePlan?.completed_minutes ?? 0}
                {exercisePlan?.target_minutes ? ` / ${exercisePlan.target_minutes}` : ''} min
              </span>
            </div>
            <button
              onClick={generateExercisePlan}
              disabled={generatingPlan}
              className="mt-3 px-3 py-1.5 text-xs bg-slate-700 hover:bg-slate-600 text-slate-100 rounded-md border border-slate-600 disabled:opacity-50"
            >
              {generatingPlan ? 'Generating...' : 'Generate Plan'}
            </button>
          </div>
        </Card>

        {/* Sodium */}
        <Card title="Sodium">
          <p className={`text-3xl font-bold ${sodiumOverMg > 0 ? 'text-rose-400' : 'text-slate-100'}`}>
            {sodiumTodayMg}
            <span className="text-lg font-normal text-slate-500 ml-1">mg</span>
          </p>
          <div className="mt-3">
            <div className="flex justify-between text-xs text-slate-500 mb-1">
              <span>{Math.round((sodiumTodayMg / sodiumUpperLimitMg) * 100)}%</span>
              <span>{sodiumUpperLimitMg} mg upper limit</span>
            </div>
            <div className="h-2.5 rounded-full bg-slate-700 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${sodiumOverMg > 0 ? 'bg-rose-500' : 'bg-emerald-500'}`}
                style={{ width: `${sodiumPct}%` }}
              />
            </div>
            {sodiumOverMg > 0 ? (
              <p className="text-xs text-rose-400 mt-2">Over limit by {sodiumOverMg} mg</p>
            ) : (
              <p className="text-xs text-slate-500 mt-2">{sodiumUpperLimitMg - sodiumTodayMg} mg remaining</p>
            )}
          </div>
        </Card>

        {/* Fasting */}
        <Card title="Fasting Timer">
          <FastingTimer />
        </Card>

        {/* Meds & Vitamins */}
        <Card title="Meds & Vitamins">
          <div className="space-y-3">
            <div>
              <p className="text-xs text-slate-500 mb-1">Medications</p>
              <div className="space-y-1.5">
                {(checklist?.medications.length ? checklist.medications : [{ name: 'No medications set in profile', dose: '', timing: '', completed: false }]).map((m) => {
                  const isPlaceholder = m.name.startsWith('No medications');
                  return (
                    <label key={`med-${m.name}`} className="flex items-center gap-2 text-sm text-slate-200">
                      <input
                        type="checkbox"
                        checked={m.completed}
                        disabled={isPlaceholder}
                        onChange={(e) => toggleChecklist('medication', m.name, e.target.checked)}
                        className="accent-emerald-500"
                      />
                      <span className={`flex-1 ${m.completed ? 'line-through text-slate-400' : ''}`}>
                        {m.name}{m.dose ? ` (${m.dose})` : ''}
                      </span>
                      {m.timing && <span className="text-xs text-emerald-400/70 shrink-0">{m.timing}</span>}
                    </label>
                  );
                })}
              </div>
            </div>
            <div>
              <p className="text-xs text-slate-500 mb-1">Vitamins / Supplements</p>
              <div className="space-y-1.5">
                {(checklist?.supplements.length ? checklist.supplements : [{ name: 'No supplements set in profile', dose: '', timing: '', completed: false }]).map((s) => {
                  const isPlaceholder = s.name.startsWith('No supplements');
                  return (
                    <label key={`sup-${s.name}`} className="flex items-center gap-2 text-sm text-slate-200">
                      <input
                        type="checkbox"
                        checked={s.completed}
                        disabled={isPlaceholder}
                        onChange={(e) => toggleChecklist('supplement', s.name, e.target.checked)}
                        className="accent-sky-500"
                      />
                      <span className={`flex-1 ${s.completed ? 'line-through text-slate-400' : ''}`}>
                        {s.name}{s.dose ? ` (${s.dose})` : ''}
                      </span>
                      {s.timing && <span className="text-xs text-sky-400/70 shrink-0">{s.timing}</span>}
                    </label>
                  );
                })}
              </div>
            </div>
          </div>
        </Card>

        {/* Weight */}
        <Card title="Weight">
          <div className="grid grid-cols-[90px_1fr] gap-3">
            <div className="space-y-2">
              <div>
                <p className="text-xs text-slate-500">Current</p>
                <p className="text-2xl font-bold text-slate-100">
                  {latestWeight != null
                    ? displayWeight(latestWeight)
                    : profile?.current_weight_kg != null
                      ? displayWeight(profile.current_weight_kg)
                      : '--'}
                  <span className="text-sm font-normal text-slate-500 ml-1">{weightUnit}</span>
                </p>
              </div>
              {profile?.goal_weight_kg && (
                <div>
                  <p className="text-xs text-slate-500">Goal</p>
                  <p className="text-lg font-semibold text-emerald-400">
                    {displayWeight(profile.goal_weight_kg)}
                    <span className="text-sm font-normal text-slate-500 ml-1">{weightUnit}</span>
                  </p>
                </div>
              )}
            </div>
            <div>
              {weightRange ? (
                <WeightTrendChart
                  points={weightSeries}
                  goal={profile?.goal_weight_kg ?? null}
                  unit={weightUnit}
                  toDisplay={displayWeight}
                  fromDate={weightRange.from}
                  toDate={weightRange.to}
                />
              ) : (
                <div className="h-[130px] rounded-lg border border-slate-700 bg-slate-900/40 flex items-center justify-center text-xs text-slate-500">
                  Loading trend...
                </div>
              )}
            </div>
          </div>
        </Card>

        {/* Macro Targets */}
        <Card title="Macro Targets (P/C/F)">
          <MacroTargetsCard
            protein={protein}
            carbs={carbs}
            fat={fat}
            proteinTarget={proteinTargetG}
            carbsTarget={carbsTargetG}
            fatTarget={fatTargetG}
          />
        </Card>

        {/* Vitals */}
        <Card title="Latest Vitals">
          {(latestVital && (latestVital.bp_systolic || latestVital.heart_rate)) || vitalsWindow.length > 0 ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <span>
                  BP: {latestVital?.bp_systolic ?? '--'}/{latestVital?.bp_diastolic ?? '--'} mmHg
                </span>
                <span>HR: {latestVital?.heart_rate ?? '--'} bpm</span>
              </div>
              {weightRange && (
                <VitalsTrendChart vitals={vitalsWindow} fromDate={weightRange.from} toDate={weightRange.to} />
              )}
            </div>
          ) : (
            <p className="text-slate-500 text-sm">No vitals recorded today</p>
          )}
        </Card>
      </div>
    </div>
  );
}
