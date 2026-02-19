import { useState, useEffect, useCallback } from 'react';
import { apiClient } from '../api/client';

interface Specialist {
  id: string;
  name: string;
  description: string;
  color: string;
}

interface SpecialistsResponse {
  specialists: Specialist[];
  active: string;
}

export default function Specialists() {
  const [specialists, setSpecialists] = useState<Specialist[]>([]);
  const [active, setActive] = useState<string>('auto');
  const [selected, setSelected] = useState<string>('auto');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  const fetchSpecialists = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiClient.get<SpecialistsResponse>('/api/specialists');
      setSpecialists(data.specialists);
      setActive(data.active);
      setSelected(data.active);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSpecialists();
  }, [fetchSpecialists]);

  const save = async () => {
    setSaving(true);
    setMessage('');
    try {
      await apiClient.put('/api/specialists', { active_specialist: selected });
      setActive(selected);
      setMessage('Specialist updated successfully.');
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to update specialist.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-3.5rem)]">
        <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  // Build the full list with "auto" prepended
  const allOptions: Specialist[] = [
    { id: 'auto', name: 'Auto', description: 'Automatically selects the best specialist for each conversation. Recommended for most users.', color: '#10b981' },
    ...specialists,
  ];

  return (
    <div className="max-w-4xl mx-auto px-4 py-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100">Specialists</h1>
        <p className="text-slate-400 text-sm mt-1">Choose which AI specialist handles your health coaching conversations.</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {allOptions.map((spec) => {
          const isSelected = selected === spec.id;
          const isCurrentlyActive = active === spec.id;

          return (
            <button
              key={spec.id}
              onClick={() => setSelected(spec.id)}
              className={`relative text-left p-5 rounded-xl border transition-all ${
                isSelected
                  ? 'border-emerald-500 bg-emerald-900/20 ring-1 ring-emerald-500/50'
                  : 'border-slate-700 bg-slate-800 hover:border-slate-600'
              }`}
            >
              {/* Color accent bar */}
              <div
                className="absolute top-0 left-0 right-0 h-1 rounded-t-xl"
                style={{ backgroundColor: spec.color }}
              />

              <div className="flex items-center gap-2 mt-1">
                <h3 className={`font-semibold text-sm ${isSelected ? 'text-emerald-400' : 'text-slate-200'}`}>
                  {spec.name}
                </h3>
                {isCurrentlyActive && (
                  <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-emerald-900/50 text-emerald-400">
                    Active
                  </span>
                )}
                {spec.id === 'auto' && (
                  <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-sky-900/50 text-sky-400">
                    Recommended
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-400 mt-2 leading-relaxed">
                {spec.description}
              </p>

              {/* Radio indicator */}
              <div className={`absolute top-4 right-4 w-4 h-4 rounded-full border-2 flex items-center justify-center ${
                isSelected ? 'border-emerald-500' : 'border-slate-600'
              }`}>
                {isSelected && <div className="w-2 h-2 rounded-full bg-emerald-500" />}
              </div>
            </button>
          );
        })}
      </div>

      <div className="mt-6 flex items-center gap-4">
        <button
          onClick={save}
          disabled={saving || selected === active}
          className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors"
        >
          {saving ? 'Saving...' : 'Save Selection'}
        </button>
        {message && (
          <span className={`text-sm ${message.includes('success') ? 'text-emerald-400' : 'text-rose-400'}`}>
            {message}
          </span>
        )}
      </div>
    </div>
  );
}
