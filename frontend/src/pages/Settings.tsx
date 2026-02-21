import { useState, useEffect, useCallback, type KeyboardEvent } from 'react';
import { apiClient } from '../api/client';
import {
  lbToKg,
  kgToLb,
  ftInToCm,
  cmToFtIn,
  round1,
  type HeightUnit,
  type WeightUnit,
  type HydrationUnit,
} from '../utils/units';

type Tab = 'apikey' | 'profile' | 'framework' | 'models' | 'usage' | 'adaptation' | 'security';
type Provider = 'anthropic' | 'openai' | 'google';
type ModelRole = 'utility' | 'reasoning' | 'deep_thinking';

interface ModelOption {
  id: string;
  name: string;
  hint?: string;
  quality_tier?: string;
  speed_tier?: string;
  cost_tier?: string;
  best_for?: string[];
}

interface RoleHint {
  title: string;
  description: string;
  selection_tips: string[];
}

interface ModelPreset {
  label: string;
  description: string;
  reasoning: string;
  utility: string;
  deep_thinking: string;
}

interface ModelsResponse {
  provider: string;
  reasoning_models: ModelOption[];
  utility_models: ModelOption[];
  deep_thinking_models: ModelOption[];
  default_reasoning: string;
  default_utility: string;
  default_deep_thinking: string;
  role_hints: Record<ModelRole, RoleHint>;
  presets: Record<string, ModelPreset>;
}

interface ProfileData {
  ai_provider: string;
  has_api_key: boolean;
  reasoning_model: string;
  utility_model: string;
  deep_thinking_model: string;
  age: number | null;
  sex: string | null;
  height_cm: number | null;
  current_weight_kg: number | null;
  goal_weight_kg: number | null;
  height_unit: HeightUnit;
  weight_unit: WeightUnit;
  hydration_unit: HydrationUnit;
  fitness_level: string | null;
  timezone: string | null;
  medical_conditions: string | null;
  medications: string | null;
  supplements: string | null;
  family_history: string | null;
  dietary_preferences: string | null;
  health_goals: string | null;
}

type FrameworkTypeKey = 'dietary' | 'training' | 'metabolic_timing' | 'micronutrient' | 'expert_derived';

interface FrameworkTypeMeta {
  label: string;
  classifier_label: string;
  description?: string;
  examples?: string[];
}

interface FrameworkItem {
  id: number;
  user_id: number;
  framework_type: FrameworkTypeKey | string;
  framework_type_label: string;
  classifier_label: string;
  name: string;
  normalized_name: string;
  priority_score: number;
  is_active: boolean;
  source: string;
  rationale: string | null;
  metadata: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
}

interface FrameworkResponse {
  framework_types: Record<string, FrameworkTypeMeta>;
  grouped: Record<string, FrameworkItem[]>;
  items: FrameworkItem[];
}

const PROVIDERS: { value: Provider; label: string; description: string }[] = [
  { value: 'anthropic', label: 'Anthropic', description: 'Claude models' },
  { value: 'openai', label: 'OpenAI', description: 'GPT models' },
  { value: 'google', label: 'Google', description: 'Gemini models' },
];

const FITNESS_LEVELS = ['sedentary', 'lightly_active', 'moderately_active', 'very_active', 'extremely_active'];

function TabButton({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
        active
          ? 'bg-emerald-600 text-white'
          : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
      }`}
    >
      {label}
    </button>
  );
}

function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full ${
      ok ? 'bg-emerald-900/50 text-emerald-400' : 'bg-rose-900/50 text-rose-400'
    }`}>
      <span className={`w-1.5 h-1.5 rounded-full ${ok ? 'bg-emerald-400' : 'bg-rose-400'}`} />
      {label}
    </span>
  );
}

function TagInput({
  label,
  hint,
  tags,
  onChange,
}: {
  label: string;
  hint: string;
  tags: string[];
  onChange: (tags: string[]) => void;
}) {
  const [input, setInput] = useState('');

  const addTag = (text: string) => {
    const trimmed = text.trim();
    if (trimmed && !tags.includes(trimmed)) {
      onChange([...tags, trimmed]);
    }
    setInput('');
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addTag(input);
    } else if (e.key === 'Backspace' && !input && tags.length > 0) {
      onChange(tags.slice(0, -1));
    }
  };

  const removeTag = (index: number) => {
    onChange(tags.filter((_, i) => i !== index));
  };

  return (
    <div>
      <label className="block text-sm text-slate-400 mb-1">{label}</label>
      <div className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 focus-within:border-emerald-500 min-h-[42px] flex flex-wrap gap-1.5 items-center">
        {tags.map((tag, i) => (
          <span
            key={i}
            className="inline-flex items-center gap-1 bg-slate-600 text-slate-200 text-xs font-medium px-2 py-1 rounded-md"
          >
            {tag}
            <button
              type="button"
              onClick={() => removeTag(i)}
              className="text-slate-400 hover:text-rose-400 ml-0.5"
            >
              &times;
            </button>
          </span>
        ))}
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={() => { if (input.trim()) addTag(input); }}
          placeholder={tags.length === 0 ? hint : 'Add more...'}
          className="flex-1 min-w-[120px] bg-transparent text-slate-100 text-sm outline-none placeholder-slate-500"
        />
      </div>
      <p className="text-xs text-slate-500 mt-1">Press Enter or comma to add. Backspace to remove last.</p>
    </div>
  );
}

interface StructuredItem {
  name: string;
  dose: string;
  timing: string;
}

const TIMING_OPTIONS = [
  '', 'morning', 'evening', 'with breakfast', 'with lunch',
  'with dinner', 'bedtime', 'twice daily', 'as needed',
];

function StructuredItemEditor({
  label,
  items,
  onChange,
}: {
  label: string;
  items: StructuredItem[];
  onChange: (items: StructuredItem[]) => void;
}) {
  const updateItem = (index: number, field: keyof StructuredItem, value: string) => {
    const updated = items.map((item, i) => i === index ? { ...item, [field]: value } : item);
    onChange(updated);
  };

  const removeItem = (index: number) => {
    onChange(items.filter((_, i) => i !== index));
  };

  const addItem = () => {
    onChange([...items, { name: '', dose: '', timing: '' }]);
  };

  return (
    <div>
      <label className="block text-sm text-slate-400 mb-1">{label}</label>
      <div className="space-y-2">
        {items.map((item, i) => (
          <div key={i} className="flex gap-2 items-center">
            <input
              type="text"
              value={item.name}
              onChange={(e) => updateItem(i, 'name', e.target.value)}
              placeholder="Name"
              className="flex-1 min-w-0 bg-slate-700 border border-slate-600 rounded px-2 py-1.5 text-sm text-slate-100 placeholder-slate-500 focus:border-emerald-500 outline-none"
            />
            <input
              type="text"
              value={item.dose}
              onChange={(e) => updateItem(i, 'dose', e.target.value)}
              placeholder="Dose"
              className="w-28 bg-slate-700 border border-slate-600 rounded px-2 py-1.5 text-sm text-slate-100 placeholder-slate-500 focus:border-emerald-500 outline-none"
            />
            <select
              value={item.timing}
              onChange={(e) => updateItem(i, 'timing', e.target.value)}
              className="w-32 bg-slate-700 border border-slate-600 rounded px-2 py-1.5 text-sm text-slate-100 focus:border-emerald-500 outline-none"
            >
              {TIMING_OPTIONS.map((t) => (
                <option key={t} value={t}>{t || '— timing —'}</option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => removeItem(i)}
              className="text-slate-400 hover:text-rose-400 text-lg px-1"
            >
              &times;
            </button>
          </div>
        ))}
      </div>
      <button
        type="button"
        onClick={addItem}
        className="mt-2 text-sm text-emerald-400 hover:text-emerald-300"
      >
        + Add {label.toLowerCase().replace(/s$/, '')}
      </button>
    </div>
  );
}

function UnitToggle({ value, options, onChange }: { value: string; options: { value: string; label: string }[]; onChange: (v: string) => void }) {
  return (
    <div className="inline-flex rounded-md border border-slate-600 overflow-hidden">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={`px-3 py-1.5 text-xs font-medium transition-colors ${
            value === opt.value
              ? 'bg-emerald-600 text-white'
              : 'bg-slate-700 text-slate-400 hover:text-slate-200'
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

export default function Settings() {
  const [tab, setTab] = useState<Tab>('profile');
  const [loading, setLoading] = useState(true);
  const [profileLoaded, setProfileLoaded] = useState(false);

  // API Key state
  const [provider, setProvider] = useState<Provider>('anthropic');
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [hasKey, setHasKey] = useState(false);
  const [keySaving, setKeySaving] = useState(false);
  const [keyValidating, setKeyValidating] = useState(false);
  const [keyMessage, setKeyMessage] = useState('');
  const [keyValid, setKeyValid] = useState<boolean | null>(null);

  // Profile state
  const [age, setAge] = useState('');
  const [sex, setSex] = useState('');
  const [heightCm, setHeightCm] = useState('');
  const [heightFt, setHeightFt] = useState('');
  const [heightIn, setHeightIn] = useState('');
  const [heightUnit, setHeightUnit] = useState<HeightUnit>('cm');
  const [currentWeight, setCurrentWeight] = useState('');
  const [goalWeight, setGoalWeight] = useState('');
  const [weightUnit, setWeightUnit] = useState<WeightUnit>('kg');
  const [hydrationUnit, setHydrationUnit] = useState<HydrationUnit>('ml');
  const [fitnessLevel, setFitnessLevel] = useState('');
  const [timezone, setTimezone] = useState('');
  const [medicalConditionsTags, setMedicalConditionsTags] = useState<string[]>([]);
  const [medicationsItems, setMedicationsItems] = useState<StructuredItem[]>([]);
  const [supplementsItems, setSupplementsItems] = useState<StructuredItem[]>([]);
  const [familyHistoryTags, setFamilyHistoryTags] = useState<string[]>([]);
  const [dietaryPreferencesTags, setDietaryPreferencesTags] = useState<string[]>([]);
  const [healthGoalsTags, setHealthGoalsTags] = useState<string[]>([]);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileMessage, setProfileMessage] = useState('');
  const [frameworkData, setFrameworkData] = useState<FrameworkResponse | null>(null);
  const [frameworkLoading, setFrameworkLoading] = useState(false);
  const [frameworkSaving, setFrameworkSaving] = useState(false);
  const [frameworkMessage, setFrameworkMessage] = useState('');
  const [newFrameworkDrafts, setNewFrameworkDrafts] = useState<
    Record<string, { name: string; priority_score: number; is_active: boolean }>
  >({});

  // Models state
  const [reasoningModel, setReasoningModel] = useState('');
  const [utilityModel, setUtilityModel] = useState('');
  const [deepThinkingModel, setDeepThinkingModel] = useState('');
  const [modelsSaving, setModelsSaving] = useState(false);
  const [modelsMessage, setModelsMessage] = useState('');
  const [availableModels, setAvailableModels] = useState<ModelsResponse | null>(null);

  // Usage state
  interface UsageModel {
    model_id: string;
    model_name: string;
    tokens_in: number;
    tokens_out: number;
    request_count: number;
    cost_usd: number;
  }
  const [usageData, setUsageData] = useState<{
    models: UsageModel[];
    total_cost_usd: number;
    reset_at: string | null;
  } | null>(null);
  const [usageLoading, setUsageLoading] = useState(false);
  const [resetConfirm, setResetConfirm] = useState(false);

  interface AnalysisRunRow {
    id: number;
    run_type: 'daily' | 'weekly' | 'monthly' | string;
    period_start: string;
    period_end: string;
    status: string;
    confidence: number | null;
    summary_markdown: string | null;
    created_at: string | null;
  }

  interface AnalysisProposalRow {
    id: number;
    analysis_run_id: number;
    proposal_kind: string;
    status: string;
    title: string;
    rationale: string;
    confidence: number | null;
    created_at: string | null;
  }

  const [analysisRuns, setAnalysisRuns] = useState<AnalysisRunRow[]>([]);
  const [analysisProposals, setAnalysisProposals] = useState<AnalysisProposalRow[]>([]);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisMessage, setAnalysisMessage] = useState('');
  const [analysisRunType, setAnalysisRunType] = useState<'daily' | 'weekly' | 'monthly'>('daily');

  // Security state
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmNewPassword, setConfirmNewPassword] = useState('');
  const [passwordSaving, setPasswordSaving] = useState(false);
  const [passwordMessage, setPasswordMessage] = useState('');
  const [resetPassword, setResetPassword] = useState('');
  const [resetConfirmation, setResetConfirmation] = useState('');
  const [resetDataSaving, setResetDataSaving] = useState(false);
  const [resetDataMessage, setResetDataMessage] = useState('');
  const [toast, setToast] = useState<{ message: string; tone: 'info' | 'warn' | 'success' } | null>(null);

  const showToast = useCallback((message: string, tone: 'info' | 'warn' | 'success' = 'info') => {
    setToast({ message, tone });
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 4200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const fetchUsage = useCallback(async () => {
    setUsageLoading(true);
    try {
      const data = await apiClient.get<{
        models: UsageModel[];
        total_cost_usd: number;
        reset_at: string | null;
      }>('/api/settings/usage');
      setUsageData(data);
    } catch {
      // ignore
    } finally {
      setUsageLoading(false);
    }
  }, []);

  const resetUsage = async () => {
    try {
      await apiClient.post('/api/settings/usage/reset', {});
      setResetConfirm(false);
      fetchUsage();
    } catch {
      // ignore
    }
  };

  const fetchAnalysis = useCallback(async () => {
    setAnalysisLoading(true);
    try {
      const [runs, proposals] = await Promise.all([
        apiClient.get<AnalysisRunRow[]>('/api/analysis/runs?limit=20'),
        apiClient.get<AnalysisProposalRow[]>('/api/analysis/proposals?limit=40'),
      ]);
      setAnalysisRuns(runs);
      setAnalysisProposals(proposals);
    } catch (e: unknown) {
      setAnalysisMessage(e instanceof Error ? e.message : 'Failed to load adaptation data.');
    } finally {
      setAnalysisLoading(false);
    }
  }, []);

  const triggerAnalysisRun = async () => {
    setAnalysisMessage('');
    setAnalysisLoading(true);
    try {
      await apiClient.post('/api/analysis/runs', { run_type: analysisRunType, force: true });
      setAnalysisMessage(`${analysisRunType} analysis completed.`);
      await fetchAnalysis();
    } catch (e: unknown) {
      setAnalysisMessage(e instanceof Error ? e.message : 'Failed to run analysis.');
    } finally {
      setAnalysisLoading(false);
    }
  };

  const triggerDueAnalyses = async () => {
    setAnalysisMessage('');
    setAnalysisLoading(true);
    try {
      const response = await apiClient.post<{ count: number }>('/api/analysis/runs/due', {});
      setAnalysisMessage(`Triggered due analysis runs: ${response.count}`);
      await fetchAnalysis();
    } catch (e: unknown) {
      setAnalysisMessage(e instanceof Error ? e.message : 'Failed to trigger due runs.');
    } finally {
      setAnalysisLoading(false);
    }
  };

  const reviewAnalysisProposal = async (proposalId: number, action: 'approve' | 'reject') => {
    setAnalysisMessage('');
    try {
      await apiClient.post(`/api/analysis/proposals/${proposalId}/review`, { action });
      setAnalysisMessage(`Proposal ${action}d.`);
      await fetchAnalysis();
    } catch (e: unknown) {
      setAnalysisMessage(e instanceof Error ? e.message : `Failed to ${action} proposal.`);
    }
  };

  const fmtNum = (n: number) => n.toLocaleString();
  const fmtCost = (n: number) => `$${n.toFixed(4)}`;
  const tierLabel = (tier?: string) => {
    const normalized = (tier || '').toLowerCase();
    if (!normalized) return 'N/A';
    if (normalized === 'very_high') return 'Very High';
    if (normalized === 'high') return 'High';
    if (normalized === 'medium') return 'Medium';
    if (normalized === 'low') return 'Low';
    if (normalized === 'fast') return 'Fast';
    if (normalized === 'slow') return 'Slow';
    return normalized.replace(/_/g, ' ');
  };
  const costBadge = (tier?: string) => {
    const normalized = (tier || '').toLowerCase();
    if (normalized === 'low') return '$';
    if (normalized === 'medium') return '$$';
    if (normalized === 'high') return '$$$';
    if (normalized === 'very_high') return '$$$$';
    return '?';
  };
  const findModelById = (options: ModelOption[], modelId: string) => options.find((m) => m.id === modelId);

  // Parse stored string into tags (handles both JSON arrays and comma-separated)
  const parseToTags = (val: string | null): string[] => {
    const doseToken = /^\d[\d,.\s]*(mcg|mg|g|kg|iu|ml|units?|tabs?|caps?)\b/i;
    const intakeTokenA = /^(\d+(?:[.,]\d+)?)\s*(drops?|caps?(?:ules?)?|tablets?|tabs?|pills?|ml)\b(?:\s*(daily|per day|\/day|a day))?$/i;
    const intakeTokenB = /^(drops?|caps?(?:ules?)?|tablets?|tabs?|pills?|ml)\s*\+?\s*(\d+(?:[.,]\d+)?)(?:\s*(daily|per day|\/day|a day))?$/i;
    const familyIntakeA = /^(\d+(?:[.,]\d+)?)\s*(omega\s*-?\s*3|omega3|d3|b12|coq10|q10)(?:\s*(daily|per day|\/day|a day))?$/i;
    const familyIntakeB = /^(omega\s*-?\s*3|omega3|d3|b12|coq10|q10)\s*\+?\s*(\d+(?:[.,]\d+)?)(?:\s*(daily|per day|\/day|a day))?$/i;
    const familyKey = (s: string): 'omega3' | 'd3' | 'b12' | 'coq10' | null => {
      const t = s.toLowerCase();
      if (t.includes('omega3') || t.includes('omega-3') || t.includes('omega 3')) return 'omega3';
      if (t.includes('d3') || t.includes('vitamin d') || t.includes('vit d')) return 'd3';
      if (t.includes('b12') || t.includes('vitamin b12') || t.includes('vit b12')) return 'b12';
      if (t.includes('coq10') || t.includes('q10')) return 'coq10';
      return null;
    };
    const toCanonicalIntake = (item: string): string | null => {
      const a = item.match(intakeTokenA);
      if (a) {
        const qty = a[1];
        const unit = a[2].toLowerCase();
        const freq = (a[3] || '').toLowerCase();
        const normalizedFreq = ['per day', '/day', 'a day'].includes(freq) ? 'daily' : freq;
        return `${qty} ${unit}${normalizedFreq === 'daily' ? ' daily' : ''}`.trim();
      }
      const b = item.match(intakeTokenB);
      if (b) {
        const unit = b[1].toLowerCase();
        const qty = b[2];
        const freq = (b[3] || '').toLowerCase();
        const normalizedFreq = ['per day', '/day', 'a day'].includes(freq) ? 'daily' : freq;
        return `${qty} ${unit}${normalizedFreq === 'daily' ? ' daily' : ''}`.trim();
      }
      return null;
    };
    const normalize = (items: string[]) => {
      const merged: string[] = [];
      for (const raw of items) {
        const item = raw.replace(/\s+/g, ' ').trim();
        if (!item) continue;
        const fa = item.match(familyIntakeA);
        const fb = item.match(familyIntakeB);
        if (fa || fb) {
          const fam = familyKey((fa ? fa[2] : fb?.[1]) || '');
          const qty = (fa ? fa[1] : fb?.[2]) || '';
          const detail = `${qty} daily`;
          if (fam) {
            const idx = merged.findIndex((m) => familyKey(m) === fam);
            if (idx >= 0) {
              if (!merged[idx].toLowerCase().includes(detail.toLowerCase())) {
                merged[idx] = `${merged[idx]}, ${detail}`;
              }
              continue;
            }
          }
        }
        const intake = toCanonicalIntake(item);
        if (merged.length > 0 && intake) {
          if (!merged[merged.length - 1].toLowerCase().includes(intake.toLowerCase())) {
            merged[merged.length - 1] = `${merged[merged.length - 1]}, ${intake}`;
          }
          continue;
        }
        if (merged.length > 0 && doseToken.test(item)) {
          merged[merged.length - 1] = `${merged[merged.length - 1]} ${item}`.trim();
          continue;
        }
        merged.push(item);
      }
      return merged;
    };

    if (!val) return [];
    const trimmed = val.trim();
    if (trimmed.startsWith('[')) {
      try {
        const arr = JSON.parse(trimmed);
        if (Array.isArray(arr)) return normalize(arr.map((s: string) => s.trim()).filter(Boolean));
      } catch { /* fall through */ }
    }
    return normalize(trimmed.split(',').map(s => s.trim()).filter(Boolean));
  };

  const parseToStructuredItems = (val: string | null): StructuredItem[] => {
    if (!val) return [];
    const trimmed = val.trim();
    if (!trimmed) return [];
    if (trimmed.startsWith('[')) {
      try {
        const arr = JSON.parse(trimmed);
        if (Array.isArray(arr)) {
          return arr.map((entry: string | { name?: string; dose?: string; timing?: string }) => {
            if (typeof entry === 'string') {
              // Legacy string entry — try to split "Name 4mg" into name + dose
              const doseMatch = entry.match(/\b(\d[\d,.\s]*(mcg|mg|g|kg|iu|ml|units?|tabs?|caps?|drops?))\b/i);
              if (doseMatch) {
                const dose = doseMatch[0].trim();
                const name = (entry.slice(0, doseMatch.index) + entry.slice(doseMatch.index! + doseMatch[0].length)).trim().replace(/^\s*[+\-,]\s*|\s*[+\-,]\s*$/g, '').trim();
                return { name: name || dose, dose: name ? dose : '', timing: '' };
              }
              return { name: entry.trim(), dose: '', timing: '' };
            }
            return {
              name: (entry.name || '').trim(),
              dose: (entry.dose || '').trim(),
              timing: (entry.timing || '').trim(),
            };
          }).filter((item: StructuredItem) => item.name);
        }
      } catch { /* fall through */ }
    }
    // Comma-separated fallback
    return trimmed.split(',').map(s => s.trim()).filter(Boolean).map(s => ({ name: s, dose: '', timing: '' }));
  };

  const fetchProfile = useCallback(async () => {
    setLoading(true);
    setProfileLoaded(false);
    try {
      const p = await apiClient.get<ProfileData>('/api/settings/profile');
      setProvider((p.ai_provider || 'anthropic') as Provider);
      setHasKey(p.has_api_key);
      setAge(p.age?.toString() ?? '');
      setSex(p.sex ?? '');
      const profileHeightUnit: HeightUnit = p.height_unit === 'ft' ? 'ft' : 'cm';
      const profileWeightUnit: WeightUnit = p.weight_unit === 'lb' ? 'lb' : 'kg';
      const profileHydrationUnit: HydrationUnit = p.hydration_unit === 'oz' ? 'oz' : 'ml';
      setHeightUnit(profileHeightUnit);
      setWeightUnit(profileWeightUnit);
      setHydrationUnit(profileHydrationUnit);

      // Height: store cm internally, populate both unit views
      const cm = p.height_cm;
      if (cm != null) {
        setHeightCm(cm.toString());
        const [ft, inches] = cmToFtIn(cm);
        setHeightFt(ft.toString());
        setHeightIn(inches.toString());
      } else {
        setHeightCm('');
        setHeightFt('');
        setHeightIn('');
      }

      if (p.current_weight_kg != null) {
        const displayCurrentWeight = profileWeightUnit === 'lb'
          ? round1(kgToLb(p.current_weight_kg))
          : round1(p.current_weight_kg);
        setCurrentWeight(displayCurrentWeight.toString());
      } else {
        setCurrentWeight('');
      }

      if (p.goal_weight_kg != null) {
        const displayGoalWeight = profileWeightUnit === 'lb'
          ? round1(kgToLb(p.goal_weight_kg))
          : round1(p.goal_weight_kg);
        setGoalWeight(displayGoalWeight.toString());
      } else {
        setGoalWeight('');
      }

      setFitnessLevel(p.fitness_level ?? '');
      setTimezone(p.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone);
      setMedicalConditionsTags(parseToTags(p.medical_conditions));
      setMedicationsItems(parseToStructuredItems(p.medications));
      setSupplementsItems(parseToStructuredItems(p.supplements));
      setFamilyHistoryTags(parseToTags(p.family_history));
      setDietaryPreferencesTags(parseToTags(p.dietary_preferences));
      setHealthGoalsTags(parseToTags(p.health_goals));
      setReasoningModel(p.reasoning_model ?? '');
      setUtilityModel(p.utility_model ?? '');
      setDeepThinkingModel(p.deep_thinking_model ?? p.reasoning_model ?? '');
    } catch {
      // ignore
    } finally {
      setLoading(false);
      setProfileLoaded(true);
    }
  }, []);

  const fetchModels = useCallback(async (prov: string) => {
    try {
      const m = await apiClient.get<ModelsResponse>(`/api/settings/models?provider=${prov}`);
      setAvailableModels(m);
    } catch {
      // ignore
    }
  }, []);

  const fetchFrameworks = useCallback(async () => {
    setFrameworkLoading(true);
    setFrameworkMessage('');
    try {
      const data = await apiClient.get<FrameworkResponse>('/api/settings/frameworks');
      setFrameworkData(data);
      setNewFrameworkDrafts((prev) => {
        const next = { ...prev };
        Object.keys(data.framework_types || {}).forEach((typeKey) => {
          if (!next[typeKey]) {
            next[typeKey] = { name: '', priority_score: 60, is_active: true };
          }
        });
        return next;
      });
    } catch (e: unknown) {
      setFrameworkMessage(e instanceof Error ? e.message : 'Failed to load framework settings.');
    } finally {
      setFrameworkLoading(false);
    }
  }, []);

  const patchFrameworkItem = async (
    frameworkId: number,
    payload: Partial<Pick<FrameworkItem, 'priority_score' | 'is_active' | 'name' | 'framework_type' | 'rationale'>>,
  ) => {
    setFrameworkSaving(true);
    setFrameworkMessage('');
    try {
      await apiClient.put(`/api/settings/frameworks/${frameworkId}`, payload);
      await fetchFrameworks();
    } catch (e: unknown) {
      setFrameworkMessage(e instanceof Error ? e.message : 'Failed to update framework item.');
    } finally {
      setFrameworkSaving(false);
    }
  };

  const createFrameworkItem = async (frameworkType: string) => {
    const draft = newFrameworkDrafts[frameworkType] || { name: '', priority_score: 60, is_active: true };
    if (!draft.name.trim()) {
      setFrameworkMessage('Enter a framework name before adding.');
      return;
    }
    setFrameworkSaving(true);
    setFrameworkMessage('');
    try {
      await apiClient.post('/api/settings/frameworks', {
        framework_type: frameworkType,
        name: draft.name.trim(),
        priority_score: Number.isFinite(draft.priority_score) ? draft.priority_score : 60,
        is_active: Boolean(draft.is_active),
        source: 'user',
      });
      setNewFrameworkDrafts((prev) => ({
        ...prev,
        [frameworkType]: { name: '', priority_score: 60, is_active: true },
      }));
      await fetchFrameworks();
      showToast('Framework item added.', 'success');
    } catch (e: unknown) {
      setFrameworkMessage(e instanceof Error ? e.message : 'Failed to add framework item.');
    } finally {
      setFrameworkSaving(false);
    }
  };

  const removeFrameworkItem = async (frameworkId: number) => {
    setFrameworkSaving(true);
    setFrameworkMessage('');
    try {
      await apiClient.delete(`/api/settings/frameworks/${frameworkId}`);
      await fetchFrameworks();
    } catch (e: unknown) {
      setFrameworkMessage(e instanceof Error ? e.message : 'Failed to remove framework item.');
    } finally {
      setFrameworkSaving(false);
    }
  };

  const syncFrameworksFromProfile = async () => {
    setFrameworkSaving(true);
    setFrameworkMessage('');
    try {
      await apiClient.post('/api/settings/frameworks/sync', {});
      await fetchFrameworks();
      showToast('Frameworks synced from profile signals.', 'success');
    } catch (e: unknown) {
      setFrameworkMessage(e instanceof Error ? e.message : 'Failed to sync frameworks from profile.');
    } finally {
      setFrameworkSaving(false);
    }
  };

  useEffect(() => {
    fetchProfile();
  }, [fetchProfile]);

  useEffect(() => {
    if (!profileLoaded) return;
    fetchModels(provider);
  }, [provider, fetchModels, profileLoaded]);

  useEffect(() => {
    if (!availableModels) return;
    if (!profileLoaded) return;
    if (availableModels.provider !== provider) return;
    const reasoningIds = new Set(availableModels.reasoning_models.map((m) => m.id));
    const utilityIds = new Set(availableModels.utility_models.map((m) => m.id));
    const deepIds = new Set(availableModels.deep_thinking_models.map((m) => m.id));

    if (!reasoningIds.has(reasoningModel)) {
      if (reasoningModel) {
        showToast(`Reasoning model is not available for ${provider}. Reset to provider default.`, 'warn');
      }
      setReasoningModel(availableModels.default_reasoning);
    }
    if (!utilityIds.has(utilityModel)) {
      if (utilityModel) {
        showToast(`Utility model is not available for ${provider}. Reset to provider default.`, 'warn');
      }
      setUtilityModel(availableModels.default_utility);
    }
    if (!deepIds.has(deepThinkingModel)) {
      if (deepThinkingModel) {
        showToast(`Deep-thinking model is not available for ${provider}. Reset to provider default.`, 'warn');
      }
      setDeepThinkingModel(availableModels.default_deep_thinking);
    }
  }, [availableModels, reasoningModel, utilityModel, deepThinkingModel, provider, showToast, profileLoaded]);

  useEffect(() => {
    if (tab === 'usage') fetchUsage();
  }, [tab, fetchUsage]);

  useEffect(() => {
    if (tab === 'framework') fetchFrameworks();
  }, [tab, fetchFrameworks]);

  useEffect(() => {
    if (tab === 'adaptation') fetchAnalysis();
  }, [tab, fetchAnalysis]);

  const saveApiKey = async () => {
    if (!apiKey.trim()) return;
    setKeySaving(true);
    setKeyMessage('');
    try {
      const res = await apiClient.put<{
        status: string;
        ai_provider: string;
        reasoning_model: string;
        utility_model: string;
        deep_thinking_model: string;
      }>('/api/settings/api-key', {
        ai_provider: provider,
        api_key: apiKey,
        reasoning_model: reasoningModel || undefined,
        utility_model: utilityModel || undefined,
        deep_thinking_model: deepThinkingModel || reasoningModel || undefined,
      });
      if (
        res.reasoning_model !== reasoningModel ||
        res.utility_model !== utilityModel ||
        res.deep_thinking_model !== deepThinkingModel
      ) {
        showToast('Some selected models were adjusted to supported defaults for this provider.', 'warn');
      }
      setReasoningModel(res.reasoning_model);
      setUtilityModel(res.utility_model);
      setDeepThinkingModel(res.deep_thinking_model);
      setHasKey(true);
      setKeyMessage('API key saved successfully.');
      showToast('API key and model routing saved.', 'success');
      setKeyValid(null);
      setApiKey('');
      window.dispatchEvent(new Event('intake:check'));
    } catch (e: unknown) {
      setKeyMessage(e instanceof Error ? e.message : 'Failed to save API key.');
    } finally {
      setKeySaving(false);
    }
  };

  const validateKey = async () => {
    setKeyValidating(true);
    setKeyMessage('');
    try {
      const res = await apiClient.post<{ status: string; ai_provider?: string }>('/api/settings/api-key/validate');
      const isValid = res.status === 'valid';
      setKeyValid(isValid);
      setKeyMessage(isValid ? 'API key is valid!' : 'API key is invalid.');
    } catch (e: unknown) {
      setKeyValid(false);
      setKeyMessage(e instanceof Error ? e.message : 'Validation failed.');
    } finally {
      setKeyValidating(false);
    }
  };

  const saveProfile = async () => {
    setProfileSaving(true);
    setProfileMessage('');
    try {
      // Convert height to cm
      let heightCmVal: number | null = null;
      if (heightUnit === 'cm' && heightCm) {
        heightCmVal = round1(parseFloat(heightCm));
      } else if (heightUnit === 'ft' && (heightFt || heightIn)) {
        heightCmVal = round1(ftInToCm(parseFloat(heightFt || '0'), parseFloat(heightIn || '0')));
      }

      // Convert weight to kg
      let currentWeightKg: number | null = null;
      let goalWeightKg: number | null = null;
      if (currentWeight) {
        currentWeightKg = weightUnit === 'lb' ? round1(lbToKg(parseFloat(currentWeight))) : round1(parseFloat(currentWeight));
      }
      if (goalWeight) {
        goalWeightKg = weightUnit === 'lb' ? round1(lbToKg(parseFloat(goalWeight))) : round1(parseFloat(goalWeight));
      }

      // Persist as JSON array so item text can safely contain commas.
      const tagsToString = (tags: string[]) => (tags.length > 0 ? JSON.stringify(tags) : null);

      await apiClient.put('/api/settings/profile', {
        age: age ? parseInt(age) : null,
        sex: sex || null,
        height_cm: heightCmVal,
        current_weight_kg: currentWeightKg,
        goal_weight_kg: goalWeightKg,
        height_unit: heightUnit,
        weight_unit: weightUnit,
        hydration_unit: hydrationUnit,
        fitness_level: fitnessLevel || null,
        timezone: timezone || null,
        medical_conditions: tagsToString(medicalConditionsTags),
        medications: medicationsItems.filter(m => m.name.trim()).length > 0
          ? JSON.stringify(medicationsItems.filter(m => m.name.trim()))
          : null,
        supplements: supplementsItems.filter(s => s.name.trim()).length > 0
          ? JSON.stringify(supplementsItems.filter(s => s.name.trim()))
          : null,
        family_history: tagsToString(familyHistoryTags),
        dietary_preferences: tagsToString(dietaryPreferencesTags),
        health_goals: tagsToString(healthGoalsTags),
      });
      await fetchFrameworks();
      setProfileMessage('Profile saved successfully.');
    } catch (e: unknown) {
      setProfileMessage(e instanceof Error ? e.message : 'Failed to save profile.');
    } finally {
      setProfileSaving(false);
    }
  };

  const saveModels = async () => {
    setModelsSaving(true);
    setModelsMessage('');
    try {
      const res = await apiClient.put<{
        status: string;
        reasoning_model: string;
        utility_model: string;
        deep_thinking_model: string;
      }>('/api/settings/models', {
        reasoning_model: reasoningModel,
        utility_model: utilityModel,
        deep_thinking_model: deepThinkingModel,
      });
      if (
        res.reasoning_model !== reasoningModel ||
        res.utility_model !== utilityModel ||
        res.deep_thinking_model !== deepThinkingModel
      ) {
        showToast('One or more selected models were not valid and were reset to supported defaults.', 'warn');
      }
      setReasoningModel(res.reasoning_model);
      setUtilityModel(res.utility_model);
      setDeepThinkingModel(res.deep_thinking_model);
      setModelsMessage('Models saved successfully.');
      showToast('Model routing saved.', 'success');
      window.dispatchEvent(new Event('intake:check'));
    } catch (e: unknown) {
      setModelsMessage(e instanceof Error ? e.message : 'Failed to save models.');
    } finally {
      setModelsSaving(false);
    }
  };

  const applyPreset = (presetKey: string) => {
    if (!availableModels) return;
    const preset = availableModels.presets?.[presetKey];
    if (!preset) return;
    setReasoningModel(preset.reasoning);
    setUtilityModel(preset.utility);
    setDeepThinkingModel(preset.deep_thinking);
    showToast(`Applied "${preset.label}" preset. You can still override each role manually.`, 'info');
  };

  const changePassword = async () => {
    setPasswordMessage('');
    if (!currentPassword || !newPassword) {
      setPasswordMessage('Current and new password are required.');
      return;
    }
    if (newPassword.length < 8) {
      setPasswordMessage('New password must be at least 8 characters.');
      return;
    }
    if (newPassword !== confirmNewPassword) {
      setPasswordMessage('New password and confirmation do not match.');
      return;
    }

    setPasswordSaving(true);
    try {
      await apiClient.post('/api/settings/password/change', {
        current_password: currentPassword,
        new_password: newPassword,
      });
      setPasswordMessage('Password updated successfully.');
      setCurrentPassword('');
      setNewPassword('');
      setConfirmNewPassword('');
    } catch (e: unknown) {
      setPasswordMessage(e instanceof Error ? e.message : 'Failed to change password.');
    } finally {
      setPasswordSaving(false);
    }
  };

  const resetUserData = async () => {
    setResetDataMessage('');
    if (!resetPassword) {
      setResetDataMessage('Current password is required for reset.');
      return;
    }
    if (resetConfirmation.trim().toUpperCase() !== 'RESET') {
      setResetDataMessage('Type RESET to confirm data reset.');
      return;
    }

    setResetDataSaving(true);
    try {
      await apiClient.post('/api/settings/reset-data', {
        current_password: resetPassword,
        confirmation: resetConfirmation,
      });
      setResetDataMessage('User data reset successfully. Password unchanged.');
      setResetPassword('');
      setResetConfirmation('');
      await fetchProfile();
      await fetchFrameworks();
      setUsageData(null);
      window.dispatchEvent(new Event('intake:check'));
    } catch (e: unknown) {
      setResetDataMessage(e instanceof Error ? e.message : 'Failed to reset data.');
    } finally {
      setResetDataSaving(false);
    }
  };

  const selectedReasoningOption = availableModels
    ? findModelById(availableModels.reasoning_models, reasoningModel)
    : undefined;
  const selectedUtilityOption = availableModels
    ? findModelById(availableModels.utility_models, utilityModel)
    : undefined;
  const selectedDeepOption = availableModels
    ? findModelById(availableModels.deep_thinking_models, deepThinkingModel)
    : undefined;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-3.5rem)]">
        <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-6">
      {toast && (
        <div className="fixed right-4 top-20 z-50 max-w-sm">
          <div
            className={`rounded-lg border px-3 py-2 text-sm shadow-lg ${
              toast.tone === 'warn'
                ? 'bg-amber-950/90 border-amber-700 text-amber-200'
                : toast.tone === 'success'
                  ? 'bg-emerald-950/90 border-emerald-700 text-emerald-200'
                  : 'bg-slate-900/95 border-slate-700 text-slate-100'
            }`}
          >
            {toast.message}
          </div>
        </div>
      )}

      <h1 className="text-2xl font-bold text-slate-100 mb-6">Settings</h1>

      {/* No API Key Warning */}
      {!hasKey && (
        <div className="mb-6 p-4 bg-rose-900/30 border border-rose-700 rounded-xl">
          <p className="text-rose-300 font-semibold text-sm">
            You must configure an API key to use the app.
          </p>
          <p className="text-rose-400/80 text-xs mt-1">
            Go to the API Key tab below and enter your provider API key.
          </p>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 mb-6">
        <TabButton active={tab === 'profile'} label="Profile" onClick={() => setTab('profile')} />
        <TabButton active={tab === 'framework'} label="Framework" onClick={() => setTab('framework')} />
        <TabButton active={tab === 'models'} label="Models" onClick={() => setTab('models')} />
        <TabButton active={tab === 'apikey'} label="API Key" onClick={() => setTab('apikey')} />
        <TabButton active={tab === 'usage'} label="Usage" onClick={() => setTab('usage')} />
        <TabButton active={tab === 'adaptation'} label="Adaptation" onClick={() => setTab('adaptation')} />
        <TabButton active={tab === 'security'} label="Security" onClick={() => setTab('security')} />
      </div>

      {/* API Key Tab */}
      {tab === 'apikey' && (
        <div className="bg-slate-800 rounded-xl p-6 border border-slate-700 space-y-6">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-slate-100">AI Provider & API Key</h2>
            <StatusBadge ok={hasKey} label={hasKey ? 'Configured' : 'Not configured'} />
            {keyValid !== null && (
              <StatusBadge ok={keyValid} label={keyValid ? 'Valid' : 'Invalid'} />
            )}
          </div>

          {/* Provider cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {PROVIDERS.map((p) => (
              <button
                key={p.value}
                onClick={() => setProvider(p.value)}
                className={`p-4 rounded-lg border text-left transition-colors ${
                  provider === p.value
                    ? 'border-emerald-500 bg-emerald-900/20'
                    : 'border-slate-600 bg-slate-700/50 hover:border-slate-500'
                }`}
              >
                <p className={`font-semibold text-sm ${provider === p.value ? 'text-emerald-400' : 'text-slate-200'}`}>
                  {p.label}
                </p>
                <p className="text-xs text-slate-400 mt-0.5">{p.description}</p>
              </button>
            ))}
          </div>

          {/* API Key input */}
          <div>
            <label className="block text-sm text-slate-400 mb-1.5">API Key</label>
            <div className="relative">
              <input
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={hasKey ? '********** (key is set, enter new to replace)' : 'Enter your API key'}
                className="w-full bg-slate-700 border border-slate-600 rounded-lg px-4 py-2.5 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500 pr-20 text-sm"
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-slate-400 hover:text-slate-200 px-2 py-1"
              >
                {showKey ? 'Hide' : 'Show'}
              </button>
            </div>
          </div>

          {keyMessage && (
            <p className={`text-sm ${keyMessage.includes('success') || keyMessage.includes('valid') && !keyMessage.includes('invalid') ? 'text-emerald-400' : 'text-rose-400'}`}>
              {keyMessage}
            </p>
          )}

          <div className="flex gap-3">
            <button
              onClick={saveApiKey}
              disabled={keySaving || !apiKey.trim()}
              className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors"
            >
              {keySaving ? 'Saving...' : 'Save Key'}
            </button>
            <button
              onClick={validateKey}
              disabled={keyValidating || !hasKey}
              className="px-4 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed text-slate-200 text-sm font-medium rounded-lg transition-colors border border-slate-600"
            >
              {keyValidating ? 'Validating...' : 'Validate Key'}
            </button>
          </div>
        </div>
      )}

      {/* Profile Tab */}
      {tab === 'profile' && (
        <div className="bg-slate-800 rounded-xl p-6 border border-slate-700 space-y-5">
          <h2 className="text-lg font-semibold text-slate-100">Profile</h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-slate-400 mb-1">Age</label>
              <input
                type="number"
                value={age}
                onChange={(e) => setAge(e.target.value)}
                className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-emerald-500"
              />
            </div>
            <div>
              <label className="block text-sm text-slate-400 mb-1">Sex</label>
              <select
                value={sex}
                onChange={(e) => setSex(e.target.value)}
                className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-emerald-500"
              >
                <option value="">Select</option>
                <option value="male">Male</option>
                <option value="female">Female</option>
                <option value="other">Other</option>
              </select>
            </div>

            {/* Height with unit toggle */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-sm text-slate-400">Height</label>
                <UnitToggle
                  value={heightUnit}
                  options={[{ value: 'cm', label: 'cm' }, { value: 'ft', label: 'ft / in' }]}
                  onChange={(v) => {
                    const newUnit = v as HeightUnit;
                    if (newUnit === 'ft' && heightCm) {
                      const [ft, inches] = cmToFtIn(parseFloat(heightCm));
                      setHeightFt(ft.toString());
                      setHeightIn(inches.toString());
                    } else if (newUnit === 'cm' && (heightFt || heightIn)) {
                      setHeightCm(ftInToCm(parseFloat(heightFt || '0'), parseFloat(heightIn || '0')).toString());
                    }
                    setHeightUnit(newUnit);
                  }}
                />
              </div>
              {heightUnit === 'cm' ? (
                <input
                  type="number"
                  value={heightCm}
                  onChange={(e) => setHeightCm(e.target.value)}
                  placeholder="e.g. 175"
                  className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-emerald-500"
                />
              ) : (
                <div className="flex gap-2">
                  <div className="flex-1">
                    <input
                      type="number"
                      value={heightFt}
                      onChange={(e) => setHeightFt(e.target.value)}
                      placeholder="ft"
                      className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-emerald-500"
                    />
                  </div>
                  <div className="flex-1">
                    <input
                      type="number"
                      value={heightIn}
                      onChange={(e) => setHeightIn(e.target.value)}
                      placeholder="in"
                      className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-emerald-500"
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Fitness Level */}
            <div>
              <label className="block text-sm text-slate-400 mb-1">Fitness Level</label>
              <select
                value={fitnessLevel}
                onChange={(e) => setFitnessLevel(e.target.value)}
                className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-emerald-500"
              >
                <option value="">Select</option>
                {FITNESS_LEVELS.map((l) => (
                  <option key={l} value={l}>
                    {l.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())}
                  </option>
                ))}
              </select>
            </div>

            {/* Weight with unit toggle */}
            <div className="sm:col-span-2">
              <div className="flex items-center justify-between mb-1">
                <label className="text-sm text-slate-400">Weight</label>
                <UnitToggle
                  value={weightUnit}
                  options={[{ value: 'kg', label: 'kg' }, { value: 'lb', label: 'lb' }]}
                  onChange={(v) => {
                    const newUnit = v as WeightUnit;
                    if (newUnit === 'lb' && weightUnit === 'kg') {
                      if (currentWeight) setCurrentWeight(round1(kgToLb(parseFloat(currentWeight))).toString());
                      if (goalWeight) setGoalWeight(round1(kgToLb(parseFloat(goalWeight))).toString());
                    } else if (newUnit === 'kg' && weightUnit === 'lb') {
                      if (currentWeight) setCurrentWeight(round1(lbToKg(parseFloat(currentWeight))).toString());
                      if (goalWeight) setGoalWeight(round1(lbToKg(parseFloat(goalWeight))).toString());
                    }
                    setWeightUnit(newUnit);
                  }}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-slate-500 mb-1">Current</label>
                  <input
                    type="number"
                    step="0.1"
                    value={currentWeight}
                    onChange={(e) => setCurrentWeight(e.target.value)}
                    placeholder={weightUnit === 'kg' ? 'e.g. 75' : 'e.g. 165'}
                    className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-emerald-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-500 mb-1">Goal</label>
                  <input
                    type="number"
                    step="0.1"
                    value={goalWeight}
                    onChange={(e) => setGoalWeight(e.target.value)}
                    placeholder={weightUnit === 'kg' ? 'e.g. 70' : 'e.g. 154'}
                    className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-emerald-500"
                  />
                </div>
              </div>
            </div>

            <div className="sm:col-span-2">
              <div className="flex items-center justify-between mb-1">
                <label className="text-sm text-slate-400">Hydration Unit</label>
                <UnitToggle
                  value={hydrationUnit}
                  options={[{ value: 'ml', label: 'ml' }, { value: 'oz', label: 'oz' }]}
                  onChange={(v) => setHydrationUnit(v as HydrationUnit)}
                />
              </div>
            </div>

            <div className="sm:col-span-2">
              <label className="block text-sm text-slate-400 mb-1">Timezone</label>
              <input
                type="text"
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
                placeholder="e.g. America/New_York"
                className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-emerald-500"
              />
            </div>
          </div>

          <hr className="border-slate-700" />

          <div className="space-y-4">
            <TagInput
              label="Medical Conditions"
              hint="e.g. hypertension, type 2 diabetes"
              tags={medicalConditionsTags}
              onChange={setMedicalConditionsTags}
            />
            <StructuredItemEditor
              label="Medications"
              items={medicationsItems}
              onChange={setMedicationsItems}
            />
            <StructuredItemEditor
              label="Supplements"
              items={supplementsItems}
              onChange={setSupplementsItems}
            />
            <TagInput
              label="Family History"
              hint="e.g. heart disease, cancer"
              tags={familyHistoryTags}
              onChange={setFamilyHistoryTags}
            />
            <TagInput
              label="Dietary Preferences"
              hint="e.g. vegetarian, low-sodium"
              tags={dietaryPreferencesTags}
              onChange={setDietaryPreferencesTags}
            />
            <TagInput
              label="Health Goals"
              hint="e.g. lose weight, lower blood pressure"
              tags={healthGoalsTags}
              onChange={setHealthGoalsTags}
            />
          </div>

          {profileMessage && (
            <p className={`text-sm ${profileMessage.includes('success') ? 'text-emerald-400' : 'text-rose-400'}`}>
              {profileMessage}
            </p>
          )}

          <button
            onClick={saveProfile}
            disabled={profileSaving}
            className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors"
          >
            {profileSaving ? 'Saving...' : 'Save Profile'}
          </button>
        </div>
      )}

      {/* Framework Tab */}
      {tab === 'framework' && (
        <div className="bg-slate-800 rounded-xl p-6 border border-slate-700 space-y-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-slate-100">Health Optimization Framework</h2>
              <p className="text-sm text-slate-400 mt-1">
                Strategy priorities that guide agent recommendations. Keep one active strategy per category to avoid conflicts.
              </p>
            </div>
            <button
              onClick={syncFrameworksFromProfile}
              disabled={frameworkSaving}
              className="px-3 py-1.5 text-sm rounded-lg border border-slate-600 text-slate-200 hover:bg-slate-700 disabled:opacity-60"
            >
              Sync From Profile
            </button>
          </div>

          {frameworkLoading ? (
            <p className="text-sm text-slate-400">Loading framework settings...</p>
          ) : (
            <div className="space-y-4">
              {Object.entries(frameworkData?.framework_types || {}).map(([typeKey, meta]) => {
                const items = frameworkData?.grouped?.[typeKey] || [];
                const draft = newFrameworkDrafts[typeKey] || { name: '', priority_score: 60, is_active: true };
                return (
                  <div key={typeKey} className="rounded-xl border border-slate-700 bg-slate-900/35 p-4 space-y-3">
                    <div className="flex items-center justify-between gap-2">
                      <div>
                        <h3 className="text-sm font-semibold text-slate-100">{meta.label}</h3>
                        <p className="text-xs text-slate-500">{meta.classifier_label}</p>
                      </div>
                      <span className="text-xs text-slate-500 uppercase tracking-wide">{typeKey.replace(/_/g, ' ')}</span>
                    </div>

                    <details className="rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2">
                      <summary className="cursor-pointer select-none text-xs text-slate-300">
                        Framework description and examples
                      </summary>
                      <div className="mt-2 space-y-2">
                        <p className="text-xs text-slate-400">
                          {meta.description || 'No description available for this framework type.'}
                        </p>
                        <p className="text-xs text-slate-500">
                          Examples:{' '}
                          {(meta.examples && meta.examples.length > 0)
                            ? meta.examples.join(', ')
                            : 'none'}
                        </p>
                      </div>
                    </details>

                    {items.length === 0 ? (
                      <p className="text-xs text-slate-500">No items in this category yet.</p>
                    ) : (
                      <div className="space-y-2">
                        {items.map((item) => (
                          <div key={item.id} className="rounded-lg border border-slate-700 bg-slate-800/80 px-3 py-2">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <div>
                                <p className="text-sm text-slate-100">{item.name}</p>
                                <p className="text-xs text-slate-500">
                                  Source: {item.source}
                                  {item.rationale ? ` - ${item.rationale}` : ''}
                                </p>
                              </div>
                              <button
                                onClick={() => removeFrameworkItem(item.id)}
                                disabled={frameworkSaving}
                                className="text-xs px-2 py-1 rounded-md border border-rose-700/60 text-rose-300 hover:bg-rose-900/30 disabled:opacity-60"
                              >
                                Remove
                              </button>
                            </div>
                            <div className="mt-2 flex flex-wrap items-center gap-3">
                              <label className="inline-flex items-center gap-2 text-xs text-slate-300">
                                <input
                                  type="checkbox"
                                  checked={item.is_active}
                                  onChange={(e) => patchFrameworkItem(item.id, { is_active: e.target.checked })}
                                  disabled={frameworkSaving}
                                  className="accent-emerald-500"
                                />
                                Active
                              </label>
                              <label className="text-xs text-slate-400">
                                Score
                                <input
                                  type="number"
                                  min={0}
                                  max={100}
                                  defaultValue={item.priority_score}
                                  onBlur={(e) => {
                                    const parsed = Number(e.target.value);
                                    if (!Number.isFinite(parsed)) return;
                                    const clamped = Math.max(0, Math.min(100, Math.round(parsed)));
                                    e.target.value = String(clamped);
                                    if (clamped !== item.priority_score) {
                                      patchFrameworkItem(item.id, { priority_score: clamped });
                                    }
                                  }}
                                  className="ml-2 w-20 bg-slate-700 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100 focus:outline-none focus:border-emerald-500"
                                />
                              </label>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    <div className="border-t border-slate-700 pt-3">
                      <p className="text-xs text-slate-500 mb-2">Add strategy</p>
                      <div className="flex flex-col sm:flex-row gap-2">
                        <input
                          type="text"
                          value={draft.name}
                          onChange={(e) => {
                            const value = e.target.value;
                            setNewFrameworkDrafts((prev) => ({
                              ...prev,
                              [typeKey]: { ...draft, name: value },
                            }));
                          }}
                          placeholder={`e.g. ${(meta.examples && meta.examples.length > 0)
                            ? meta.examples.slice(0, 3).join(', ')
                            : 'Add strategy name'}`}
                          className="flex-1 bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500"
                        />
                        <input
                          type="number"
                          min={0}
                          max={100}
                          value={draft.priority_score}
                          onChange={(e) => {
                            const parsed = Number(e.target.value);
                            const clamped = Number.isFinite(parsed) ? Math.max(0, Math.min(100, Math.round(parsed))) : 60;
                            setNewFrameworkDrafts((prev) => ({
                              ...prev,
                              [typeKey]: { ...draft, priority_score: clamped },
                            }));
                          }}
                          className="w-24 bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-emerald-500"
                        />
                        <label className="inline-flex items-center gap-2 text-xs text-slate-300 px-2">
                          <input
                            type="checkbox"
                            checked={draft.is_active}
                            onChange={(e) => {
                              setNewFrameworkDrafts((prev) => ({
                                ...prev,
                                [typeKey]: { ...draft, is_active: e.target.checked },
                              }));
                            }}
                            className="accent-emerald-500"
                          />
                          Active
                        </label>
                        <button
                          onClick={() => createFrameworkItem(typeKey)}
                          disabled={frameworkSaving}
                          className="px-3 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-60 text-white text-sm rounded-lg"
                        >
                          Add
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {frameworkMessage && (
            <p className={`text-sm ${frameworkMessage.toLowerCase().includes('failed') || frameworkMessage.toLowerCase().includes('invalid') ? 'text-rose-400' : 'text-slate-300'}`}>
              {frameworkMessage}
            </p>
          )}
        </div>
      )}

      {/* Models Tab */}
      {tab === 'models' && (
        <div className="bg-slate-800 rounded-xl p-6 border border-slate-700 space-y-5">
          <h2 className="text-lg font-semibold text-slate-100">AI Models</h2>
          <p className="text-sm text-slate-400">
            Select which models to use for the <span className="text-emerald-400 font-medium">{provider}</span> provider.
          </p>

          {availableModels?.presets && (
            <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-3 space-y-2">
              <p className="text-sm text-slate-200 font-medium">Quick Presets</p>
              <p className="text-xs text-slate-400">
                Apply a starting profile, then override any role below.
              </p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(availableModels.presets).map(([key, preset]) => (
                  <button
                    key={key}
                    onClick={() => applyPreset(key)}
                    className="px-3 py-1.5 text-xs rounded-md border border-slate-600 text-slate-200 hover:bg-slate-700"
                    title={preset.description}
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="space-y-4">
            <div>
              <label className="block text-sm text-slate-400 mb-1">Reasoning Model</label>
              <select
                value={reasoningModel}
                onChange={(e) => setReasoningModel(e.target.value)}
                className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2.5 text-slate-100 text-sm focus:outline-none focus:border-emerald-500"
              >
                {availableModels?.reasoning_models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}{m.id === availableModels.default_reasoning ? ' (default)' : ''}
                  </option>
                ))}
              </select>
              <p className="text-xs text-slate-500 mt-1">{availableModels?.role_hints?.reasoning?.description || 'Used for health coaching, advice, and complex analysis.'}</p>
              {selectedReasoningOption && (
                <div className="mt-2 rounded-md border border-slate-700 bg-slate-900/40 p-2 space-y-2">
                  <div className="flex flex-wrap gap-2 text-xs">
                    <span className="px-2 py-0.5 rounded bg-slate-700 text-slate-200">Cost {costBadge(selectedReasoningOption.cost_tier)} ({tierLabel(selectedReasoningOption.cost_tier)})</span>
                    <span className="px-2 py-0.5 rounded bg-slate-700 text-slate-200">Quality {tierLabel(selectedReasoningOption.quality_tier)}</span>
                    <span className="px-2 py-0.5 rounded bg-slate-700 text-slate-200">Speed {tierLabel(selectedReasoningOption.speed_tier)}</span>
                  </div>
                  {selectedReasoningOption.hint && <p className="text-xs text-slate-400">{selectedReasoningOption.hint}</p>}
                  {selectedReasoningOption.best_for && selectedReasoningOption.best_for.length > 0 && (
                    <p className="text-xs text-slate-500">Best for: {selectedReasoningOption.best_for.join(', ')}</p>
                  )}
                </div>
              )}
            </div>
            <div>
              <label className="block text-sm text-slate-400 mb-1">Utility Model</label>
              <select
                value={utilityModel}
                onChange={(e) => setUtilityModel(e.target.value)}
                className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2.5 text-slate-100 text-sm focus:outline-none focus:border-emerald-500"
              >
                {availableModels?.utility_models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}{m.id === availableModels.default_utility ? ' (default)' : ''}
                  </option>
                ))}
              </select>
              <p className="text-xs text-slate-500 mt-1">{availableModels?.role_hints?.utility?.description || 'Used for quick tasks: intent classification, data parsing, summaries.'}</p>
              {selectedUtilityOption && (
                <div className="mt-2 rounded-md border border-slate-700 bg-slate-900/40 p-2 space-y-2">
                  <div className="flex flex-wrap gap-2 text-xs">
                    <span className="px-2 py-0.5 rounded bg-slate-700 text-slate-200">Cost {costBadge(selectedUtilityOption.cost_tier)} ({tierLabel(selectedUtilityOption.cost_tier)})</span>
                    <span className="px-2 py-0.5 rounded bg-slate-700 text-slate-200">Quality {tierLabel(selectedUtilityOption.quality_tier)}</span>
                    <span className="px-2 py-0.5 rounded bg-slate-700 text-slate-200">Speed {tierLabel(selectedUtilityOption.speed_tier)}</span>
                  </div>
                  {selectedUtilityOption.hint && <p className="text-xs text-slate-400">{selectedUtilityOption.hint}</p>}
                  {selectedUtilityOption.best_for && selectedUtilityOption.best_for.length > 0 && (
                    <p className="text-xs text-slate-500">Best for: {selectedUtilityOption.best_for.join(', ')}</p>
                  )}
                </div>
              )}
            </div>
            <div>
              <label className="block text-sm text-slate-400 mb-1">Deep-Thinking Model</label>
              <select
                value={deepThinkingModel}
                onChange={(e) => setDeepThinkingModel(e.target.value)}
                className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2.5 text-slate-100 text-sm focus:outline-none focus:border-emerald-500"
              >
                {availableModels?.deep_thinking_models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}{m.id === availableModels.default_deep_thinking ? ' (default)' : ''}
                  </option>
                ))}
              </select>
              <p className="text-xs text-slate-500 mt-1">{availableModels?.role_hints?.deep_thinking?.description || 'Used for monthly synthesis, root-cause hypotheses, and prompt/guidance tuning proposals.'}</p>
              {selectedDeepOption && (
                <div className="mt-2 rounded-md border border-slate-700 bg-slate-900/40 p-2 space-y-2">
                  <div className="flex flex-wrap gap-2 text-xs">
                    <span className="px-2 py-0.5 rounded bg-slate-700 text-slate-200">Cost {costBadge(selectedDeepOption.cost_tier)} ({tierLabel(selectedDeepOption.cost_tier)})</span>
                    <span className="px-2 py-0.5 rounded bg-slate-700 text-slate-200">Quality {tierLabel(selectedDeepOption.quality_tier)}</span>
                    <span className="px-2 py-0.5 rounded bg-slate-700 text-slate-200">Speed {tierLabel(selectedDeepOption.speed_tier)}</span>
                  </div>
                  {selectedDeepOption.hint && <p className="text-xs text-slate-400">{selectedDeepOption.hint}</p>}
                  {selectedDeepOption.best_for && selectedDeepOption.best_for.length > 0 && (
                    <p className="text-xs text-slate-500">Best for: {selectedDeepOption.best_for.join(', ')}</p>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {(['utility', 'reasoning', 'deep_thinking'] as ModelRole[]).map((role) => (
              <div key={role} className="rounded-lg border border-slate-700 bg-slate-900/35 p-3">
                <p className="text-sm text-slate-100 font-medium">{availableModels?.role_hints?.[role]?.title || role}</p>
                <p className="text-xs text-slate-400 mt-1">{availableModels?.role_hints?.[role]?.description}</p>
                <ul className="mt-2 space-y-1 text-xs text-slate-500 list-disc pl-4">
                  {(availableModels?.role_hints?.[role]?.selection_tips || []).slice(0, 3).map((tip, idx) => (
                    <li key={`${role}-tip-${idx}`}>{tip}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          {modelsMessage && (
            <p className={`text-sm ${modelsMessage.includes('success') ? 'text-emerald-400' : 'text-rose-400'}`}>
              {modelsMessage}
            </p>
          )}

          <button
            onClick={saveModels}
            disabled={modelsSaving}
            className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors"
          >
            {modelsSaving ? 'Saving...' : 'Save Models'}
          </button>
        </div>
      )}

      {tab === 'usage' && (
        <div className="bg-slate-800 rounded-xl p-6 border border-slate-700 space-y-5">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-100">Model Usage</h2>
              <p className="text-sm text-slate-400">
                {usageData?.reset_at
                  ? `Since ${new Date(usageData.reset_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`
                  : 'Since account creation'}
              </p>
            </div>
            {!resetConfirm ? (
              <button
                onClick={() => setResetConfirm(true)}
                className="px-3 py-1.5 text-sm text-slate-400 hover:text-rose-400 border border-slate-600 hover:border-rose-500 rounded-lg transition-colors"
              >
                Reset Counters
              </button>
            ) : (
              <div className="flex gap-2 items-center">
                <span className="text-sm text-slate-400">Reset all?</span>
                <button
                  onClick={resetUsage}
                  className="px-3 py-1.5 text-sm text-white bg-rose-600 hover:bg-rose-500 rounded-lg transition-colors"
                >
                  Confirm
                </button>
                <button
                  onClick={() => setResetConfirm(false)}
                  className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-200 border border-slate-600 rounded-lg transition-colors"
                >
                  Cancel
                </button>
              </div>
            )}
          </div>

          {usageLoading ? (
            <p className="text-sm text-slate-400">Loading...</p>
          ) : usageData && usageData.models.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-slate-400 text-left border-b border-slate-700">
                    <th className="pb-2 font-medium">Model</th>
                    <th className="pb-2 font-medium text-right">Requests</th>
                    <th className="pb-2 font-medium text-right">Input Tokens</th>
                    <th className="pb-2 font-medium text-right">Output Tokens</th>
                    <th className="pb-2 font-medium text-right">Est. Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {usageData.models.map((m) => (
                    <tr key={m.model_id} className="border-b border-slate-700/50 text-slate-200">
                      <td className="py-2.5">
                        <span className="font-medium">{m.model_name}</span>
                        <span className="text-xs text-slate-500 ml-2">{m.model_id}</span>
                      </td>
                      <td className="py-2.5 text-right text-slate-300">{fmtNum(m.request_count)}</td>
                      <td className="py-2.5 text-right text-slate-300">{fmtNum(m.tokens_in)}</td>
                      <td className="py-2.5 text-right text-slate-300">{fmtNum(m.tokens_out)}</td>
                      <td className="py-2.5 text-right font-medium text-emerald-400">{fmtCost(m.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="text-slate-100 font-semibold">
                    <td className="pt-3">Total</td>
                    <td className="pt-3 text-right">{fmtNum(usageData.models.reduce((s, m) => s + m.request_count, 0))}</td>
                    <td className="pt-3 text-right">{fmtNum(usageData.models.reduce((s, m) => s + m.tokens_in, 0))}</td>
                    <td className="pt-3 text-right">{fmtNum(usageData.models.reduce((s, m) => s + m.tokens_out, 0))}</td>
                    <td className="pt-3 text-right text-emerald-400">{fmtCost(usageData.total_cost_usd)}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          ) : (
            <p className="text-sm text-slate-400">No usage data yet. Start chatting to see token usage here.</p>
          )}

          <p className="text-xs text-slate-500">
            Costs are estimates based on pricing in <code className="text-slate-400">data/models.json</code>. Edit that file to update rates.
          </p>
        </div>
      )}

      {tab === 'adaptation' && (
        <div className="space-y-5">
          <div className="bg-slate-800 rounded-xl p-6 border border-slate-700 space-y-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-slate-100">Adaptation Engine</h2>
                <p className="text-sm text-slate-400">Daily/weekly/monthly longitudinal runs with approval-gated adjustments.</p>
              </div>
              <button
                onClick={fetchAnalysis}
                className="px-3 py-1.5 text-sm text-slate-200 border border-slate-600 rounded-lg hover:bg-slate-700"
              >
                Refresh
              </button>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <select
                value={analysisRunType}
                onChange={(e) => setAnalysisRunType(e.target.value as 'daily' | 'weekly' | 'monthly')}
                className="bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-emerald-500"
              >
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
              </select>
              <button
                onClick={triggerAnalysisRun}
                disabled={analysisLoading}
                className="px-3 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-60 text-white text-sm rounded-lg"
              >
                Run Selected
              </button>
              <button
                onClick={triggerDueAnalyses}
                disabled={analysisLoading}
                className="px-3 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-60 text-slate-100 text-sm rounded-lg border border-slate-600"
              >
                Run Due Windows
              </button>
            </div>

            {analysisMessage && (
              <p className={`text-sm ${analysisMessage.toLowerCase().includes('failed') || analysisMessage.toLowerCase().includes('error') ? 'text-rose-400' : 'text-emerald-400'}`}>
                {analysisMessage}
              </p>
            )}
          </div>

          <div className="bg-slate-800 rounded-xl p-6 border border-slate-700 space-y-3">
            <h3 className="text-base font-semibold text-slate-100">Recent Runs</h3>
            {analysisRuns.length === 0 ? (
              <p className="text-sm text-slate-400">No analysis runs yet.</p>
            ) : (
              <div className="space-y-2">
                {analysisRuns.slice(0, 12).map((run) => (
                  <div key={run.id} className="rounded-lg border border-slate-700 bg-slate-900/35 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-sm text-slate-200">
                        <span className="font-medium">{run.run_type}</span>
                        <span className="text-slate-500 ml-2">{run.period_start}{run.period_start !== run.period_end ? ` -> ${run.period_end}` : ''}</span>
                      </div>
                      <span className={`text-xs px-2 py-0.5 rounded-full ${
                        run.status === 'completed'
                          ? 'bg-emerald-900/50 text-emerald-300'
                          : run.status === 'failed'
                            ? 'bg-rose-900/50 text-rose-300'
                            : 'bg-slate-700 text-slate-300'
                      }`}>
                        {run.status}
                      </span>
                    </div>
                    <div className="text-xs text-slate-400 mt-1">
                      Confidence: {run.confidence != null ? `${Math.round(run.confidence * 100)}%` : 'n/a'}
                      {run.created_at ? ` · ${new Date(run.created_at).toLocaleString()}` : ''}
                    </div>
                    {run.summary_markdown && (
                      <p className="text-sm text-slate-300 mt-2 line-clamp-3">{run.summary_markdown}</p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="bg-slate-800 rounded-xl p-6 border border-slate-700 space-y-3">
            <h3 className="text-base font-semibold text-slate-100">Adjustment Proposals</h3>
            {analysisProposals.length === 0 ? (
              <p className="text-sm text-slate-400">No proposals yet.</p>
            ) : (
              <div className="space-y-2">
                {analysisProposals.slice(0, 20).map((proposal) => (
                  <div key={proposal.id} className="rounded-lg border border-slate-700 bg-slate-900/35 p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="text-sm text-slate-100 font-medium">{proposal.title}</p>
                        <p className="text-xs text-slate-400 mt-1">
                          {proposal.proposal_kind} · run #{proposal.analysis_run_id}
                          {proposal.confidence != null ? ` · ${Math.round(proposal.confidence * 100)}%` : ''}
                        </p>
                      </div>
                      <span className={`text-xs px-2 py-0.5 rounded-full ${
                        proposal.status === 'approved' || proposal.status === 'applied'
                          ? 'bg-emerald-900/50 text-emerald-300'
                          : proposal.status === 'rejected'
                            ? 'bg-rose-900/50 text-rose-300'
                            : 'bg-amber-900/50 text-amber-300'
                      }`}>
                        {proposal.status}
                      </span>
                    </div>
                    <p className="text-sm text-slate-300 mt-2">{proposal.rationale}</p>
                    {proposal.status === 'pending' && (
                      <div className="flex gap-2 mt-3">
                        <button
                          onClick={() => reviewAnalysisProposal(proposal.id, 'approve')}
                          className="px-3 py-1.5 text-xs bg-emerald-600 hover:bg-emerald-500 text-white rounded-md"
                        >
                          Approve
                        </button>
                        <button
                          onClick={() => reviewAnalysisProposal(proposal.id, 'reject')}
                          className="px-3 py-1.5 text-xs bg-rose-600 hover:bg-rose-500 text-white rounded-md"
                        >
                          Reject
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {tab === 'security' && (
        <div className="space-y-5">
          <div className="bg-slate-800 rounded-xl p-6 border border-slate-700 space-y-4">
            <h2 className="text-lg font-semibold text-slate-100">Change Password</h2>
            <p className="text-sm text-slate-400">Update your account password.</p>

            <div className="space-y-3">
              <div>
                <label className="block text-sm text-slate-400 mb-1">Current Password</label>
                <input
                  type="password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-emerald-500"
                />
              </div>
              <div>
                <label className="block text-sm text-slate-400 mb-1">New Password</label>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-emerald-500"
                />
              </div>
              <div>
                <label className="block text-sm text-slate-400 mb-1">Confirm New Password</label>
                <input
                  type="password"
                  value={confirmNewPassword}
                  onChange={(e) => setConfirmNewPassword(e.target.value)}
                  className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-emerald-500"
                />
              </div>
            </div>

            {passwordMessage && (
              <p className={`text-sm ${passwordMessage.includes('success') ? 'text-emerald-400' : 'text-rose-400'}`}>
                {passwordMessage}
              </p>
            )}

            <button
              onClick={changePassword}
              disabled={passwordSaving}
              className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors"
            >
              {passwordSaving ? 'Updating...' : 'Change Password'}
            </button>
          </div>

          <div className="bg-slate-800 rounded-xl p-6 border border-rose-700/40 space-y-4">
            <h2 className="text-lg font-semibold text-rose-300">Reset User Data</h2>
            <p className="text-sm text-slate-400">
              This removes your profile data, logs, chat history, summaries, checklists, templates, notifications, and feedback entries.
              Your account and password are kept.
            </p>

            <div className="space-y-3">
              <div>
                <label className="block text-sm text-slate-400 mb-1">Current Password</label>
                <input
                  type="password"
                  value={resetPassword}
                  onChange={(e) => setResetPassword(e.target.value)}
                  className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-rose-500"
                />
              </div>
              <div>
                <label className="block text-sm text-slate-400 mb-1">Type RESET to confirm</label>
                <input
                  type="text"
                  value={resetConfirmation}
                  onChange={(e) => setResetConfirmation(e.target.value)}
                  placeholder="RESET"
                  className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-rose-500"
                />
              </div>
            </div>

            {resetDataMessage && (
              <p className={`text-sm ${resetDataMessage.includes('successfully') ? 'text-emerald-400' : 'text-rose-400'}`}>
                {resetDataMessage}
              </p>
            )}

            <button
              onClick={resetUserData}
              disabled={resetDataSaving}
              className="px-4 py-2 bg-rose-600 hover:bg-rose-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors"
            >
              {resetDataSaving ? 'Resetting...' : 'Reset My Data'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
