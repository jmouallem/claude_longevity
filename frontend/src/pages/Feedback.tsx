import { useCallback, useEffect, useState } from 'react';
import { apiClient } from '../api/client';

type FeedbackType = 'bug' | 'enhancement' | 'missing' | 'other';

interface FeedbackEntry {
  id: number;
  feedback_type: FeedbackType;
  title: string;
  details?: string | null;
  source: 'user' | 'agent' | string;
  specialist_id?: string | null;
  specialist_name?: string | null;
  created_by_user_id?: number | null;
  created_by_username?: string | null;
  created_at: string;
}

const TYPE_OPTIONS: FeedbackType[] = ['bug', 'enhancement', 'missing', 'other'];

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function Feedback() {
  const [entries, setEntries] = useState<FeedbackEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');

  const [feedbackType, setFeedbackType] = useState<FeedbackType>('enhancement');
  const [title, setTitle] = useState('');
  const [details, setDetails] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await apiClient.get<FeedbackEntry[]>('/api/feedback');
      setEntries(rows);
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to load feedback');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const submit = async () => {
    const t = title.trim();
    if (!t) return;
    setMessage('');
    try {
      await apiClient.post('/api/feedback', {
        feedback_type: feedbackType,
        title: t,
        details: details.trim() || null,
      });
      setTitle('');
      setDetails('');
      await load();
      setMessage('Feedback submitted.');
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to submit feedback');
    }
  };

  const removeOne = async (id: number) => {
    setMessage('');
    try {
      await apiClient.delete(`/api/feedback/${id}`);
      setEntries((prev) => prev.filter((r) => r.id !== id));
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : 'Failed to delete feedback entry');
    }
  };

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">My Feedback</h1>
        <p className="text-sm text-slate-400">Your submitted product feedback entries.</p>
      </div>

      <div className="bg-slate-800 rounded-xl border border-slate-700 p-4 space-y-3">
        <h2 className="text-lg font-semibold text-slate-100">Add Feedback</h2>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <div>
            <label className="block text-xs text-slate-400 mb-1">Type</label>
            <select
              value={feedbackType}
              onChange={(e) => setFeedbackType(e.target.value as FeedbackType)}
              className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm"
            >
              {TYPE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div className="md:col-span-3">
            <label className="block text-xs text-slate-400 mb-1">Title</label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Short summary"
              className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm"
            />
          </div>
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">Details</label>
          <textarea
            value={details}
            onChange={(e) => setDetails(e.target.value)}
            placeholder="Describe impact, context, and expected behavior"
            rows={3}
            className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 text-sm resize-y"
          />
        </div>
        <button
          onClick={submit}
          className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium rounded-lg"
        >
          Add Feedback
        </button>
      </div>

      {message && <p className="text-sm text-emerald-300">{message}</p>}

      <div className="bg-slate-800 rounded-xl border border-slate-700">
        <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-100">My Entries</h2>
          <span className="text-xs text-slate-400">{entries.length} entries</span>
        </div>
        <div className="divide-y divide-slate-700">
          {loading ? (
            <div className="px-4 py-6 text-sm text-slate-400">Loading...</div>
          ) : entries.length === 0 ? (
            <div className="px-4 py-6 text-sm text-slate-400">No feedback yet.</div>
          ) : (
            entries.map((item) => (
              <div key={item.id} className="px-4 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-[11px] uppercase tracking-wide px-2 py-0.5 rounded-full bg-slate-700 text-slate-300 border border-slate-600">
                        {item.feedback_type}
                      </span>
                    </div>
                    <p className="text-slate-100 font-medium">{item.title}</p>
                    {item.details && <p className="text-sm text-slate-300 mt-1 whitespace-pre-wrap">{item.details}</p>}
                    <p className="text-[11px] text-slate-500 mt-2">{formatTime(item.created_at)}</p>
                  </div>
                  <button
                    onClick={() => removeOne(item.id)}
                    className="text-sm text-slate-400 hover:text-rose-300"
                    title="Delete entry"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
