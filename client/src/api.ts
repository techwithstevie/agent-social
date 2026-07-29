const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export interface User {
  id: string;
  name: string;
  email: string;
  role: string;
  organization_id: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface Agent {
  id: string;
  name: string;
  role: string;
  instructions: string;
  channels: string[];
  status: string;
  created_at: string;
}

export interface Campaign {
  id: string;
  name: string;
  objective: string;
  audience: string;
  brand_voice: string;
  channels: string[];
  status: string;
  created_at: string;
}

export interface AgentRun {
  id: string;
  agent_id: string;
  campaign_id: string;
  topic: string;
  channel: string;
  status: "queued" | "running" | "completed" | "failed";
  provider: string;
  model: string;
  output_json: Record<string, unknown> | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface ContentPost {
  id: string;
  campaign_id: string;
  agent_id: string;
  agent_run_id: string;
  title: string;
  body: string;
  channel: string;
  hashtags: string[];
  risk_flags: string[];
  risk_score: number;
  status: string;
  approved_at: string | null;
  published_at: string | null;
  publish_response: Record<string, unknown> | null;
  created_at: string;
}

export interface AuditEvent {
  id: string;
  actor_type: string;
  action: string;
  resource_type: string;
  resource_id: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface Dashboard {
  active_campaigns: number;
  awaiting_review: number;
  approved_ready: number;
  published: number;
  total_runs: number;
  provider: string;
}

let token = localStorage.getItem("agentsocial_access_token") ?? "";

function headers(extra: HeadersInit = {}) {
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extra,
  };
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: headers(options.headers),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? "Request failed.");
  }

  return response.json() as Promise<T>;
}

export const auth = {
  isLoggedIn: () => Boolean(token),

  logout() {
    token = "";
    localStorage.removeItem("agentsocial_access_token");
  },

  async login(email: string, password: string) {
    const result = await request<AuthResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    token = result.access_token;
    localStorage.setItem("agentsocial_access_token", token);
    return result;
  },

  async register(payload: {
    name: string;
    organization_name: string;
    email: string;
    password: string;
  }) {
    const result = await request<AuthResponse>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    token = result.access_token;
    localStorage.setItem("agentsocial_access_token", token);
    return result;
  },
};

export const api = {
  me: () => request<User>("/api/me"),
  dashboard: () => request<Dashboard>("/api/dashboard"),
  agents: () => request<Agent[]>("/api/agents"),
  campaigns: () => request<Campaign[]>("/api/campaigns"),
  posts: () => request<ContentPost[]>("/api/posts"),
  audit: () => request<AuditEvent[]>("/api/audit"),

  createAgent: (payload: Omit<Agent, "id" | "status" | "created_at">) =>
    request<Agent>("/api/agents", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  createCampaign: (payload: Omit<Campaign, "id" | "status" | "created_at">) =>
    request<Campaign>("/api/campaigns", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  createRun: (payload: {
    agent_id: string;
    campaign_id: string;
    topic: string;
    channel: string;
  }) =>
    request<AgentRun>("/api/runs", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getRun: (runId: string) => request<AgentRun>(`/api/runs/${runId}`),

  approvePost: (postId: string) =>
    request<ContentPost>(`/api/posts/${postId}/approve`, {
      method: "POST",
    }),

  requestChanges: (postId: string) =>
    request<ContentPost>(`/api/posts/${postId}/request-changes`, {
      method: "POST",
    }),

  publishPost: (postId: string) =>
    request<{ post: ContentPost; message: string }>(`/api/posts/${postId}/publish`, {
      method: "POST",
    }),
};