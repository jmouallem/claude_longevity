import { useEffect, useRef, useState } from 'react';
import { useChat } from '../hooks/useChat';
import ChatMessage from '../components/ChatMessage';
import ChatInput from '../components/ChatInput';

const PENDING_IMAGE_KEY = 'chat_pending_image_data_url';
const PENDING_IMAGE_NAME_KEY = 'chat_pending_image_name';
const PENDING_IMAGE_TYPE_KEY = 'chat_pending_image_type';

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

export default function Chat() {
  const { messages, loading, error, sendMessage, loadHistory } = useChat();
  const [selectedImage, setSelectedImage] = useState<File | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const hasLoadedRef = useRef(false);

  // Load history on mount
  useEffect(() => {
    if (!hasLoadedRef.current) {
      hasLoadedRef.current = true;
      loadHistory();
    }
  }, [loadHistory]);

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
    sendMessage(text, imageFile);
    setSelectedImage(null);
    sessionStorage.removeItem(PENDING_IMAGE_KEY);
    sessionStorage.removeItem(PENDING_IMAGE_NAME_KEY);
    sessionStorage.removeItem(PENDING_IMAGE_TYPE_KEY);
  };

  const isStreaming = messages.some((m) => m.isStreaming);

  return (
    <div className="flex flex-col h-[calc(100vh-3.5rem)]">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {messages.length === 0 && !loading ? (
          /* Empty state */
          <div className="flex items-center justify-center h-full">
            <div className="text-center max-w-md">
              <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-emerald-500/10 flex items-center justify-center">
                <svg
                  className="w-8 h-8 text-emerald-500"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={1.5}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z"
                  />
                </svg>
              </div>
              <h2 className="text-xl font-semibold text-slate-100 mb-2">
                Welcome to The Longevity Alchemist!
              </h2>
              <p className="text-slate-400 text-sm leading-relaxed">
                I'm your AI health coach. Start by telling me about your health goals,
                logging a meal, or asking me anything about nutrition, exercise, sleep,
                or supplements.
              </p>
            </div>
          </div>
        ) : (
          /* Messages list */
          <div className="max-w-3xl mx-auto">
            {messages.map((message) => (
              <ChatMessage key={message.id} message={message} />
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}
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
      />
    </div>
  );
}
