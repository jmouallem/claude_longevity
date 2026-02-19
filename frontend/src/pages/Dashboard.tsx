import { useState, useEffect, useCallback } from 'react';
import { apiClient } from '../api/client';
import FastingTimer from '../components/FastingTimer';

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

function Card({ title, children, className = '' }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-slate-800 rounded-xl p-5 border border-slate-700 ${className}`}>
      <h3 className="text-sm font-medium text-slate-400 mb-3">{title}</h3>
      {children}
    </div>
  );
}

export default function Dashboard() {
  const [totals, setTotals] = useState<DailyTotals | null>(null);
  const [vitals, setVitals] = useState<Vital[]>([]);
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [generating, setGenerating] = useState(false);
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
      setTotals(t);
      setVitals(v);
      setProfile(p);
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

  const latestVital = vitals.length > 0 ? vitals[vitals.length - 1] : null;
  const latestWeight = vitals.find((v) => v.weight_kg !== null)?.weight_kg ?? null;
  const hydrationGoal = 2500;
  const hydrationPct = totals ? Math.min((totals.hydration_ml / hydrationGoal) * 100, 100) : 0;

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
            {totals ? Math.round(totals.hydration_ml) : 0}
            <span className="text-lg font-normal text-slate-500 ml-1">ml</span>
          </p>
          <div className="mt-3">
            <div className="flex justify-between text-xs text-slate-500 mb-1">
              <span>{Math.round(hydrationPct)}%</span>
              <span>{hydrationGoal} ml goal</span>
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
        </Card>

        {/* Fasting */}
        <Card title="Fasting Timer">
          <FastingTimer />
        </Card>

        {/* Weight */}
        <Card title="Weight">
          <div className="space-y-2">
            <div>
              <p className="text-xs text-slate-500">Current</p>
              <p className="text-2xl font-bold text-slate-100">
                {latestWeight ?? profile?.current_weight_kg ?? '--'}
                <span className="text-sm font-normal text-slate-500 ml-1">kg</span>
              </p>
            </div>
            {profile?.goal_weight_kg && (
              <div>
                <p className="text-xs text-slate-500">Goal</p>
                <p className="text-lg font-semibold text-emerald-400">
                  {profile.goal_weight_kg}
                  <span className="text-sm font-normal text-slate-500 ml-1">kg</span>
                </p>
              </div>
            )}
          </div>
        </Card>

        {/* Vitals */}
        <Card title="Latest Vitals">
          {latestVital && (latestVital.bp_systolic || latestVital.heart_rate) ? (
            <div className="space-y-3">
              {latestVital.bp_systolic != null && latestVital.bp_diastolic != null && (
                <div>
                  <p className="text-xs text-slate-500">Blood Pressure</p>
                  <p className="text-2xl font-bold text-slate-100">
                    {latestVital.bp_systolic}/{latestVital.bp_diastolic}
                    <span className="text-sm font-normal text-slate-500 ml-1">mmHg</span>
                  </p>
                </div>
              )}
              {latestVital.heart_rate != null && (
                <div>
                  <p className="text-xs text-slate-500">Heart Rate</p>
                  <p className="text-2xl font-bold text-slate-100">
                    {latestVital.heart_rate}
                    <span className="text-sm font-normal text-slate-500 ml-1">bpm</span>
                  </p>
                </div>
              )}
              <p className="text-xs text-slate-600">
                {new Date(latestVital.logged_at).toLocaleTimeString()}
              </p>
            </div>
          ) : (
            <p className="text-slate-500 text-sm">No vitals recorded today</p>
          )}
        </Card>
      </div>
    </div>
  );
}
