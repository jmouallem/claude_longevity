import { useState, useEffect, useCallback } from 'react';
import { Fragment, type ReactNode } from 'react';
import { apiClient } from '../api/client';

type SummaryFilter = 'all' | 'daily' | 'weekly' | 'monthly';

interface Summary {
  id: number;
  summary_type: string;
  period_start: string;
  period_end: string;
  full_narrative: string;
}

function FilterTab({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-1.5 text-sm font-medium rounded-lg transition-colors ${
        active
          ? 'bg-emerald-600 text-white'
          : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
      }`}
    >
      {label}
    </button>
  );
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
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

function SummaryCard({ summary }: { summary: Summary }) {
  const [expanded, setExpanded] = useState(false);

  const typeBadgeColor: Record<string, string> = {
    daily: 'bg-sky-900/50 text-sky-400',
    weekly: 'bg-violet-900/50 text-violet-400',
    monthly: 'bg-amber-900/50 text-amber-400',
  };

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-5 py-4 flex items-center justify-between text-left hover:bg-slate-750 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${typeBadgeColor[summary.summary_type] ?? 'bg-slate-700 text-slate-300'}`}>
            {summary.summary_type}
          </span>
          <span className="text-sm text-slate-200">
            {formatDate(summary.period_start)}
            {summary.period_start !== summary.period_end && (
              <> &mdash; {formatDate(summary.period_end)}</>
            )}
          </span>
        </div>
        <svg
          className={`w-4 h-4 text-slate-400 transition-transform ${expanded ? 'rotate-180' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {expanded && (
        <div className="px-5 pb-5 border-t border-slate-700">
          <div className="pt-4 text-sm leading-7 break-words space-y-3 text-slate-300">
            {renderMarkdown(summary.full_narrative)}
          </div>
        </div>
      )}
    </div>
  );
}

export default function History() {
  const [summaries, setSummaries] = useState<Summary[]>([]);
  const [filter, setFilter] = useState<SummaryFilter>('all');
  const [loading, setLoading] = useState(true);

  const fetchSummaries = useCallback(async () => {
    setLoading(true);
    try {
      const params = filter === 'all' ? '' : `summary_type=${filter}&`;
      const data = await apiClient.get<Summary[]>(`/api/summaries?${params}limit=50`);
      setSummaries(data);
    } catch {
      setSummaries([]);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    fetchSummaries();
  }, [fetchSummaries]);

  return (
    <div className="max-w-3xl mx-auto px-4 py-6">
      <h1 className="text-2xl font-bold text-slate-100 mb-6">History</h1>

      <div className="flex gap-2 mb-6">
        {(['all', 'daily', 'weekly', 'monthly'] as SummaryFilter[]).map((f) => (
          <FilterTab
            key={f}
            active={filter === f}
            label={f.charAt(0).toUpperCase() + f.slice(1)}
            onClick={() => setFilter(f)}
          />
        ))}
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : summaries.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-slate-400">No summaries found.</p>
          <p className="text-slate-500 text-sm mt-1">Generate a daily summary from the Dashboard to get started.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {summaries.map((s) => (
            <SummaryCard key={s.id} summary={s} />
          ))}
        </div>
      )}
    </div>
  );
}
