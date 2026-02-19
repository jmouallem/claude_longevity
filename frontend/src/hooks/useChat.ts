import { useState, useCallback, useRef } from 'react';
import { apiClient } from '../api/client';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  specialist_used?: string;
  created_at: string;
  isStreaming?: boolean;
}

interface HistoryMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  specialist_used?: string;
  created_at: string;
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const loadHistory = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const history = await apiClient.get<HistoryMessage[]>('/api/chat/history');
      setMessages(
        history.map((msg) => ({
          id: msg.id,
          role: msg.role,
          content: msg.content,
          specialist_used: msg.specialist_used,
          created_at: msg.created_at,
          isStreaming: false,
        }))
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load chat history');
    } finally {
      setLoading(false);
    }
  }, []);

  const sendMessage = useCallback(async (text: string, imageFile?: File) => {
    if (!text.trim() && !imageFile) return;

    setError(null);

    const userMessageId = `user-${Date.now()}`;
    const assistantMessageId = `assistant-${Date.now()}`;

    const userMessage: ChatMessage = {
      id: userMessageId,
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
      isStreaming: false,
    };

    const assistantMessage: ChatMessage = {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      created_at: new Date().toISOString(),
      isStreaming: true,
    };

    setMessages((prev) => [...prev, userMessage, assistantMessage]);
    setLoading(true);

    try {
      const formData = new FormData();
      formData.append('message', text);
      if (imageFile) {
        formData.append('image', imageFile);
      }

      const token = apiClient.getToken();
      const controller = new AbortController();
      abortRef.current = controller;

      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: formData,
        signal: controller.signal,
      });

      if (response.status === 401) {
        apiClient.clearToken();
        window.location.href = '/login';
        return;
      }

      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || body.message || `Request failed: ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error('No response stream available');
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        // Keep the last potentially incomplete line in the buffer
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || !trimmed.startsWith('data: ')) continue;

          const jsonStr = trimmed.slice(6);
          if (jsonStr === '[DONE]') continue;

          try {
            const parsed = JSON.parse(jsonStr);

            if (parsed.type === 'chunk') {
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === assistantMessageId
                    ? { ...msg, content: msg.content + parsed.text }
                    : msg
                )
              );
            } else if (parsed.type === 'done') {
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === assistantMessageId
                    ? {
                        ...msg,
                        isStreaming: false,
                        specialist_used: parsed.specialist || parsed.category,
                      }
                    : msg
                )
              );
            } else if (parsed.type === 'error') {
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === assistantMessageId
                    ? { ...msg, content: parsed.text, isStreaming: false }
                    : msg
                )
              );
              setError(parsed.text);
            }
          } catch {
            // Skip malformed JSON lines
          }
        }
      }

      // Ensure streaming is marked complete even if no "done" event was received
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMessageId && msg.isStreaming
            ? { ...msg, isStreaming: false }
            : msg
        )
      );
    } catch (err) {
      if ((err as Error).name === 'AbortError') return;

      const errorMessage = err instanceof Error ? err.message : 'Failed to send message';
      setError(errorMessage);
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMessageId
            ? { ...msg, content: 'Sorry, something went wrong. Please try again.', isStreaming: false }
            : msg
        )
      );
    } finally {
      setLoading(false);
      abortRef.current = null;
    }
  }, []);

  return { messages, loading, error, sendMessage, loadHistory };
}
