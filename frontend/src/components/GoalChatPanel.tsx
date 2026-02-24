import { Fragment, type ReactNode, useCallback, useEffect, useRef, useState } from 'react';
import { useChat } from '../hooks/useChat';
import type { ChatMessage } from '../hooks/useChat';

interface GoalChatPanelProps {
  open: boolean;
  onClose: () => void;
  taskTitle: string;
  taskDescription?: string;
  initialMessage?: string;
  onTaskUpdated?: () => void;
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
        <code
          key={`${match.index}-c`}
          className="px-1.5 py-0.5 rounded bg-slate-900/50 text-sky-200 text-[0.92em]"
        >
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

function renderContent(content: string): ReactNode[] {
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
      const headingText = headingMatch[2];
      const headingClass = level <= 2
        ? 'text-base font-semibold text-slate-50'
        : 'text-sm font-semibold text-slate-100';
      blocks.push(
        <p key={`h-${i}`} className={headingClass}>
          {renderInline(headingText)}
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
          {items.map((item, idx) => (
            <li key={`uli-${idx}`}>{renderInline(item)}</li>
          ))}
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
          {items.map((item, idx) => (
            <li key={`oli-${idx}`}>{renderInline(item)}</li>
          ))}
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

/** Strip internal metadata tags (e.g. [task_id=123]) from user-facing text. */
function stripMetaTags(text: string): string {
  return text.replace(/\s*\[task_id=\d+\]/g, '');
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user';
  const displayContent = isUser ? stripMetaTags(message.content) : message.content;
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm ${
          isUser
            ? 'bg-emerald-600 text-white rounded-br-sm'
            : 'bg-slate-700 text-slate-100 rounded-bl-sm'
        }`}
      >
        <div className="leading-relaxed break-words space-y-2">
          {renderContent(displayContent)}
          {message.isStreaming && (
            <span className="inline-block w-1.5 h-3.5 ml-0.5 bg-current animate-pulse rounded-sm" />
          )}
        </div>
      </div>
    </div>
  );
}

export default function GoalChatPanel({
  open,
  onClose,
  taskTitle,
  taskDescription,
  initialMessage,
  onTaskUpdated,
}: GoalChatPanelProps) {
  const { messages, loading, loadHistory, sendMessage } = useChat();
  const [inputText, setInputText] = useState('');
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const lastAutoSentPromptRef = useRef('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Load history on first open
  useEffect(() => {
    if (open && !historyLoaded) {
      loadHistory().then(() => setHistoryLoaded(true));
    }
  }, [open, historyLoaded, loadHistory]);

  // Pre-fill and auto-send the initial check-in message for each task.
  useEffect(() => {
    const prompt = String(initialMessage || '').trim();
    if (!open || !historyLoaded || !prompt) return;
    if (lastAutoSentPromptRef.current === prompt) return;
    lastAutoSentPromptRef.current = prompt;
    sendMessage(prompt);
  }, [open, historyLoaded, initialMessage, sendMessage]);

  // Reset auto-send state when panel is closed (so reopening same task sends again).
  useEffect(() => {
    if (!open) {
      lastAutoSentPromptRef.current = '';
      setHistoryLoaded(false);
    }
  }, [open]);

  // Scroll to bottom when messages or loading state changes.
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  // Fire onTaskUpdated after assistant stops streaming
  const prevLoadingRef = useRef(loading);
  useEffect(() => {
    if (prevLoadingRef.current && !loading && historyLoaded) {
      onTaskUpdated?.();
    }
    prevLoadingRef.current = loading;
  }, [loading, historyLoaded, onTaskUpdated]);

  const handleSend = useCallback(() => {
    const text = inputText.trim();
    if (!text || loading) return;
    setInputText('');
    sendMessage(text);
  }, [inputText, loading, sendMessage]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  if (!open) return null;

  // Only show messages from after the panel opened (or show all — using all for coaching continuity)
  const visibleMessages = messages.filter((m) => m.isStreaming || m.content.trim() !== '');

  return (
    <>
      {/* Backdrop (mobile tap to close) */}
      <div
        className="fixed inset-0 z-40 bg-slate-950/50 lg:hidden"
        onClick={onClose}
      />

      {/* Panel — bottom sheet on mobile, right drawer on desktop */}
      <div
        className={`
          fixed z-50 bg-slate-900 border-slate-700 shadow-2xl flex flex-col
          bottom-0 left-0 right-0 h-[70vh] rounded-t-2xl border-t border-x
          lg:bottom-0 lg:top-0 lg:left-auto lg:right-0 lg:w-[400px] lg:h-full lg:rounded-none lg:border-t-0 lg:border-l lg:border-x-0
          transition-transform duration-300
        `}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 px-4 py-3 border-b border-slate-700 flex-shrink-0">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-wider text-emerald-400 mb-0.5">
              Goal Check-in
            </p>
            <p className="text-sm font-medium text-slate-100 leading-snug line-clamp-2">
              {taskTitle}
            </p>
            {taskDescription && (
              <p className="text-xs text-slate-500 mt-0.5 line-clamp-1">{taskDescription}</p>
            )}
          </div>
          <button
            onClick={onClose}
            className="flex-shrink-0 p-1.5 text-slate-400 hover:text-white hover:bg-slate-700 rounded-lg transition-colors"
            aria-label="Close"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
          {visibleMessages.length === 0 && !loading && (
            <p className="text-center text-slate-500 text-sm pt-4">
              Starting check-in...
            </p>
          )}
          {visibleMessages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="flex-shrink-0 border-t border-slate-700 px-3 py-2.5">
          <div className="flex items-end gap-2">
            <textarea
              ref={inputRef}
              rows={1}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Reply to your coach..."
              disabled={loading}
              className="flex-1 bg-slate-800 border border-slate-600 rounded-xl px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500 resize-none disabled:opacity-50"
              style={{ maxHeight: '100px' }}
              onInput={(e) => {
                const el = e.currentTarget;
                el.style.height = 'auto';
                el.style.height = `${Math.min(el.scrollHeight, 100)}px`;
              }}
            />
            <button
              onClick={handleSend}
              disabled={loading || !inputText.trim()}
              className="flex-shrink-0 p-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white rounded-xl transition-colors"
              aria-label="Send"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            </button>
          </div>
          <p className="text-xs text-slate-600 mt-1.5 text-center">
            Full chat available in{' '}
            <button
              onClick={onClose}
              className="text-emerald-600 hover:text-emerald-400 underline"
            >
              Chat →
            </button>
          </p>
        </div>
      </div>
    </>
  );
}
