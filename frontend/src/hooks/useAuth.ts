import { useEffect } from 'react';
import { useAuthStore } from '../stores/authStore';

export function useAuth() {
  const {
    user,
    isAuthenticated,
    loading,
    error,
    login,
    register,
    logout,
    loadUser,
    clearError,
  } = useAuthStore();

  useEffect(() => {
    if (!isAuthenticated && !loading) {
      loadUser();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    user,
    isAuthenticated,
    loading,
    error,
    login,
    register,
    logout,
    clearError,
  };
}
