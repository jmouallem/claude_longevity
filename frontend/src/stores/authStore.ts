import { create } from 'zustand';
import { apiClient } from '../api/client';

export interface User {
  id: number;
  username: string;
  display_name: string;
  role: 'user' | 'admin';
  force_password_change: boolean;
}

interface AuthState {
  token: string | null;
  user: User | null;
  isAuthenticated: boolean;
  loading: boolean;
  error: string | null;

  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string, displayName: string) => Promise<void>;
  logout: () => void;
  loadUser: () => Promise<void>;
  clearError: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem('longevity_token'),
  user: null,
  isAuthenticated: false,
  loading: false,
  error: null,

  login: async (username: string, password: string) => {
    set({ loading: true, error: null });
    try {
      const data = await apiClient.post<{ access_token: string }>(
        '/api/auth/login',
        { username, password }
      );
      apiClient.setToken(data.access_token);
      set({ token: data.access_token });
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

  register: async (username: string, password: string, displayName: string) => {
    set({ loading: true, error: null });
    try {
      const data = await apiClient.post<{ access_token: string }>(
        '/api/auth/register',
        { username, password, display_name: displayName }
      );
      apiClient.setToken(data.access_token);
      set({ token: data.access_token });
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

  logout: () => {
    apiClient.clearToken();
    set({
      token: null,
      user: null,
      isAuthenticated: false,
      error: null,
    });
  },

  loadUser: async () => {
    const token = apiClient.getToken();
    if (!token) {
      set({ isAuthenticated: false, loading: false });
      return;
    }
    set({ loading: true });
    try {
      const user = await apiClient.get<User>('/api/auth/me');
      set({
        user,
        token,
        isAuthenticated: true,
        loading: false,
      });
    } catch {
      apiClient.clearToken();
      set({
        token: null,
        user: null,
        isAuthenticated: false,
        loading: false,
      });
    }
  },

  clearError: () => set({ error: null }),
}));
