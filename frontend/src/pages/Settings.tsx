import { useState, useEffect, useCallback, type KeyboardEvent } from 'react';
import { apiClient } from '../api/client';

type Tab = 'apikey' | 'profile' | 'models';
type Provider = 'anthropic' | 'openai' | 'google';
type WeightUnit = 'kg' | 'lb';
type HeightUnit = 'cm' | 'ft';

// Conversion helpers
const lbToKg = (lb: number) => Math.round(lb * 0.453592 * 10) / 10;
const kgToLb = (kg: number) => Math.round(kg / 0.453592 * 10) / 10;
const ftInToCm = (ft: number, inches: number) => Math.round((ft * 30.48 + inches * 2.54) * 10) / 10;
const cmToFtIn = (cm: number): [number, number] => {
  const totalIn = cm / 2.54;
  const ft = Math.floor(totalIn / 12);
  const inches = Math.round(totalIn % 12);
  return [ft, inches];
};

interface ProfileData {
  ai_provider: string;
  has_api_key: boolean;
  reasoning_model: string;
  utility_model: string;
  age: number | null;
  sex: string | null;
  height_cm: number | null;
  current_weight_kg: number | null;
  goal_weight_kg: number | null;
  fitness_level: string | null;
  timezone: string | null;
  medical_conditions: string | null;
  medications: string | null;
  supplements: string | null;
  family_history: string | null;
  dietary_preferences: string | null;
  health_goals: string | null;
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
  const [tab, setTab] = useState<Tab>('apikey');
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [loading, setLoading] = useState(true);

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
  const [fitnessLevel, setFitnessLevel] = useState('');
  const [timezone, setTimezone] = useState('');
  const [medicalConditionsTags, setMedicalConditionsTags] = useState<string[]>([]);
  const [medicationsTags, setMedicationsTags] = useState<string[]>([]);
  const [supplementsTags, setSupplementsTags] = useState<string[]>([]);
  const [familyHistoryTags, setFamilyHistoryTags] = useState<string[]>([]);
  const [dietaryPreferencesTags, setDietaryPreferencesTags] = useState<string[]>([]);
  const [healthGoalsTags, setHealthGoalsTags] = useState<string[]>([]);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileMessage, setProfileMessage] = useState('');

  // Models state
  const [reasoningModel, setReasoningModel] = useState('');
  const [utilityModel, setUtilityModel] = useState('');
  const [modelsSaving, setModelsSaving] = useState(false);
  const [modelsMessage, setModelsMessage] = useState('');
  const [availableModels, setAvailableModels] = useState<{
    reasoning_models: { id: string; name: string }[];
    utility_models: { id: string; name: string }[];
    default_reasoning: string;
    default_utility: string;
  } | null>(null);

  // Parse stored string into tags (handles both JSON arrays and comma-separated)
  const parseToTags = (val: string | null): string[] => {
    if (!val) return [];
    const trimmed = val.trim();
    if (trimmed.startsWith('[')) {
      try {
        const arr = JSON.parse(trimmed);
        if (Array.isArray(arr)) return arr.map((s: string) => s.trim()).filter(Boolean);
      } catch { /* fall through */ }
    }
    return trimmed.split(',').map(s => s.trim()).filter(Boolean);
  };

  const fetchProfile = useCallback(async () => {
    setLoading(true);
    try {
      const p = await apiClient.get<ProfileData>('/api/settings/profile');
      setProfile(p);
      setProvider((p.ai_provider || 'anthropic') as Provider);
      setHasKey(p.has_api_key);
      setAge(p.age?.toString() ?? '');
      setSex(p.sex ?? '');

      // Height: store cm internally, populate both unit views
      const cm = p.height_cm;
      if (cm) {
        setHeightCm(cm.toString());
        const [ft, inches] = cmToFtIn(cm);
        setHeightFt(ft.toString());
        setHeightIn(inches.toString());
      }

      // Weight: store kg internally, populate display value based on unit
      setCurrentWeight(p.current_weight_kg?.toString() ?? '');
      setGoalWeight(p.goal_weight_kg?.toString() ?? '');

      setFitnessLevel(p.fitness_level ?? '');
      setTimezone(p.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone);
      setMedicalConditionsTags(parseToTags(p.medical_conditions));
      setMedicationsTags(parseToTags(p.medications));
      setSupplementsTags(parseToTags(p.supplements));
      setFamilyHistoryTags(parseToTags(p.family_history));
      setDietaryPreferencesTags(parseToTags(p.dietary_preferences));
      setHealthGoalsTags(parseToTags(p.health_goals));
      setReasoningModel(p.reasoning_model ?? '');
      setUtilityModel(p.utility_model ?? '');
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchModels = useCallback(async (prov: string) => {
    try {
      const m = await apiClient.get<{
        reasoning_models: { id: string; name: string }[];
        utility_models: { id: string; name: string }[];
        default_reasoning: string;
        default_utility: string;
      }>(`/api/settings/models?provider=${prov}`);
      setAvailableModels(m);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    fetchProfile();
  }, [fetchProfile]);

  useEffect(() => {
    fetchModels(provider);
  }, [provider, fetchModels]);

  const saveApiKey = async () => {
    if (!apiKey.trim()) return;
    setKeySaving(true);
    setKeyMessage('');
    try {
      await apiClient.put('/api/settings/api-key', {
        ai_provider: provider,
        api_key: apiKey,
        reasoning_model: reasoningModel || undefined,
        utility_model: utilityModel || undefined,
      });
      setHasKey(true);
      setKeyMessage('API key saved successfully.');
      setKeyValid(null);
      setApiKey('');
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
        heightCmVal = parseFloat(heightCm);
      } else if (heightUnit === 'ft' && (heightFt || heightIn)) {
        heightCmVal = ftInToCm(parseFloat(heightFt || '0'), parseFloat(heightIn || '0'));
      }

      // Convert weight to kg
      let currentWeightKg: number | null = null;
      let goalWeightKg: number | null = null;
      if (currentWeight) {
        currentWeightKg = weightUnit === 'lb' ? lbToKg(parseFloat(currentWeight)) : parseFloat(currentWeight);
      }
      if (goalWeight) {
        goalWeightKg = weightUnit === 'lb' ? lbToKg(parseFloat(goalWeight)) : parseFloat(goalWeight);
      }

      const tagsToString = (tags: string[]) => tags.length > 0 ? tags.join(', ') : null;

      await apiClient.put('/api/settings/profile', {
        age: age ? parseInt(age) : null,
        sex: sex || null,
        height_cm: heightCmVal,
        current_weight_kg: currentWeightKg,
        goal_weight_kg: goalWeightKg,
        fitness_level: fitnessLevel || null,
        timezone: timezone || null,
        medical_conditions: tagsToString(medicalConditionsTags),
        medications: tagsToString(medicationsTags),
        supplements: tagsToString(supplementsTags),
        family_history: tagsToString(familyHistoryTags),
        dietary_preferences: tagsToString(dietaryPreferencesTags),
        health_goals: tagsToString(healthGoalsTags),
      });
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
      await apiClient.put('/api/settings/models', {
        reasoning_model: reasoningModel,
        utility_model: utilityModel,
      });
      setModelsMessage('Models saved successfully.');
    } catch (e: unknown) {
      setModelsMessage(e instanceof Error ? e.message : 'Failed to save models.');
    } finally {
      setModelsSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-3.5rem)]">
        <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-6">
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
        <TabButton active={tab === 'apikey'} label="API Key" onClick={() => setTab('apikey')} />
        <TabButton active={tab === 'profile'} label="Profile" onClick={() => setTab('profile')} />
        <TabButton active={tab === 'models'} label="Models" onClick={() => setTab('models')} />
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
                      if (currentWeight) setCurrentWeight(kgToLb(parseFloat(currentWeight)).toString());
                      if (goalWeight) setGoalWeight(kgToLb(parseFloat(goalWeight)).toString());
                    } else if (newUnit === 'kg' && weightUnit === 'lb') {
                      if (currentWeight) setCurrentWeight(lbToKg(parseFloat(currentWeight)).toString());
                      if (goalWeight) setGoalWeight(lbToKg(parseFloat(goalWeight)).toString());
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
            <TagInput
              label="Medications"
              hint="e.g. metformin 500mg, lisinopril 10mg"
              tags={medicationsTags}
              onChange={setMedicationsTags}
            />
            <TagInput
              label="Supplements"
              hint="e.g. vitamin D 2000 IU, omega-3"
              tags={supplementsTags}
              onChange={setSupplementsTags}
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

      {/* Models Tab */}
      {tab === 'models' && (
        <div className="bg-slate-800 rounded-xl p-6 border border-slate-700 space-y-5">
          <h2 className="text-lg font-semibold text-slate-100">AI Models</h2>
          <p className="text-sm text-slate-400">
            Select which models to use for the <span className="text-emerald-400 font-medium">{provider}</span> provider.
          </p>

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
              <p className="text-xs text-slate-500 mt-1">Used for health coaching, advice, and complex analysis.</p>
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
              <p className="text-xs text-slate-500 mt-1">Used for quick tasks: intent classification, data parsing, summaries.</p>
            </div>
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
    </div>
  );
}
