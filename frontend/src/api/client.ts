export interface AuthStatus {
  connected: boolean;
  session_file: string;
  message: string | null;
}

export interface LoginStatus {
  state: string;
  error: string | null;
}

export interface Campaign {
  id: number;
  name: string;
  search_query: string;
  area_id: string | null;
  apply_limit: number;
  status: string;
  sent_count: number;
  skipped_count: number;
  failed_count: number;
  processed_count: number;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ApplicationLog {
  id: number;
  campaign_id: number;
  vacancy_id: string;
  vacancy_title: string | null;
  status: string;
  detail: string | null;
  created_at: string;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  getAuthStatus: () => request<AuthStatus>("/api/auth/status"),

  startLogin: () =>
    request<{ status: string; message: string }>("/api/auth/login/start", {
      method: "POST",
    }),

  getLoginStatus: () => request<LoginStatus>("/api/auth/login/status"),

  submitPhone: (phone: string) =>
    request<{ status: string; message: string }>("/api/auth/login/phone", {
      method: "POST",
      body: JSON.stringify({ phone }),
    }),

  submitCode: (code: string) =>
    request<{ status: string; message: string }>("/api/auth/login/code", {
      method: "POST",
      body: JSON.stringify({ code }),
    }),

  cancelLogin: () =>
    request<{ status: string }>("/api/auth/login/cancel", { method: "POST" }),

  deleteSession: () =>
    request<{ status: string }>("/api/auth/session", { method: "DELETE" }),

  getCampaigns: () => request<Campaign[]>("/api/campaigns"),

  createCampaign: (data: {
    name: string;
    search_query: string;
    area_id?: string;
    apply_limit: number;
  }) =>
    request<Campaign>("/api/campaigns", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  startCampaign: (id: number) =>
    request<Campaign>(`/api/campaigns/${id}/start`, { method: "POST" }),

  stopCampaign: (id: number) =>
    request<Campaign>(`/api/campaigns/${id}/stop`, { method: "POST" }),

  deleteCampaign: (id: number) =>
    request<{ status: string }>(`/api/campaigns/${id}`, { method: "DELETE" }),

  getCampaignLogs: (id: number) =>
    request<ApplicationLog[]>(`/api/campaigns/${id}/logs`),
};
