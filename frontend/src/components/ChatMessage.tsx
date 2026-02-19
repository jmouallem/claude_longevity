import SpecialistBadge from './SpecialistBadge';

interface ChatMessageProps {
  message: {
    role: 'user' | 'assistant';
    content: string;
    specialist_used?: string;
    isStreaming?: boolean;
    created_at: string;
  };
}

function formatContent(content: string): string {
  let html = content
    // Escape HTML entities
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // Bold: **text**
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

  // Italic: *text*
  html = html.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '<em>$1</em>');

  // Bullet points: lines starting with "- " or "* "
  html = html.replace(/^[\-\*]\s+(.+)$/gm, '<li class="ml-4 list-disc">$1</li>');

  // Numbered lists: lines starting with "1. ", "2. ", etc.
  html = html.replace(/^\d+\.\s+(.+)$/gm, '<li class="ml-4 list-decimal">$1</li>');

  // Line breaks
  html = html.replace(/\n/g, '<br/>');

  return html;
}

function formatTimestamp(isoString: string): string {
  try {
    const date = new Date(isoString);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

export default function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === 'user';

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
        <div
          className="text-sm leading-relaxed break-words"
          dangerouslySetInnerHTML={{ __html: formatContent(message.content) }}
        />

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
