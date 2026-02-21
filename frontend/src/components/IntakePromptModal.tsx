import { useState } from 'react';
import { apiClient } from '../api/client';

interface IntakeState {
  session_id: number;
  status: string;
  progress_completed: number;
  progress_total: number;
  current_field_id: string | null;
  current_question: string | null;
  current_help_text: string | null;
  current_options: string[];
  ready_to_finish: boolean;
}

interface IntakePromptModalProps {
  onDismiss: () => void;
  onCompleted: () => void;
}

export default function IntakePromptModal({ onDismiss, onCompleted }: IntakePromptModalProps) {
  const [mode, setMode] = useState<'prompt' | 'flow'>('prompt');
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [answer, setAnswer] = useState('');
  const [state, setState] = useState<IntakeState | null>(null);

  const startIntake = async () => {
    setLoading(true);
    setError('');
    try {
      const next = await apiClient.post<IntakeState>('/api/intake/start', { restart: false });
      setState(next);
      setMode('flow');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to start intake.');
    } finally {
      setLoading(false);
    }
  };

  const submitAnswer = async () => {
    if (!answer.trim() || !state) return;
    setSubmitting(true);
    setError('');
    try {
      const next = await apiClient.post<IntakeState & { status: string; error?: string }>('/api/intake/answer', {
        answer: answer.trim(),
      });
      if (next.status === 'validation_error' && next.error) {
        setError(next.error);
      } else {
        setError('');
      }
      setState(next);
      setAnswer('');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to submit answer.');
    } finally {
      setSubmitting(false);
    }
  };

  const skipCurrent = async () => {
    if (!state) return;
    setSubmitting(true);
    setError('');
    try {
      const next = await apiClient.post<IntakeState & { status: string }>('/api/intake/skip', { skip_all: false });
      setState(next);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to skip this question.');
    } finally {
      setSubmitting(false);
    }
  };

  const skipAll = async () => {
    setSubmitting(true);
    setError('');
    try {
      await apiClient.post('/api/intake/skip', { skip_all: true });
      onDismiss();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to skip intake.');
    } finally {
      setSubmitting(false);
    }
  };

  const finish = async () => {
    setSubmitting(true);
    setError('');
    try {
      await apiClient.post('/api/intake/finish', {});
      onCompleted();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to finish intake.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/70 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="w-full max-w-xl bg-slate-800 border border-slate-700 rounded-xl p-5 shadow-2xl">
        {mode === 'prompt' && (
          <div className="space-y-4">
            <h2 className="text-xl font-semibold text-slate-100">Start Your Intake</h2>
            <p className="text-sm text-slate-300">
              Your API key and models are set. Start the intake now so your profile is complete and coaching can adapt correctly.
            </p>
            {error && <p className="text-sm text-rose-400">{error}</p>}
            <div className="flex flex-wrap gap-2 justify-end">
              <button
                onClick={onDismiss}
                className="px-3 py-2 text-sm text-slate-300 border border-slate-600 rounded-lg hover:bg-slate-700"
              >
                Later
              </button>
              <button
                onClick={startIntake}
                disabled={loading}
                className="px-3 py-2 text-sm text-white bg-emerald-600 hover:bg-emerald-500 rounded-lg disabled:opacity-60"
              >
                {loading ? 'Starting...' : 'Start Intake'}
              </button>
            </div>
          </div>
        )}

        {mode === 'flow' && state && (
          <div className="space-y-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-xl font-semibold text-slate-100">Intake Session</h2>
                <p className="text-xs text-slate-400 mt-1">
                  Step {Math.min(state.progress_completed + 1, state.progress_total)} of {state.progress_total}
                </p>
              </div>
              <button
                onClick={onDismiss}
                className="px-2 py-1 text-xs text-slate-300 border border-slate-600 rounded hover:bg-slate-700"
              >
                Close
              </button>
            </div>

            {!state.ready_to_finish ? (
              <>
                <div>
                  <p className="text-sm text-slate-100">{state.current_question}</p>
                  {state.current_help_text && <p className="text-xs text-slate-400 mt-1">{state.current_help_text}</p>}
                  {state.current_options?.length > 0 && (
                    <p className="text-xs text-slate-500 mt-1">Options: {state.current_options.join(', ')}</p>
                  )}
                </div>
                <textarea
                  rows={3}
                  value={answer}
                  onChange={(e) => setAnswer(e.target.value)}
                  placeholder="Type your answer..."
                  className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500"
                />
              </>
            ) : (
              <p className="text-sm text-slate-200">All steps are complete. Apply your profile updates now.</p>
            )}

            {error && <p className="text-sm text-rose-400">{error}</p>}

            <div className="flex flex-wrap gap-2 justify-end">
              {!state.ready_to_finish && (
                <>
                  <button
                    onClick={skipCurrent}
                    disabled={submitting}
                    className="px-3 py-2 text-sm text-slate-300 border border-slate-600 rounded-lg hover:bg-slate-700 disabled:opacity-60"
                  >
                    Skip This
                  </button>
                  <button
                    onClick={submitAnswer}
                    disabled={submitting || !answer.trim()}
                    className="px-3 py-2 text-sm text-white bg-emerald-600 hover:bg-emerald-500 rounded-lg disabled:opacity-60"
                  >
                    {submitting ? 'Saving...' : 'Submit'}
                  </button>
                </>
              )}
              {state.ready_to_finish && (
                <button
                  onClick={finish}
                  disabled={submitting}
                  className="px-3 py-2 text-sm text-white bg-emerald-600 hover:bg-emerald-500 rounded-lg disabled:opacity-60"
                >
                  {submitting ? 'Finishing...' : 'Finish Intake'}
                </button>
              )}
              <button
                onClick={skipAll}
                disabled={submitting}
                className="px-3 py-2 text-sm text-rose-300 border border-rose-700/60 rounded-lg hover:bg-rose-900/20 disabled:opacity-60"
              >
                Skip Intake
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
