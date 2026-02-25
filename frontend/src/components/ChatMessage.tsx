import { Fragment, type ReactNode } from 'react';
import SpecialistBadge from './SpecialistBadge';

interface ChatMessageProps {
  message: {
    role: 'user' | 'assistant';
    content: string;
    specialist_used?: string;
    isStreaming?: boolean;
    created_at: string;
    image_preview_url?: string;
    has_image?: boolean;
  };
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

function formatTimestamp(isoString: string): string {
  try {
    // Legacy chat rows may store UTC timestamps without an offset.
    // Treat bare ISO values as UTC so desktop/mobile render consistently.
    const normalized = /(?:Z|[+-]\d{2}:\d{2})$/.test(isoString) ? isoString : `${isoString}Z`;
    const date = new Date(normalized);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

/** Strip internal metadata tags, tool call blocks, and action summaries from user-facing text. */
function stripMetaTags(text: string): string {
  let cleaned = text.replace(/\s*\[task_id=\d+\]/g, '');
  cleaned = cleaned.replace(/<tool_call>[\s\S]*?<\/tool_call>/g, '');
  // Strip "Actions taken:" blocks (backend-appended or AI-generated)
  cleaned = cleaned.replace(/\n*\*{0,2}Actions taken:?\*{0,2}\n```[\s\S]*?```/g, '');
  cleaned = cleaned.replace(/\n*\*{0,2}Actions taken:?\*{0,2}\n\s*-[^\n]*/g, '');
  cleaned = cleaned.replace(/\n{3,}/g, '\n\n');
  return cleaned.trim();
}

export default function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === 'user';
  const displayContent = stripMetaTags(message.content);

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div
        className={`max-w-[85%] sm:max-w-[75%] rounded-2xl px-4 py-3 ${
          isUser
            ? 'bg-emerald-700 text-white rounded-br-md'
            : 'bg-slate-700 text-slate-100 rounded-bl-md'
        }`}
      >
        {/* Specialist badge */}
        {!isUser && message.specialist_used && (
          <div className="mb-2">
            <SpecialistBadge specialist={message.specialist_used} />
          </div>
        )}

        {/* Message content */}
        {message.image_preview_url && (
          <img
            src={message.image_preview_url}
            alt="Uploaded"
            className="mb-2 max-h-56 w-auto rounded-lg border border-slate-500/50"
          />
        )}
        {!message.image_preview_url && message.has_image && (
          <div className="mb-2 inline-flex items-center rounded-md border border-slate-500/60 bg-slate-800/70 px-2 py-1 text-xs text-slate-200">
            Image attached
          </div>
        )}
        {!!displayContent && (
          <div className="text-sm leading-7 break-words space-y-3">{renderContent(displayContent)}</div>
        )}

        {/* Streaming cursor */}
        {message.isStreaming && (
          <span className="inline-block w-2 h-4 ml-0.5 bg-slate-300 animate-pulse rounded-sm align-text-bottom" />
        )}

        {/* Timestamp */}
        <div
          className={`text-[10px] mt-1.5 ${
            isUser ? 'text-emerald-300/60' : 'text-slate-400/60'
          }`}
        >
          {formatTimestamp(message.created_at)}
        </div>
      </div>
    </div>
  );
}
