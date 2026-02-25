import { useState, useCallback, useRef, useEffect } from 'react';

interface SpeechRecognitionEvent {
  results: SpeechRecognitionResultList;
  resultIndex: number;
}

interface SpeechRecognitionErrorEvent {
  error: string;
  message?: string;
}

interface SpeechRecognitionInstance {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
}

declare global {
  interface Window {
    SpeechRecognition: new () => SpeechRecognitionInstance;
    webkitSpeechRecognition: new () => SpeechRecognitionInstance;
  }
}

function getSpeechRecognition(): (new () => SpeechRecognitionInstance) | null {
  if (typeof window === 'undefined') return null;
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

async function requestMicrophoneAccess(): Promise<void> {
  const isSecure =
    typeof window !== 'undefined' &&
    (window.isSecureContext ||
      window.location.hostname === 'localhost' ||
      window.location.hostname === '127.0.0.1');
  if (!isSecure) {
    throw new Error('insecure-context');
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error('mic-unavailable');
  }
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  stream.getTracks().forEach((t) => t.stop());
}

export function useVoice() {
  const [isListening, setIsListening] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [interimText, setInterimText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null);
  // Accumulate finalized segments across the continuous session
  const accumulatedRef = useRef('');
  // Track intentional stop so onend doesn't restart
  const stoppingRef = useRef(false);

  const isSupported = getSpeechRecognition() !== null;

  const startListening = useCallback(() => {
    const run = async () => {
      try {
        await requestMicrophoneAccess();
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'unknown';
        if (msg === 'insecure-context') {
          setError('Microphone requires HTTPS (or localhost).');
        } else if (msg === 'mic-unavailable') {
          setError('Microphone API is unavailable in this browser.');
        } else {
          setError('Microphone permission denied.');
        }
        return;
      }

      const SpeechRecognitionCtor = getSpeechRecognition();
      if (!SpeechRecognitionCtor) {
        setError('Speech recognition is not supported in this browser.');
        return;
      }
      setError(null);
      accumulatedRef.current = '';
      stoppingRef.current = false;

      const recognition = new SpeechRecognitionCtor();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = 'en-US';

      recognition.onresult = (event: SpeechRecognitionEvent) => {
        let finalChunk = '';
        let interim = '';

        for (let i = event.resultIndex; i < event.results.length; i++) {
          const result = event.results[i];
          if (result.isFinal) {
            finalChunk += result[0].transcript;
          } else {
            interim += result[0].transcript;
          }
        }

        if (finalChunk) {
          const sep = accumulatedRef.current ? ' ' : '';
          accumulatedRef.current += sep + finalChunk;
          setTranscript(accumulatedRef.current);
        }
        setInterimText(interim);
      };

      recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
        const code = event?.error || 'unknown';
        // "no-speech" is common during pauses — don't kill the session
        if (code === 'no-speech') return;
        if (code === 'not-allowed') {
          setError('Microphone permission denied.');
        } else if (code === 'audio-capture') {
          setError('No microphone detected.');
        } else if (code !== 'aborted') {
          setError(`Voice error: ${code}`);
        }
        setIsListening(false);
        recognitionRef.current = null;
      };

      recognition.onend = () => {
        // If user intentionally stopped, finalize
        if (stoppingRef.current) {
          setIsListening(false);
          recognitionRef.current = null;
          return;
        }
        // Otherwise the browser stopped on its own (silence timeout) — restart
        // to keep recording until user explicitly presses stop.
        if (recognitionRef.current) {
          try {
            recognitionRef.current.start();
          } catch {
            setIsListening(false);
            recognitionRef.current = null;
          }
        }
      };

      recognitionRef.current = recognition;
      setTranscript('');
      setInterimText('');
      setIsListening(true);
      try {
        recognition.start();
      } catch {
        setIsListening(false);
        recognitionRef.current = null;
        setError('Unable to start microphone.');
      }
    };

    void run();
  }, []);

  const stopListening = useCallback(() => {
    stoppingRef.current = true;
    if (recognitionRef.current) {
      recognitionRef.current.stop();
      recognitionRef.current = null;
    }
    setInterimText('');
    setIsListening(false);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stoppingRef.current = true;
      if (recognitionRef.current) {
        recognitionRef.current.abort();
        recognitionRef.current = null;
      }
    };
  }, []);

  return { isListening, transcript, interimText, isSupported, error, startListening, stopListening };
}
