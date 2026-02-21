import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiClient } from '../api/client';

type ViewMode = 'active' | 'archived' | 'all';

interface MealTemplate {
  id: number;
  name: string;
  ingredients: string[];
  servings: number;
  notes?: string | null;
  is_archived: boolean;
  archived_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  usage_count?: number;
  last_logged_at?: string | null;
  version_count?: number;
  macros_per_serving: {
    calories?: number | null;
    protein_g?: number | null;
    carbs_g?: number | null;
    fat_g?: number | null;
    fiber_g?: number | null;
    sodium_mg?: number | null;
  };
}

interface VersionItem {
  id: number;
  version_number: number;
  change_note?: string | null;
  created_at?: string | null;
}

interface InsightItem {
  template_id: number;
  template_name: string;
  usage_count: number;
  signal_count: number;
  energy_avg?: number | null;
  gi_event_rate?: number | null;
  gi_severity_avg?: number | null;
  weight_delta_next_day_kg_avg?: number | null;
}

function formatDate(value?: string | null): string {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function metric(value?: number | null, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return Number(value).toFixed(digits);
}

export default function Menu() {
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [viewMode, setViewMode] = useState<ViewMode>('active');
  const [templates, setTemplates] = useState<MealTemplate[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selected, setSelected] = useState<MealTemplate | null>(null);
  const [versions, setVersions] = useState<VersionItem[]>([]);
  const [insights, setInsights] = useState<InsightItem[]>([]);

  const loadTemplates = useCallback(async () => {
    const rows = await apiClient.get<MealTemplate[]>('/api/menu/templates?include_archived=true');
    setTemplates(rows);
    if (rows.length > 0 && !selectedId) {
      setSelectedId(rows[0].id);
    }
  }, [selectedId]);

  const loadInsights = useCallback(async () => {
    const out = await apiClient.get<{ items: InsightItem[] }>('/api/menu/insights?since_days=90');
    setInsights(out.items || []);
  }, []);

  const loadDetail = useCallback(async (id: number) => {
    const tpl = await apiClient.get<MealTemplate>(`/api/menu/templates/${id}`);
    setSelected(tpl);
    const versionOut = await apiClient.get<{ versions: VersionItem[] }>(`/api/menu/templates/${id}/versions`);
    setVersions(versionOut.versions || []);
  }, []);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setMessage('');
    try {
      await Promise.all([loadTemplates(), loadInsights()]);
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to load menu');
    } finally {
      setLoading(false);
    }
  }, [loadTemplates, loadInsights]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      setVersions([]);
      return;
    }
    loadDetail(selectedId).catch((e: unknown) => {
      setMessage(e instanceof Error ? e.message : 'Failed to load meal detail');
    });
  }, [selectedId, loadDetail]);

  const visibleTemplates = useMemo(() => {
    if (viewMode === 'all') return templates;
    if (viewMode === 'archived') return templates.filter((t) => t.is_archived);
    return templates.filter((t) => !t.is_archived);
  }, [templates, viewMode]);

  const insightByTemplate = useMemo(() => {
    const map = new Map<number, InsightItem>();
    for (const item of insights) map.set(item.template_id, item);
    return map;
  }, [insights]);

  const topEnergy = useMemo(() => {
    return [...insights]
      .filter((i) => i.energy_avg !== null && i.energy_avg !== undefined)
      .sort((a, b) => (b.energy_avg || 0) - (a.energy_avg || 0))[0];
  }, [insights]);

  const worstGi = useMemo(() => {
    return [...insights]
      .filter((i) => i.gi_event_rate !== null && i.gi_event_rate !== undefined)
      .sort((a, b) => (b.gi_event_rate || 0) - (a.gi_event_rate || 0))[0];
  }, [insights]);

  const archiveToggle = async (template: MealTemplate, archive: boolean) => {
    setMessage('');
    try {
      await apiClient.post(`/api/menu/templates/${template.id}/archive`, { archive });
      await loadAll();
      if (selectedId === template.id) {
        await loadDetail(template.id);
      }
      setMessage(archive ? 'Menu item archived.' : 'Menu item restored.');
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to update menu item');
    }
  };

  const deleteTemplate = async (template: MealTemplate) => {
    if (!confirm(`Delete "${template.name}" from menu? This keeps historical logs.`)) return;
    setMessage('');
    try {
      await apiClient.delete(`/api/menu/templates/${template.id}`);
      if (selectedId === template.id) setSelectedId(null);
      await loadAll();
      setMessage('Menu item deleted.');
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to delete menu item');
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Menu</h1>
          <p className="text-sm text-slate-400">
            Chat-first menu. Log meals naturally, then save or update base meals only when you choose.
          </p>
        </div>
        <div className="text-xs text-slate-400 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2">
          Tip: say <span className="text-slate-200">“save this meal to menu as Power Pancakes”</span>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-3">
          <p className="text-xs text-slate-400">Most used meal</p>
          <p className="text-sm text-slate-100 mt-1 truncate">
            {insights[0]?.template_name || 'No data yet'}
          </p>
          <p className="text-xs text-slate-400 mt-1">{insights[0]?.usage_count || 0} logs</p>
        </div>
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-3">
          <p className="text-xs text-slate-400">Best energy response</p>
          <p className="text-sm text-slate-100 mt-1 truncate">{topEnergy?.template_name || 'No signals yet'}</p>
          <p className="text-xs text-emerald-300 mt-1">Energy avg {metric(topEnergy?.energy_avg, 2)}</p>
        </div>
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-3">
          <p className="text-xs text-slate-400">Highest GI issue rate</p>
          <p className="text-sm text-slate-100 mt-1 truncate">{worstGi?.template_name || 'No GI data yet'}</p>
          <p className="text-xs text-rose-300 mt-1">GI rate {metric((worstGi?.gi_event_rate || 0) * 100, 0)}%</p>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={() => setViewMode('active')}
          className={`px-3 py-1.5 rounded-lg text-sm border ${
            viewMode === 'active'
              ? 'bg-emerald-600/20 text-emerald-300 border-emerald-500/50'
              : 'bg-slate-800 text-slate-300 border-slate-700'
          }`}
        >
          Active
        </button>
        <button
          onClick={() => setViewMode('archived')}
          className={`px-3 py-1.5 rounded-lg text-sm border ${
            viewMode === 'archived'
              ? 'bg-emerald-600/20 text-emerald-300 border-emerald-500/50'
              : 'bg-slate-800 text-slate-300 border-slate-700'
          }`}
        >
          Archived
        </button>
        <button
          onClick={() => setViewMode('all')}
          className={`px-3 py-1.5 rounded-lg text-sm border ${
            viewMode === 'all'
              ? 'bg-emerald-600/20 text-emerald-300 border-emerald-500/50'
              : 'bg-slate-800 text-slate-300 border-slate-700'
          }`}
        >
          All
        </button>
      </div>

      {message && <p className="text-sm text-emerald-300">{message}</p>}

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(320px,360px)] gap-4">
        <div className="space-y-3">
          {loading ? (
            <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 text-sm text-slate-400">Loading menu...</div>
          ) : visibleTemplates.length === 0 ? (
            <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 text-sm text-slate-400">
              No menu items yet. Log a meal in chat and save it when prompted.
            </div>
          ) : (
            visibleTemplates.map((tpl) => {
              const insight = insightByTemplate.get(tpl.id);
              const active = selectedId === tpl.id;
              return (
                <button
                  key={tpl.id}
                  type="button"
                  onClick={() => setSelectedId(tpl.id)}
                  className={`w-full text-left rounded-xl border p-4 transition ${
                    active
                      ? 'border-emerald-500/70 bg-slate-800 shadow-[0_0_0_1px_rgba(16,185,129,0.35)]'
                      : 'border-slate-700 bg-slate-800/80 hover:border-slate-600'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-slate-100 font-medium truncate">{tpl.name}</p>
                      <p className="text-xs text-slate-400 mt-1">
                        {tpl.usage_count || 0} logs • updated {formatDate(tpl.updated_at)}
                      </p>
                    </div>
                    {tpl.is_archived && (
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-700 border border-slate-600 text-slate-300">
                        archived
                      </span>
                    )}
                  </div>
                  <div className="mt-3 grid grid-cols-4 gap-2 text-xs">
                    <div><span className="text-slate-500">P</span> <span className="text-slate-200">{metric(tpl.macros_per_serving?.protein_g, 0)}g</span></div>
                    <div><span className="text-slate-500">C</span> <span className="text-slate-200">{metric(tpl.macros_per_serving?.carbs_g, 0)}g</span></div>
                    <div><span className="text-slate-500">F</span> <span className="text-slate-200">{metric(tpl.macros_per_serving?.fat_g, 0)}g</span></div>
                    <div><span className="text-slate-500">Kcal</span> <span className="text-slate-200">{metric(tpl.macros_per_serving?.calories, 0)}</span></div>
                  </div>
                  {insight && (
                    <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-300">
                      <span className="px-2 py-1 rounded bg-slate-700 border border-slate-600">
                        Energy {metric(insight.energy_avg, 2)}
                      </span>
                      <span className="px-2 py-1 rounded bg-slate-700 border border-slate-600">
                        GI {metric((insight.gi_event_rate || 0) * 100, 0)}%
                      </span>
                      <span className="px-2 py-1 rounded bg-slate-700 border border-slate-600">
                        ΔWt {metric(insight.weight_delta_next_day_kg_avg, 3)} kg
                      </span>
                    </div>
                  )}
                </button>
              );
            })
          )}
        </div>

        <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 h-fit lg:sticky lg:top-20">
          {!selected ? (
            <p className="text-sm text-slate-400">Select a menu item to view details.</p>
          ) : (
            <div className="space-y-4">
              <div>
                <div className="flex items-center justify-between gap-2">
                  <h2 className="text-lg font-semibold text-slate-100 truncate">{selected.name}</h2>
                  <span className="text-xs text-slate-400">{selected.usage_count || 0} logs</span>
                </div>
                <p className="text-xs text-slate-400 mt-1">Last used: {formatDate(selected.last_logged_at)}</p>
              </div>

              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="bg-slate-700/60 border border-slate-600 rounded-lg px-2 py-1.5">Calories: {metric(selected.macros_per_serving?.calories, 0)}</div>
                <div className="bg-slate-700/60 border border-slate-600 rounded-lg px-2 py-1.5">Protein: {metric(selected.macros_per_serving?.protein_g, 0)}g</div>
                <div className="bg-slate-700/60 border border-slate-600 rounded-lg px-2 py-1.5">Carbs: {metric(selected.macros_per_serving?.carbs_g, 0)}g</div>
                <div className="bg-slate-700/60 border border-slate-600 rounded-lg px-2 py-1.5">Fat: {metric(selected.macros_per_serving?.fat_g, 0)}g</div>
              </div>

              <div>
                <p className="text-xs uppercase tracking-wide text-slate-400 mb-2">Ingredients</p>
                {selected.ingredients?.length ? (
                  <div className="flex flex-wrap gap-2">
                    {selected.ingredients.map((item, idx) => (
                      <span key={`${item}-${idx}`} className="text-xs px-2 py-1 rounded bg-slate-700 border border-slate-600 text-slate-200">
                        {item}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-slate-400">No ingredient list stored.</p>
                )}
              </div>

              <div>
                <p className="text-xs uppercase tracking-wide text-slate-400 mb-2">Version History</p>
                {versions.length === 0 ? (
                  <p className="text-sm text-slate-400">No versions saved yet.</p>
                ) : (
                  <div className="space-y-2 max-h-44 overflow-auto pr-1">
                    {versions.map((v) => (
                      <div key={v.id} className="text-xs bg-slate-700/60 border border-slate-600 rounded-lg px-2 py-2">
                        <p className="text-slate-200">v{v.version_number} • {formatDate(v.created_at)}</p>
                        {v.change_note && <p className="text-slate-400 mt-1">{v.change_note}</p>}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex flex-wrap gap-2 pt-2 border-t border-slate-700">
                {selected.is_archived ? (
                  <button
                    onClick={() => archiveToggle(selected, false)}
                    className="px-3 py-2 text-sm rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white"
                  >
                    Restore
                  </button>
                ) : (
                  <button
                    onClick={() => archiveToggle(selected, true)}
                    className="px-3 py-2 text-sm rounded-lg bg-slate-700 hover:bg-slate-600 border border-slate-600 text-slate-100"
                  >
                    Archive
                  </button>
                )}
                <button
                  onClick={() => deleteTemplate(selected)}
                  className="px-3 py-2 text-sm rounded-lg bg-rose-900/40 hover:bg-rose-900/60 border border-rose-700/70 text-rose-200"
                >
                  Delete
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

