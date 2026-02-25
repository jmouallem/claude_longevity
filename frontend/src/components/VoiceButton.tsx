import { useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useVoice } from '../hooks/useVoice';

interface VoiceButtonProps {
  onTranscript: (text: string) => void;
}

function RecordingOverlay({
  transcript,
  interimText,
  onStop,
}: {
  transcript: string;
  interimText: string;
  onStop: () => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [transcript, interimText]);

  return createPortal(
    <div className="fixed inset-0 z-[100] flex flex-col items-center justify-center bg-slate-950/85 backdrop-blur-sm">
      {/* Live transcript area */}
      <div
        ref={scrollRef}
        className="w-full max-w-md px-6 mb-8 max-h-[30vh] overflow-y-auto text-center"
      >
        {(transcript || interimText) ? (
          <p className="text-base text-slate-200 leading-relaxed">
            {transcript}
            {interimText && (
              <span className="text-slate-400">{transcript ? ' ' : ''}{interimText}</span>
            )}
          </p>
        ) : (
          <p className="text-sm text-slate-500">Listening... start speaking</p>
        )}
      </div>

      {/* Animated mic button */}
      <button
        type="button"
        onClick={onStop}
        className="relative flex items-center justify-center w-24 h-24 rounded-full bg-red-600 text-white shadow-lg shadow-red-900/40 transition-transform active:scale-95 focus:outline-none"
        aria-label="Stop recording"
      >
        {/* Pulsing ring 1 */}
        <span className="absolute inset-0 rounded-full border-2 border-red-400/60 animate-[voice-ping_2s_ease-out_infinite]" />
        {/* Pulsing ring 2 (delayed) */}
        <span className="absolute inset-0 rounded-full border-2 border-red-400/40 animate-[voice-ping_2s_ease-out_0.6s_infinite]" />
        {/* Mic icon */}
        <svg className="w-10 h-10 relative z-10" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M12 18.75a6 6 0 006-6v-1.5m-6 7.5a6 6 0 01-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 01-3-3V4.5a3 3 0 116 0v8.25a3 3 0 01-3 3z"
          />
        </svg>
      </button>

      <p className="mt-5 text-xs text-slate-500">Tap to stop recording</p>
    </div>,
    document.body
  );
}

export default function VoiceButton({ onTranscript }: VoiceButtonProps) {
  const { isListening, transcript, interimText, isSupported, error, startListening, stopListening } = useVoice();
  const prevTranscriptRef = useRef('');

  // When listening stops and we have a final transcript, send it up
  useEffect(() => {
    if (!isListening && transcript && transcript !== prevTranscriptRef.current) {
      prevTranscriptRef.current = transcript;
      onTranscript(transcript);
    }
  }, [isListening, transcript, onTranscript]);

  const handleStart = useCallback(() => {
    if (!isSupported) return;
    prevTranscriptRef.current = '';
    startListening();
  }, [isSupported, startListening]);

  return (
    <div className="flex flex-col items-center gap-1">
      <button
        type="button"
        onClick={handleStart}
        disabled={!isSupported || isListening}
        className="p-1.5 sm:p-2 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-slate-400 hover:text-slate-200 hover:bg-slate-600"
        title={
          !isSupported
            ? 'Voice input is not supported in this browser'
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

      {isListening && (
        <RecordingOverlay
          transcript={transcript}
          interimText={interimText}
          onStop={stopListening}
        />
      )}
    </div>
  );
}
