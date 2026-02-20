import { useState, useRef, useEffect, useCallback } from 'react';
import VoiceButton from './VoiceButton';
import ImageUpload from './ImageUpload';

interface ChatInputProps {
  onSend: (message: string, imageFile?: File) => void;
  selectedImage: File | null;
  onSelectedImageChange: (file: File | null) => void;
  disabled?: boolean;
}

export default function ChatInput({
  onSend,
  selectedImage,
  onSelectedImageChange,
  disabled = false,
}: ChatInputProps) {
  const [text, setText] = useState('');
  const [selectedImagePreview, setSelectedImagePreview] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = `${Math.min(textarea.scrollHeight, 120)}px`;
    }
  }, [text]);

  useEffect(() => {
    let cancelled = false;
    if (!selectedImage) {
      setSelectedImagePreview(null);
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      if (!cancelled) {
        setSelectedImagePreview(typeof reader.result === 'string' ? reader.result : null);
      }
    };
    reader.onerror = () => {
      if (!cancelled) {
        setSelectedImagePreview(null);
      }
    };
    reader.readAsDataURL(selectedImage);
    return () => {
      cancelled = true;
    };
  }, [selectedImage]);

  const handleSubmit = useCallback(() => {
    const trimmed = text.trim();
    if (!trimmed && !selectedImage) return;
    if (disabled) return;

    onSend(trimmed, selectedImage || undefined);
    setText('');
    onSelectedImageChange(null);
    setSelectedImagePreview(null);

    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [text, selectedImage, disabled, onSend, onSelectedImageChange]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleVoiceTranscript = useCallback((transcript: string) => {
    setText((prev) => {
      const separator = prev.trim() ? ' ' : '';
      return prev + separator + transcript;
    });
  }, []);

  const canSend = (text.trim().length > 0 || selectedImage !== null) && !disabled;

  return (
    <div className="border-t border-slate-700 bg-slate-800 px-4 py-3">
      {/* Image preview row */}
      {selectedImage && (
        <div className="mb-2 flex items-center gap-2">
          {selectedImagePreview ? (
            <img
              src={selectedImagePreview}
              alt="Selected"
              className="w-16 h-16 rounded-lg object-cover border border-slate-600"
            />
          ) : (
            <div className="w-16 h-16 rounded-lg border border-slate-600 bg-slate-700/60 flex items-center justify-center text-[10px] text-slate-300">
              Image
            </div>
          )}
          <button
            type="button"
          onClick={() => onSelectedImageChange(null)}
          className="p-1 text-slate-400 hover:text-red-400 transition-colors"
          title="Remove image"
        >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}

      <div className="flex items-end gap-2">
        {/* Image upload */}
        <ImageUpload
          onImageSelect={onSelectedImageChange}
        />

        {/* Voice button */}
        <VoiceButton onTranscript={handleVoiceTranscript} />

        {/* Text input */}
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type your message..."
          rows={1}
          disabled={disabled}
          className="flex-1 resize-none bg-slate-700 border border-slate-600 rounded-xl px-4 py-2.5 text-sm text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        />

        {/* Send button */}
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!canSend}
          className="p-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-600 disabled:cursor-not-allowed text-white rounded-xl transition-colors shrink-0"
          title="Send message"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5"
            />
          </svg>
        </button>
      </div>
    </div>
  );
}
