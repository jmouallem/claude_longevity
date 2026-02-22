import { create } from 'zustand';
import { apiClient } from '../api/client';
import { getPasskeyAssertion } from '../utils/webauthn';

export interface User {
  id: number;
  username: string;
  display_name: string;
  role: 'user' | 'admin';
  force_password_change: boolean;
}

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  loading: boolean;
  error: string | null;

  login: (username: string, password: string) => Promise<void>;
  loginWithPasskey: (username?: string) => Promise<void>;
  register: (username: string, password: string, displayName: string) => Promise<void>;
  logout: () => Promise<void>;
  loadUser: () => Promise<void>;
  clearError: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  loading: false,
  error: null,

  login: async (username: string, password: string) => {
    set({ loading: true, error: null });
    try {
      await apiClient.post<{ access_token?: string | null }>(
        '/api/auth/login',
        { username, password }
      );
      // Fetch user profile
      const user = await apiClient.get<User>('/api/auth/me');
      set({
        user,
        isAuthenticated: true,
        loading: false,
      });
    } catch (err) {
      set({
        loading: false,
        error: err instanceof Error ? err.message : 'Login failed',
      });
      throw err;
    }
  },

  loginWithPasskey: async (username?: string) => {
    set({ loading: true, error: null });
    try {
      const options = await apiClient.post<{ request_id: number; public_key: Record<string, unknown> }>(
        '/api/auth/passkey/login/options',
        { username: (username || '').trim() || null }
      );
      const credential = await getPasskeyAssertion(options.public_key);
      await apiClient.post<{ access_token?: string | null }>(
        '/api/auth/passkey/login/verify',
        { request_id: options.request_id, credential }
      );
      const user = await apiClient.get<User>('/api/auth/me');
      set({
        user,
        isAuthenticated: true,
        loading: false,
      });
    } catch (err) {
      set({
        loading: false,
        error: err instanceof Error ? err.message : 'Passkey sign-in failed',
      });
      throw err;
    }
  },

  register: async (username: string, password: string, displayName: string) => {
    set({ loading: true, error: null });
    try {
      await apiClient.post<{ access_token?: string | null }>(
        '/api/auth/register',
        { username, password, display_name: displayName }
      );
      // Fetch user profile
      const user = await apiClient.get<User>('/api/auth/me');
      set({
        user,
        isAuthenticated: true,
        loading: false,
      });
    } catch (err) {
      set({
        loading: false,
        error: err instanceof Error ? err.message : 'Registration failed',
      });
      throw err;
    }
  },

  logout: async () => {
    try {
      await apiClient.post('/api/auth/logout');
    } catch {
      // Continue with client-side sign-out even if server-side logout fails.
    }
    set({
      user: null,
      isAuthenticated: false,
      error: null,
    });
  },

  loadUser: async () => {
    set({ loading: true });
    try {
      const user = await apiClient.get<User>('/api/auth/me');
      set({
        user,
        isAuthenticated: true,
        loading: false,
      });
    } catch {
      set({
        user: null,
        isAuthenticated: false,
        loading: false,
      });
    }
  },

  clearError: () => set({ error: null }),
}));
