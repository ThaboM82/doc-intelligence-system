const API_BASE_URL =
  import.meta.env.VITE_API_URL ??
  "http://localhost:8000/api";

export interface ApiResponse<T> {
  success: boolean;
  data: T;
  message?: string;
}

export async function api<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const response = await fetch(
    `${API_BASE_URL}${endpoint}`,
    {
      headers: {
        "Content-Type":
          "application/json",
        ...options?.headers,
      },
      ...options,
    }
  );

  if (!response.ok) {
    throw new Error(
      `API Error: ${response.status}`
    );
  }

  return response.json();
}

export default api;