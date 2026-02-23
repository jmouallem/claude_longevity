import { useEffect, useRef } from 'react';
import { useVoice } from '../hooks/useVoice';

interface VoiceButtonProps {
  onTranscript: (text: string) => void;
}

export default function VoiceButton({ onTranscript }: VoiceButtonProps) {
  const { isListening, transcript, isSupported, error, startListening, stopListening } = useVoice();
  const prevTranscriptRef = useRef('');

  // When listening stops and we have a final transcript, send it up
  useEffect(() => {
    if (!isListening && transcript && transcript !== prevTranscriptRef.current) {
      prevTranscriptRef.current = transcript;
      onTranscript(transcript);
    }
  }, [isListening, transcript, onTranscript]);

  const handleClick = () => {
    if (!isSupported) return;
    if (isListening) {
      stopListening();
    } else {
      startListening();
    }
  };

  return (
    <div className="flex flex-col items-center gap-1">
      <button
        type="button"
        onClick={handleClick}
        disabled={!isSupported}
        className={`p-1.5 sm:p-2 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
          isListening
            ? 'text-red-400 bg-red-500/20 animate-pulse'
            : 'text-slate-400 hover:text-slate-200 hover:bg-slate-600'
        }`}
        title={
          !isSupported
            ? 'Voice input is not supported in this browser'
            : isListening
              ? 'Stop listening'
              : 'Voice input'
        }
      >
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M12 18.75a6 6 0 006-6v-1.5m-6 7.5a6 6 0 01-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 01-3-3V4.5a3 3 0 116 0v8.25a3 3 0 01-3 3z"
          />
        </svg>
      </button>
      {error && <span className="text-[10px] text-rose-400 leading-none">{error}</span>}
    </div>
  );
}
