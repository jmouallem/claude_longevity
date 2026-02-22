async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };

  if (!headers['Content-Type'] && options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }

  const response = await fetch(url, {
    ...options,
    headers,
    credentials: 'include',
  });

  if (response.status === 401) {
    window.location.href = '/login';
    throw new Error('Unauthorized');
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || body.message || `Request failed: ${response.status}`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}

export const apiClient = {
  get<T>(url: string): Promise<T> {
    return request<T>(url, { method: 'GET' });
  },

  post<T>(url: string, data?: unknown): Promise<T> {
    return request<T>(url, {
      method: 'POST',
      body: data ? JSON.stringify(data) : undefined,
    });
  },

  put<T>(url: string, data?: unknown): Promise<T> {
    return request<T>(url, {
      method: 'PUT',
      body: data ? JSON.stringify(data) : undefined,
    });
  },

  delete<T>(url: string): Promise<T> {
    return request<T>(url, { method: 'DELETE' });
  },
};

