import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useChat, type ChatVerbosity } from '../hooks/useChat';
import ChatMessage from '../components/ChatMessage';
import ChatInput from '../components/ChatInput';
import { apiClient } from '../api/client';
import { APP_NAME } from '../constants/branding';

const PENDING_IMAGE_KEY = 'chat_pending_image_data_url';
const PENDING_IMAGE_NAME_KEY = 'chat_pending_image_name';
const PENDING_IMAGE_TYPE_KEY = 'chat_pending_image_type';

interface UpcomingTask {
  id: number;
  title: string;
  description: string | null;
  status: 'pending' | 'completed' | 'missed' | 'skipped';
  progress_pct: number;
  framework_name?: string | null;
}

interface PlanSnapshotLite {
  upcoming_tasks: UpcomingTask[];
  notifications: Array<{
    id: number;
    title: string;
    message: string;
    is_read: boolean;
  }>;
  preferences: {
    visibility_mode: 'top3' | 'all';
    max_visible_tasks: number;
  };
}

interface ChatNavigationState {
  chatFill?: string;
  autoSend?: boolean;
  goalSettingMode?: boolean;
  chatFillNonce?: string | number;
}

function dataUrlToFile(dataUrl: string, name: string, type: string): File | null {
  try {
    const parts = dataUrl.split(',');
    if (parts.length < 2) return null;
    const b64 = parts[1];
    const bin = atob(b64);
    const len = bin.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) bytes[i] = bin.charCodeAt(i);
    return new File([bytes], name || `image-${Date.now()}.jpg`, { type: type || 'image/jpeg' });
  } catch {
    return null;
  }
}

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error('Failed to read file'));
    reader.readAsDataURL(file);
  });
}

function GoalPanel({
  tasks,
  notifications,
  onUpdate,
}: {
  tasks: UpcomingTask[];
  notifications: PlanSnapshotLite['notifications'];
  onUpdate: (task: UpcomingTask) => void;
}) {
  const completed = tasks.filter((t) => t.status === 'completed').length;
  const total = tasks.length;

  return (
    <div className="h-full rounded-xl border border-slate-700 bg-slate-800/70 p-3 sm:p-4 space-y-3 overflow-y-auto">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-slate-100">Today's Goals</h3>
          <p className="text-xs text-slate-400 mt-0.5">Tell the coach what you did to log progress.</p>
        </div>
        {total > 0 && (
          <span className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${
            completed === total ? 'bg-emerald-900/60 text-emerald-300' : 'bg-slate-700 text-slate-300'
          }`}>
            {completed}/{total}
          </span>
        )}
      </div>

      {tasks.length === 0 ? (
        <p className="text-xs text-slate-400">No pending goals right now.</p>
      ) : (
        <div className="space-y-2">
          {tasks.map((task) => (
            <div key={task.id} className={`rounded-lg border p-2.5 ${
              task.status === 'completed'
                ? 'border-emerald-800/40 bg-emerald-950/20'
                : 'border-slate-700 bg-slate-900/40'
            }`}>
              <div className="flex items-start justify-between gap-1">
                <p className={`text-sm font-medium flex-1 ${task.status === 'completed' ? 'line-through text-slate-400' : 'text-slate-100'}`}>
                  {task.title}
                </p>
                {task.status === 'completed' && (
                  <span className="text-emerald-400 text-xs shrink-0">✓</span>
                )}
              </div>
              {task.description && <p className="text-xs text-slate-400 mt-0.5">{task.description}</p>}
              {task.framework_name && <p className="text-[11px] text-cyan-300 mt-0.5">{task.framework_name}</p>}
              <div className="mt-2">
                <div className="flex items-center justify-between text-[11px] text-slate-400 mb-1">
                  <span>{Math.round(task.progress_pct)}%</span>
                  <span className="capitalize">{task.status}</span>
                </div>
                <div className="h-1.5 rounded-full bg-slate-700 overflow-hidden">
                  <div
                    className={`h-full ${task.status === 'completed' ? 'bg-emerald-500' : 'bg-sky-500'}`}
                    style={{ width: `${Math.min(task.progress_pct, 100)}%` }}
                  />
                </div>
              </div>
              {task.status !== 'completed' && (
                <button
                  type="button"
                  onClick={() => onUpdate(task)}
                  className="mt-2 px-2.5 py-1 text-xs rounded-md border border-slate-600 bg-slate-800 hover:bg-slate-700 text-slate-200 transition-colors"
                >
                  Update with Coach
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="pt-1">
        <h4 className="text-xs font-semibold text-slate-300 mb-1">Missed Goal Prompts</h4>
        {notifications.filter((n) => !n.is_read).length === 0 ? (
          <p className="text-[11px] text-slate-500">No active prompts.</p>
        ) : (
          <div className="space-y-1.5">
            {notifications
              .filter((n) => !n.is_read)
              .slice(0, 3)
              .map((n) => (
                <div key={n.id} className="rounded-md border border-slate-700 bg-slate-900/40 px-2 py-1.5">
                  <p className="text-[11px] font-medium text-slate-200">{n.title}</p>
                  <p className="text-[11px] text-slate-400 mt-0.5">{n.message}</p>
                </div>
              ))}
          </div>
        )}
      </div>
    </div>
  );
}

const QUICK_PROMPTS = [
  { label: 'What should I focus on now?', text: 'What should I focus on right now based on my plan?' },
  { label: 'Log a meal', text: 'I want to log a meal.' },
  { label: 'Log exercise', text: 'I want to log my workout.' },
  { label: 'Log water', text: 'I drank some water. Log it for me.' },
  { label: 'Check my progress', text: "How am I doing today?" },
];

export default function Chat() {
  const navigate = useNavigate();
  const location = useLocation();
  const { messages, loading, error, sendMessage, loadHistory } = useChat();
  const [selectedImage, setSelectedImage] = useState<File | null>(null);
  const [verbosity, setVerbosity] = useState<ChatVerbosity>('normal');
  const [planSnapshot, setPlanSnapshot] = useState<PlanSnapshotLite | null>(null);
  const [mobileGoalsOpen, setMobileGoalsOpen] = useState(false);
  const [chatFill, setChatFill] = useState<string | null>(null);
  const [autoSendPending, setAutoSendPending] = useState(false);
  const [goalSettingMode, setGoalSettingMode] = useState(false);
  const [historyReady, setHistoryReady] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const hasLoadedRef = useRef(false);
  const consumedFillKeyRef = useRef<string | number | null>(null);
  const verbosityOptions: Array<{ key: ChatVerbosity; label: string; hover: string }> = [
    { key: 'normal', label: 'Normal', hover: 'Balanced detail' },
    { key: 'summarized', label: 'Summarized', hover: 'Key points and actions' },
    { key: 'straight', label: 'Straight', hover: 'Direct and brief' },
  ];

  const fetchPlanSnapshot = useCallback(async () => {
    try {
      const snapshot = await apiClient.get<PlanSnapshotLite>('/api/plan/snapshot?cycle_type=daily');
      setPlanSnapshot(snapshot);
    } catch {
      // Keep chat functional if plan API fails.
    }
  }, []);

  const handleUpdate = (task: UpcomingTask) => {
    const desc = task.description ? ` (${task.description})` : '';
    setChatFill(`Goal check-in: ${task.title}${desc}`);
    setMobileGoalsOpen(false);
  };

  // Load history on mount
  useEffect(() => {
    if (!hasLoadedRef.current) {
      hasLoadedRef.current = true;
      let active = true;
      void (async () => {
        try {
          await Promise.all([loadHistory(), fetchPlanSnapshot()]);
        } finally {
          if (active) setHistoryReady(true);
        }
      })();
      return () => {
        active = false;
      };
    }
  }, [fetchPlanSnapshot, loadHistory]);

  useEffect(() => {
    const navState = (location.state as ChatNavigationState | null) ?? null;
    if (!navState?.chatFill) return;

    const fillKey = navState.chatFillNonce ?? location.key;
    if (consumedFillKeyRef.current === fillKey) return;
    consumedFillKeyRef.current = fillKey;

    setChatFill(navState.chatFill);
    setGoalSettingMode(Boolean(navState.goalSettingMode));
    setAutoSendPending(Boolean(navState.autoSend));

    navigate(`${location.pathname}${location.search}`, { replace: true, state: null });
  }, [location.key, location.pathname, location.search, location.state, navigate]);

  useEffect(() => {
    if (!historyReady || !autoSendPending || !chatFill) return;
    if (messages.some((m) => m.isStreaming)) return;

    const kickoff = chatFill.trim();
    if (!kickoff) {
      setAutoSendPending(false);
      return;
    }

    sendMessage(kickoff, undefined, verbosity);
    setChatFill(null);
    setAutoSendPending(false);
  }, [autoSendPending, chatFill, historyReady, messages, sendMessage, verbosity]);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'auto' });
  }, [messages]);

  useEffect(() => {
    if (selectedImage) return;
    const dataUrl = sessionStorage.getItem(PENDING_IMAGE_KEY);
    if (!dataUrl) return;
    const name = sessionStorage.getItem(PENDING_IMAGE_NAME_KEY) || `image-${Date.now()}.jpg`;
    const type = sessionStorage.getItem(PENDING_IMAGE_TYPE_KEY) || 'image/jpeg';
    const restored = dataUrlToFile(dataUrl, name, type);
    if (restored) {
      setSelectedImage(restored);
    }
  }, [selectedImage]);

  useEffect(() => {
    const streaming = messages.some((m) => m.isStreaming);
    if (!streaming) {
      void fetchPlanSnapshot();
    }
  }, [messages, fetchPlanSnapshot]);

  const handleSelectedImageChange = (file: File | null) => {
    if (!file) {
      setSelectedImage(null);
      sessionStorage.removeItem(PENDING_IMAGE_KEY);
      sessionStorage.removeItem(PENDING_IMAGE_NAME_KEY);
      sessionStorage.removeItem(PENDING_IMAGE_TYPE_KEY);
      return;
    }

    setSelectedImage(file);
    void fileToDataUrl(file)
      .then((dataUrl) => {
        sessionStorage.setItem(PENDING_IMAGE_KEY, dataUrl);
        sessionStorage.setItem(PENDING_IMAGE_NAME_KEY, file.name || 'image.jpg');
        sessionStorage.setItem(PENDING_IMAGE_TYPE_KEY, file.type || 'image/jpeg');
      })
      .catch(() => {
        // Keep in-memory image even if persistence fails.
      });
  };

  const handleSend = (text: string, imageFile?: File) => {
    sendMessage(text, imageFile, verbosity);
    setSelectedImage(null);
    sessionStorage.removeItem(PENDING_IMAGE_KEY);
    sessionStorage.removeItem(PENDING_IMAGE_NAME_KEY);
    sessionStorage.removeItem(PENDING_IMAGE_TYPE_KEY);
  };

  const isStreaming = messages.some((m) => m.isStreaming);
  const unreadPrompts = (planSnapshot?.notifications || []).filter((n) => !n.is_read).length;

  return (
    <div className="relative flex flex-col h-[calc(100vh-3.5rem)] overflow-hidden supports-[height:100dvh]:h-[calc(100dvh-3.5rem)]">
      <div className="px-4 py-2 border-b border-slate-700/70 bg-slate-900/50">
        <div className="max-w-7xl mx-auto flex items-center justify-center gap-2">
          <div className="inline-flex rounded-lg border border-slate-700 bg-slate-800/70 p-0.5">
            {verbosityOptions.map((option) => (
              <button
                key={option.key}
                type="button"
                onClick={() => setVerbosity(option.key)}
                title={option.hover}
                aria-label={`${option.label}: ${option.hover}`}
                className={[
                  'px-2.5 py-1 text-xs rounded-md transition-colors',
                  verbosity === option.key
                    ? 'bg-emerald-600 text-white'
                    : 'text-slate-300 hover:bg-slate-700/70 hover:text-slate-100',
                ].join(' ')}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {goalSettingMode && (
        <div className="px-4 py-2 border-b border-emerald-700/40 bg-emerald-900/10">
          <div className="max-w-7xl mx-auto flex items-center justify-between gap-2">
            <p className="text-xs text-emerald-300">
              Goal-setting session active. The coach will guide targets, dates, and priorities.
            </p>
            <button
              type="button"
              onClick={() => setGoalSettingMode(false)}
              className="px-2 py-0.5 text-[11px] rounded border border-emerald-700/40 text-emerald-300 hover:bg-emerald-900/20"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      <div className="flex-1 min-h-0">
        <div className="h-full max-w-7xl mx-auto px-4 py-4 grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-4">
          {/* Messages area */}
          <div className="min-h-0 overflow-y-auto pb-20 sm:pb-24">
            {messages.length === 0 && !loading ? (
              <div className="flex flex-col items-center justify-center h-full gap-6 max-w-lg mx-auto px-2">
                <div className="text-center">
                  <div className="w-14 h-14 mx-auto mb-3 rounded-full bg-emerald-500/10 flex items-center justify-center">
                    <svg className="w-7 h-7 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z" />
                    </svg>
                  </div>
                  <h2 className="text-lg font-semibold text-slate-100 mb-1">{APP_NAME}</h2>
                  <p className="text-slate-400 text-sm">Your active coach is ready. What are we doing right now?</p>
                </div>

                {/* Top pending task highlight */}
                {planSnapshot && planSnapshot.upcoming_tasks.filter(t => t.status !== 'completed').length > 0 && (
                  <div className="w-full rounded-xl border border-emerald-800/40 bg-emerald-950/20 p-3.5">
                    <p className="text-xs text-emerald-400 font-medium mb-1">Top priority right now</p>
                    <p className="text-[11px] text-slate-400 mb-2">Tap a goal to check in with your coach.</p>
                    {planSnapshot.upcoming_tasks
                      .filter(t => t.status !== 'completed')
                      .slice(0, 2)
                      .map(task => (
                        <button
                          key={task.id}
                          type="button"
                          onClick={() => handleUpdate(task)}
                          className="w-full text-left rounded-lg border border-slate-700 bg-slate-900/60 hover:bg-slate-800 px-3 py-2 mb-1.5 last:mb-0 transition-colors group"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <p className="text-sm text-slate-100 font-medium">{task.title}</p>
                            <span className="text-[11px] text-slate-400 group-hover:text-emerald-400 shrink-0 transition-colors">Check in →</span>
                          </div>
                          {task.description && <p className="text-xs text-slate-400 mt-0.5">{task.description}</p>}
                          {task.framework_name && <p className="text-[11px] text-cyan-300 mt-0.5">{task.framework_name}</p>}
                        </button>
                      ))}
                  </div>
                )}

                {/* Quick prompt chips */}
                <div className="w-full">
                  <p className="text-xs text-slate-500 mb-2 text-center">Quick starts</p>
                  <div className="flex flex-wrap gap-2 justify-center">
                    {QUICK_PROMPTS.map((p) => (
                      <button
                        key={p.label}
                        type="button"
                        onClick={() => setChatFill(p.text)}
                        className="px-3 py-1.5 text-xs rounded-full border border-slate-600 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-slate-100 transition-colors"
                      >
                        {p.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="max-w-3xl mx-auto">
                {messages.map((message) => (
                  <ChatMessage key={message.id} message={message} />
                ))}
                <div ref={messagesEndRef} />
              </div>
            )}
          </div>

          {/* Desktop goals panel */}
          <div className="hidden lg:block min-h-0">
            <GoalPanel
              tasks={planSnapshot?.upcoming_tasks || []}
              notifications={planSnapshot?.notifications || []}
              onUpdate={handleUpdate}
            />
          </div>
        </div>
      </div>

      {/* Mobile goals modal */}
      {mobileGoalsOpen && (
        <div className="lg:hidden fixed inset-0 z-40 bg-slate-950/70 px-3 pt-20 pb-4">
          <div className="h-full rounded-xl border border-slate-700 bg-slate-900/95 shadow-2xl overflow-hidden">
            <div className="flex items-center justify-end px-3 pt-3">
              <button
                type="button"
                onClick={() => setMobileGoalsOpen(false)}
                className="px-2.5 py-1 text-xs rounded-md border border-slate-600 bg-slate-800 text-slate-200 hover:bg-slate-700"
              >
                Close
              </button>
            </div>
            <div className="h-[calc(100%-2.5rem)] px-3 pb-3">
              <GoalPanel
                tasks={planSnapshot?.upcoming_tasks || []}
                notifications={planSnapshot?.notifications || []}
                onUpdate={handleUpdate}
              />
            </div>
          </div>
        </div>
      )}

      {/* Mobile goal drawer */}
      <div className="lg:hidden px-4 pb-2">
        <button
          type="button"
          onClick={() => setMobileGoalsOpen((v) => !v)}
          className="w-full flex items-center justify-between rounded-lg border border-slate-700 bg-slate-800/80 px-3 py-2 text-sm text-slate-200"
        >
          <span>Upcoming Goals</span>
          <span className="text-xs text-slate-400">
            {planSnapshot?.upcoming_tasks.length || 0} tasks
            {unreadPrompts > 0 ? ` | ${unreadPrompts} prompts` : ''}
          </span>
        </button>
      </div>

      {/* Error banner */}
      {error && (
        <div className="px-4 py-2 bg-red-500/10 border-t border-red-500/20 text-red-400 text-sm text-center">
          {error}
        </div>
      )}

      {/* Input bar */}
      <ChatInput
        onSend={handleSend}
        selectedImage={selectedImage}
        onSelectedImageChange={handleSelectedImageChange}
        disabled={isStreaming}
        fillText={autoSendPending ? null : chatFill}
        onFillConsumed={() => setChatFill(null)}
      />
    </div>
  );
}
