import { useState, useEffect, useRef, useCallback } from 'react';
import { apiClient } from '../api/client';

interface FastingResponse {
  active: boolean;
  fast_start: string | null;
  elapsed_minutes: number;
  fast_type: string | null;
}

interface FastingTimerState {
  isActive: boolean;
  elapsedMinutes: number;
  elapsedFormatted: string;
  fastType: string | null;
  startTime: string | null;
}

function formatElapsed(totalMinutes: number): string {
  const hours = Math.floor(totalMinutes / 60);
  const minutes = Math.floor(totalMinutes % 60);
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
}

export function useFastingTimer(): FastingTimerState {
  const [data, setData] = useState<FastingResponse | null>(null);
  const [liveElapsed, setLiveElapsed] = useState(0);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchFasting = useCallback(async () => {
    try {
      const res = await apiClient.get<FastingResponse>('/api/logs/fasting/active');
      setData(res);
      if (res.active && res.fast_start) {
        const startMs = new Date(res.fast_start).getTime();
        const nowMs = Date.now();
        setLiveElapsed((nowMs - startMs) / 60000);
      } else {
        setLiveElapsed(0);
      }
    } catch {
      // silently ignore - fasting endpoint may 404 if no fasts exist
    }
  }, []);

  // Poll every 30 seconds
  useEffect(() => {
    fetchFasting();
    pollRef.current = setInterval(fetchFasting, 30000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [fetchFasting]);

  // Tick every second when active
  useEffect(() => {
    if (data?.active && data.fast_start) {
      const startMs = new Date(data.fast_start).getTime();
      tickRef.current = setInterval(() => {
        setLiveElapsed((Date.now() - startMs) / 60000);
      }, 1000);
    } else {
      setLiveElapsed(0);
    }
    return () => {
      if (tickRef.current) clearInterval(tickRef.current);
    };
  }, [data?.active, data?.fast_start]);

  return {
    isActive: data?.active ?? false,
    elapsedMinutes: liveElapsed,
    elapsedFormatted: formatElapsed(liveElapsed),
    fastType: data?.fast_type ?? null,
    startTime: data?.fast_start ?? null,
  };
}
