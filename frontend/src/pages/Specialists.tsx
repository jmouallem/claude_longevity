import { Fragment, type ReactNode, useCallback, useEffect, useMemo, useState } from 'react';
import { apiClient } from '../api/client';

interface Specialist {
  id: string;
  name: string;
  description: string;
  color: string;
  custom?: boolean;
}

interface SpecialistsResponse {
  specialists: Specialist[];
  active: string;
  protected_ids: string[];
}

interface PromptsResponse {
  system_prompt: string;
  specialist_prompts: Record<string, string>;
}

const DEFAULT_SPECIALISTS: Specialist[] = [
  { id: 'nutritionist', name: 'Nutritionist', description: 'Food, diet, macros, meal planning', color: 'green' },
  { id: 'sleep_expert', name: 'Sleep Expert', description: 'Sleep optimization, circadian rhythm', color: 'indigo' },
  { id: 'movement_coach', name: 'Movement Coach', description: 'Exercise, workouts, training', color: 'orange' },
  { id: 'supplement_auditor', name: 'Supplement Auditor', description: 'Supplements, timing, interactions', color: 'purple' },
  { id: 'safety_clinician', name: 'Safety Clinician', description: 'Medical safety, vitals concerns', color: 'red' },
];

const COLOR_MAP: Record<string, string> = {
  blue: '#3b82f6',
  green: '#10b981',
  indigo: '#6366f1',
  orange: '#f59e0b',
  purple: '#a855f7',
  red: '#ef4444',
  emerald: '#10b981',
  sky: '#0ea5e9',
  slate: '#64748b',
  cyan: '#06b6d4',
  pink: '#ec4899',
  amber: '#f59e0b',
  lime: '#84cc16',
  teal: '#14b8a6',
};

function colorValue(token: string): string {
  const key = token.trim().toLowerCase();
  return COLOR_MAP[key] ?? token ?? '#64748b';
}

function renderInline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const tokenRegex = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null = tokenRegex.exec(text);

  while (match) {
    if (match.index > lastIndex) {
      out.push(text.slice(lastIndex, match.index));
    }
    const token = match[0];
    if (token.startsWith('**') && token.endsWith('**')) {
      out.push(<strong key={`${match.index}-b`}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith('`') && token.endsWith('`')) {
      out.push(
        <code key={`${match.index}-c`} className="px-1.5 py-0.5 rounded bg-slate-900/60 text-sky-200 text-[0.92em]">
          {token.slice(1, -1)}
        </code>
      );
    } else if (token.startsWith('*') && token.endsWith('*')) {
      out.push(<em key={`${match.index}-i`}>{token.slice(1, -1)}</em>);
    } else {
      out.push(token);
    }
    lastIndex = match.index + token.length;
    match = tokenRegex.exec(text);
  }
  if (lastIndex < text.length) {
    out.push(text.slice(lastIndex));
  }
  return out;
}

function renderMarkdown(content: string): ReactNode[] {
  const blocks: ReactNode[] = [];
  const lines = content.replace(/\r\n/g, '\n').split('\n');
  let i = 0;

  while (i < lines.length) {
    const rawLine = lines[i];
    const line = rawLine.trim();
    if (!line) {
      i += 1;
      continue;
    }

    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      blocks.push(
        <p key={`h-${i}`} className={level <= 2 ? 'text-base font-semibold text-slate-50' : 'text-sm font-semibold text-slate-100'}>
          {renderInline(headingMatch[2])}
        </p>
      );
      i += 1;
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*]\s+/, ''));
        i += 1;
      }
      blocks.push(
        <ul key={`ul-${i}`} className="list-disc pl-5 space-y-1.5 text-slate-100/95">
          {items.map((item, idx) => <li key={`uli-${idx}`}>{renderInline(item)}</li>)}
        </ul>
      );
      continue;
    }

    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^\d+\.\s+/, ''));
        i += 1;
      }
      blocks.push(
        <ol key={`ol-${i}`} className="list-decimal pl-5 space-y-1.5 text-slate-100/95">
          {items.map((item, idx) => <li key={`oli-${idx}`}>{renderInline(item)}</li>)}
        </ol>
      );
      continue;
    }

    const paragraphLines: string[] = [rawLine.trimEnd()];
    i += 1;
    while (i < lines.length) {
      const next = lines[i].trim();
      if (!next || /^(#{1,6})\s+/.test(next) || /^[-*]\s+/.test(next) || /^\d+\.\s+/.test(next)) {
        break;
      }
      paragraphLines.push(lines[i].trimEnd());
      i += 1;
    }
    blocks.push(
      <p key={`p-${i}`} className="text-slate-100/95">
        {paragraphLines.map((pLine, idx) => (
          <Fragment key={`pl-${idx}`}>
            {renderInline(pLine)}
            {idx < paragraphLines.length - 1 && <br />}
          </Fragment>
        ))}
      </p>
    );
  }
  return blocks;
}

function PromptPane({
  label,
  value,
  onChange,
  rows = 10,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  rows?: number;
}) {
  return (
    <div>
      <div className="mb-2">
        <label className="text-sm text-slate-400">{label}</label>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={rows}
          className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-emerald-500"
        />
        <div className="rounded-lg border border-slate-600 bg-slate-900/50 p-3 text-sm leading-7 space-y-3 max-h-[360px] overflow-auto">
          {value.trim() ? renderMarkdown(value) : <p className="text-slate-500">Preview will appear here.</p>}
        </div>
      </div>
    </div>
  );
}

export default function Specialists() {
  const [specialists, setSpecialists] = useState<Specialist[]>([]);
  const [active, setActive] = useState('auto');
  const [protectedIds, setProtectedIds] = useState<string[]>(['auto', 'orchestrator']);
  const [promptMap, setPromptMap] = useState<Record<string, string>>({});
  const [systemPrompt, setSystemPrompt] = useState('');

  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');
  const [saving, setSaving] = useState(false);

  const [editorOpen, setEditorOpen] = useState(false);
  const [isCreate, setIsCreate] = useState(false);
  const [editingId, setEditingId] = useState<string>('orchestrator');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [color, setColor] = useState('#64748b');
  const [prompt, setPrompt] = useState('');

  const [systemOpen, setSystemOpen] = useState(false);
  const [specialistPromptOpen, setSpecialistPromptOpen] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [specData, promptData] = await Promise.all([
        apiClient.get<SpecialistsResponse>('/api/specialists'),
        apiClient.get<PromptsResponse>('/api/specialists/prompts'),
      ]);
      setSpecialists(specData.specialists);
      setActive(specData.active);
      setProtectedIds(specData.protected_ids);
      setPromptMap(promptData.specialist_prompts);
      setSystemPrompt(promptData.system_prompt);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const openCreate = () => {
    setIsCreate(true);
    setEditorOpen(true);
    setEditingId('');
    setName('');
    setDescription('');
    setColor('#64748b');
    setPrompt('');
  };

  const openEdit = (spec: Specialist) => {
    setIsCreate(false);
    setEditorOpen(true);
    setEditingId(spec.id);
    setName(spec.name);
    setDescription(spec.description);
    const resolved = colorValue(spec.color || 'slate');
    setColor(resolved.startsWith('#') ? resolved : '#64748b');
    setPrompt(promptMap[spec.id] ?? '');
  };

  const saveSpecialist = async () => {
    setSaving(true);
    setMessage('');
    try {
      if (isCreate) {
        await apiClient.post('/api/specialists', {
          id: editingId || name.toLowerCase().replace(/\s+/g, '_'),
          name,
          description,
          color,
          prompt,
        });
      } else {
        await apiClient.put(`/api/specialists/${editingId}`, {
          name,
          description,
          color,
          prompt,
        });
      }
      await fetchData();
      setEditorOpen(false);
      setMessage(isCreate ? 'Specialist added.' : 'Specialist updated.');
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to save specialist.');
    } finally {
      setSaving(false);
    }
  };

  const setActiveSpecialist = async (id: string) => {
    setSaving(true);
    setMessage('');
    try {
      await apiClient.put('/api/specialists', { active_specialist: id });
      setActive(id);
      setMessage('Active specialist updated.');
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to update active specialist.');
    } finally {
      setSaving(false);
    }
  };

  const removeSpecialist = async (id: string) => {
    setSaving(true);
    setMessage('');
    try {
      await apiClient.delete(`/api/specialists/${id}`);
      await fetchData();
      if (editingId === id) setEditorOpen(false);
      setMessage('Specialist removed.');
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to remove specialist.');
    } finally {
      setSaving(false);
    }
  };

  const restoreDefault = async (id: string) => {
    setSaving(true);
    setMessage('');
    try {
      await apiClient.post(`/api/specialists/${id}/restore`);
      await fetchData();
      setMessage('Default specialist restored.');
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to restore specialist.');
    } finally {
      setSaving(false);
    }
  };

  const saveSystemPrompt = async () => {
    setSaving(true);
    setMessage('');
    try {
      await apiClient.put('/api/specialists/prompts/system', { prompt: systemPrompt });
      setMessage('System prompt saved.');
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to save system prompt.');
    } finally {
      setSaving(false);
    }
  };

  const removedDefaults = useMemo(
    () => DEFAULT_SPECIALISTS.filter((d) => !specialists.some((s) => s.id === d.id)),
    [specialists]
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-3.5rem)]">
        <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-6">
      <div className="mb-2">
        <h1 className="text-2xl font-bold text-slate-100">Specialists</h1>
        <p className="text-slate-400 text-sm mt-1">
          Click any specialist card to view and modify it. `auto` and `orchestrator` are protected.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <button
          onClick={openCreate}
          className="text-left p-5 rounded-xl border-2 border-dashed border-slate-600 bg-slate-800/60 hover:border-emerald-500 hover:bg-emerald-900/10 transition-colors"
        >
          <div className="h-1 rounded-full bg-slate-600 mb-3" />
          <p className="text-slate-200 font-semibold text-sm">+ Add Specialist</p>
          <p className="text-slate-400 text-xs mt-2">Create a new specialist profile and custom prompt.</p>
        </button>

        {specialists.map((spec) => {
          const isActive = active === spec.id;
          const accent = colorValue(spec.color);
          return (
            <button
              key={spec.id}
              onClick={() => openEdit(spec)}
              className={`relative text-left p-5 rounded-xl border transition-all ${
                isActive
                  ? 'border-emerald-500 bg-emerald-900/20 ring-1 ring-emerald-500/50'
                  : 'border-slate-700 bg-slate-800 hover:border-slate-600'
              }`}
            >
              <div className="absolute top-0 left-0 right-0 h-1 rounded-t-xl" style={{ backgroundColor: accent }} />
              <div className="flex items-center gap-2 mt-1">
                <h3 className={`font-semibold text-sm ${isActive ? 'text-emerald-400' : 'text-slate-200'}`}>
                  {spec.name}
                </h3>
                {isActive && (
                  <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-emerald-900/50 text-emerald-400">
                    Active
                  </span>
                )}
                {spec.custom && (
                  <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-violet-900/50 text-violet-300">
                    Custom
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-400 mt-2 leading-relaxed">{spec.description}</p>
            </button>
          );
        })}
      </div>

      {removedDefaults.length > 0 && (
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
          <p className="text-sm text-slate-300 mb-2">Restore removed defaults:</p>
          <div className="flex flex-wrap gap-2">
            {removedDefaults.map((s) => (
              <button
                key={s.id}
                onClick={() => restoreDefault(s.id)}
                className="px-3 py-1.5 text-xs rounded-md bg-slate-700 text-slate-200 hover:bg-slate-600"
              >
                Restore {s.name}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
        <button
          onClick={() => setSystemOpen((v) => !v)}
          className="w-full px-4 py-3 text-left flex items-center justify-between bg-slate-800 hover:bg-slate-750"
        >
          <span className="text-sm font-medium text-slate-200">System Prompt Editor</span>
          <span className="text-slate-400 text-sm">{systemOpen ? 'Hide' : 'Show'}</span>
        </button>
        {systemOpen && (
          <div className="p-4 border-t border-slate-700 space-y-3">
            <PromptPane
              label="System Prompt"
              value={systemPrompt}
              onChange={setSystemPrompt}
              rows={14}
            />
            <button
              onClick={saveSystemPrompt}
              disabled={saving}
              className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg"
            >
              Save System Prompt
            </button>
          </div>
        )}
      </div>

      {editorOpen && (
        <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between">
            <h2 className="text-sm font-medium text-slate-200">
              {isCreate ? 'Add Specialist' : `Edit Specialist: ${name || editingId}`}
            </h2>
            <button onClick={() => setEditorOpen(false)} className="text-slate-400 hover:text-slate-200 text-sm">
              Close
            </button>
          </div>
          <div className="p-4 space-y-4">
            {isCreate && (
              <div>
                <label className="block text-sm text-slate-400 mb-1">ID</label>
                <input
                  value={editingId}
                  onChange={(e) => setEditingId(e.target.value)}
                  placeholder="e.g. hormone_coach"
                  className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100"
                />
              </div>
            )}
            <div>
              <label className="block text-sm text-slate-400 mb-1">Name</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100"
              />
            </div>
            <div>
              <label className="block text-sm text-slate-400 mb-1">Description</label>
              <input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100"
              />
            </div>
            <div>
              <label className="block text-sm text-slate-400 mb-1">Color</label>
              <div className="flex items-center gap-3">
                <input
                  type="color"
                  value={color}
                  onChange={(e) => setColor(e.target.value)}
                  className="h-10 w-14 rounded border border-slate-600 bg-transparent cursor-pointer"
                />
                <input
                  value={color}
                  onChange={(e) => setColor(e.target.value)}
                  placeholder="#10b981"
                  className="flex-1 bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100"
                />
                <span
                  className="inline-block w-6 h-6 rounded border border-slate-500"
                  style={{ backgroundColor: colorValue(color) }}
                />
              </div>
            </div>

            <div className="bg-slate-900/40 border border-slate-700 rounded-lg overflow-hidden">
              <button
                onClick={() => setSpecialistPromptOpen((v) => !v)}
                className="w-full px-3 py-2 text-left flex items-center justify-between hover:bg-slate-800"
              >
                <span className="text-sm text-slate-200">Specialist Prompt</span>
                <span className="text-xs text-slate-400">{specialistPromptOpen ? 'Hide' : 'Show'}</span>
              </button>
              {specialistPromptOpen && (
                <div className="p-3 border-t border-slate-700">
                  <PromptPane
                    label="Prompt Content"
                    value={prompt}
                    onChange={setPrompt}
                    rows={12}
                  />
                </div>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-3">
              {!isCreate && (
                <button
                  onClick={() => setActiveSpecialist(editingId)}
                  disabled={saving}
                  className="px-4 py-2 bg-sky-700 hover:bg-sky-600 disabled:opacity-50 text-white text-sm rounded-lg"
                >
                  Set As Active
                </button>
              )}
              <button
                onClick={saveSpecialist}
                disabled={saving || !name.trim() || (isCreate && !editingId.trim())}
                className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm rounded-lg"
              >
                {saving ? 'Saving...' : isCreate ? 'Create Specialist' : 'Save Changes'}
              </button>
              {!isCreate && !protectedIds.includes(editingId) && (
                <button
                  onClick={() => removeSpecialist(editingId)}
                  disabled={saving}
                  className="px-4 py-2 bg-rose-700 hover:bg-rose-600 disabled:opacity-50 text-white text-sm rounded-lg"
                >
                  Remove Specialist
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {message && (
        <p className={`text-sm ${message.includes('Failed') ? 'text-rose-400' : 'text-emerald-400'}`}>
          {message}
        </p>
      )}
    </div>
  );
}
