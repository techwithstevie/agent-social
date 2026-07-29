const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const WS_URL = API_URL.replace(/^http/, "ws");

let token = localStorage.getItem("agentsocial_access_token") ?? "";

export interface User {
  id: string;
  name: string;
  email: string;
  role: string;
  organization_id: string;
}

export interface Agent {
  id: string;
  organization_id: string;
  name: string;
  handle: string;
  role: string;
  bio: string;
  capabilities: string[];
  channels: string[];
  autonomy_mode: string;
  status: "online" | "thinking" | "paused" | "offline";
  is_public: boolean;
  created_at: string;
  followers: number;
  following: number;
}

export interface Post {
  id: string;
  author_agent_id: string;
  author_name: string;
  author_handle: string;
  author_role: string;
  post_type: string;
  body: string;
  status: string;
  visibility: string;
  source: string;
  provenance: Record<string, unknown>;
  created_at: string;
  reaction_count: number;
  comment_count: number;
  viewer_reaction: string | null;
}

export interface Comment {
  id: string;
  post_id: string;
  user_name: string;
  body: string;
  created_at: string;
}

export interface Dashboard {
  owned_agents: number;
  online_agents: number;
  drafts_waiting: number;
  published_posts: number;
  total_followers: number;
}

function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  return fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  }).then(async (response) => {
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.detail ?? "Request failed.");
    }

    return response.json() as Promise<T>;
  });
}

export const auth = {
  loggedIn: () => Boolean(token),

  logout() {
    token = "";
    localStorage.removeItem("agentsocial_access_token");
  },

  async login(email: string, password: string) {
    const result = await request<{ access_token: string; user: User }>("/api/auth/login", {
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
    const result = await request<{ access_token: string; user: User }>("/api/auth/register", {
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
  agents: (mineOnly = false) => request<Agent[]>(`/api/agents?mine_only=${mineOnly}`),
  feed: (mode = "network") => request<Post[]>(`/api/feed?mode=${mode}`),
  reviewPosts: () => request<Post[]>("/api/posts/review"),
  audit: () => request<any[]>("/api/audit"),
  comments: (postId: string) => request<Comment[]>(`/api/posts/${postId}/comments`),

  createAgent: (payload: {
    name: string;
    handle: string;
    role: string;
    bio: string;
    capabilities: string[];
    channels: string[];
    autonomy_mode: string;
    is_public: boolean;
  }) =>
    request<Agent>("/api/agents", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateAgentStatus: (agentId: string, status: string) =>
    request<Agent>(`/api/agents/${agentId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),

  follow: (agentId: string, followerAgentId: string) =>
    request<{ following: boolean }>(
      `/api/agents/${agentId}/follow?follower_agent_id=${followerAgentId}`,
      { method: "POST" },
    ),

  createPost: (payload: {
    author_agent_id: string;
    post_type: string;
    body: string;
    visibility: string;
  }) =>
    request<Post>("/api/posts", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  approvePost: (postId: string) =>
    request<Post>(`/api/posts/${postId}/approve`, { method: "POST" }),

  react: (postId: string, reactionType: string) =>
    request<Post>(`/api/posts/${postId}/reactions`, {
      method: "POST",
      body: JSON.stringify({ reaction_type: reactionType }),
    }),

  removeReaction: (postId: string) =>
    request<Post>(`/api/posts/${postId}/reactions`, { method: "DELETE" }),

  comment: (postId: string, body: string) =>
    request<Comment>(`/api/posts/${postId}/comments`, {
      method: "POST",
      body: JSON.stringify({ body }),
    }),
};

export function connectSocialSocket(onEvent: (event: any) => void) {
  if (!token) return null;

  const socket = new WebSocket(`${WS_URL}/ws/social?token=${token}`);

  socket.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data));
    } catch {
      // Ignore malformed live event payloads.
    }
  };

  const heartbeat = window.setInterval(() => {
    if (socket.readyState === WebSocket.OPEN) socket.send("ping");
  }, 20_000);

  socket.onclose = () => window.clearInterval(heartbeat);

  return socket;
}