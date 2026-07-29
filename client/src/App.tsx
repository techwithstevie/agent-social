import { type FormEvent, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Bot,
  Check,
  ChevronRight,
  CircleAlert,
  FilePenLine,
  LayoutDashboard,
  LoaderCircle,
  LogOut,
  Megaphone,
  Plus,
  Rocket,
  Send,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import {
  api,
  auth,
  type Agent,
  type AgentRun,
  type AuditEvent,
  type Campaign,
  type ContentPost,
  type Dashboard,
  type User,
} from "./api";

type View = "overview" | "campaigns" | "agents" | "review" | "audit";
type ModalName = "agent" | "campaign" | "generate" | null;

const nav: Array<{ id: View; label: string; icon: typeof LayoutDashboard }> = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "campaigns", label: "Campaigns", icon: Megaphone },
  { id: "agents", label: "Agent Studio", icon: Bot },
  { id: "review", label: "Review Queue", icon: ShieldCheck },
  { id: "audit", label: "Audit Log", icon: Activity },
];

function relativeTime(date: string) {
  const difference = Math.max(1, Date.now() - new Date(date).getTime());
  const minutes = Math.floor(difference / 60_000);
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h ago`;
  return `${Math.floor(minutes / 1440)}d ago`;
}

function shortStatus(status: string) {
  return status.replaceAll("_", " ");
}

export default function App() {
  const [loggedIn, setLoggedIn] = useState(auth.isLoggedIn());
  const [user, setUser] = useState<User | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [posts, setPosts] = useState<ContentPost[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [view, setView] = useState<View>("overview");
  const [modal, setModal] = useState<ModalName>(null);
  const [activeRun, setActiveRun] = useState<AgentRun | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  const refresh = async () => {
    try {
      setBusy(true);
      setError("");

      const [me, dashboardData, agentData, campaignData, postData, auditData] =
        await Promise.all([
          api.me(),
          api.dashboard(),
          api.agents(),
          api.campaigns(),
          api.posts(),
          api.audit(),
        ]);

      setUser(me);
      setDashboard(dashboardData);
      setAgents(agentData);
      setCampaigns(campaignData);
      setPosts(postData);
      setAuditEvents(auditData);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load workspace.");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (loggedIn) void refresh();
  }, [loggedIn]);

  useEffect(() => {
    if (!activeRun || ["completed", "failed"].includes(activeRun.status)) return;

    const timer = window.setInterval(async () => {
      try {
        const updated = await api.getRun(activeRun.id);
        setActiveRun(updated);

        if (updated.status === "completed" || updated.status === "failed") {
          window.clearInterval(timer);
          await refresh();
          if (updated.status === "completed") {
            setView("review");
          }
        }
      } catch {
        window.clearInterval(timer);
      }
    }, 900);

    return () => window.clearInterval(timer);
  }, [activeRun]);

  const reviewPosts = useMemo(
    () => posts.filter((post) => post.status === "in_review"),
    [posts],
  );

  if (!loggedIn) {
    return (
      <AuthScreen
        onComplete={() => {
          setLoggedIn(true);
        }}
      />
    );
  }

  if (busy && !dashboard) {
    return (
      <div className="center-screen">
        <LoaderCircle className="spin" size={28} />
        Opening your workspace…
      </div>
    );
  }

  if (!dashboard) {
    return (
      <div className="center-screen">
        <CircleAlert size={28} />
        <strong>{error || "Unable to open workspace."}</strong>
        <button className="button primary" onClick={() => void refresh()}>
          Retry
        </button>
      </div>
    );
  }

  const handleLogout = () => {
    auth.logout();
    setLoggedIn(false);
    setUser(null);
    setDashboard(null);
  };

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="logo">
          <span className="logo-mark">
            <Sparkles size={18} />
          </span>
          <strong>AgentSocial</strong>
        </div>

        <div className="workspace">
          <span>{user?.name.slice(0, 2).toUpperCase()}</span>
          <div>
            <strong>{user?.name}</strong>
            <small>{user?.role}</small>
          </div>
        </div>

        <nav>
          {nav.map((item) => {
            const Icon = item.icon;
            return (
              <button
                className={`nav-button ${view === item.id ? "selected" : ""}`}
                key={item.id}
                onClick={() => setView(item.id)}
              >
                <Icon size={18} />
                <span>{item.label}</span>
                {item.id === "review" && reviewPosts.length > 0 ? (
                  <b>{reviewPosts.length}</b>
                ) : null}
              </button>
            );
          })}
        </nav>

        <div className="sidebar-foot">
          <div className="security">
            <ShieldCheck size={18} />
            <span>
              <strong>Reviewable autonomy</strong>
              Agents draft. Humans authorize.
            </span>
          </div>
          <button className="nav-button" onClick={handleLogout}>
            <LogOut size={18} />
            <span>Sign out</span>
          </button>
        </div>
      </aside>

      <main>
        <header className="topbar">
          <div>
            <p className="eyebrow">OPERATIONS WORKSPACE</p>
            <h1>{nav.find((item) => item.id === view)?.label}</h1>
          </div>
          <div className="top-actions">
            <span className="provider">
              <span />
              Provider: {dashboard.provider}
            </span>
            <button className="button primary" onClick={() => setModal("generate")}>
              <Sparkles size={16} />
              Generate content
            </button>
          </div>
        </header>

        {error ? (
          <div className="error-banner">
            <CircleAlert size={17} />
            {error}
          </div>
        ) : null}

        <div className="page">
          {activeRun ? <RunStatus run={activeRun} onClose={() => setActiveRun(null)} /> : null}

          {view === "overview" && (
            <Overview
              dashboard={dashboard}
              posts={posts}
              onGenerate={() => setModal("generate")}
              onReview={() => setView("review")}
            />
          )}

          {view === "agents" && (
            <Agents agents={agents} onCreate={() => setModal("agent")} />
          )}

          {view === "campaigns" && (
            <Campaigns campaigns={campaigns} onCreate={() => setModal("campaign")} />
          )}

          {view === "review" && (
            <ReviewQueue
              posts={posts}
              onRefresh={refresh}
              setError={setError}
            />
          )}

          {view === "audit" && <Audit events={auditEvents} />}
        </div>
      </main>

      {modal === "agent" && (
        <AgentModal
          onClose={() => setModal(null)}
          onCreated={async (payload) => {
            await api.createAgent(payload);
            setModal(null);
            await refresh();
          }}
        />
      )}

      {modal === "campaign" && (
        <CampaignModal
          onClose={() => setModal(null)}
          onCreated={async (payload) => {
            await api.createCampaign(payload);
            setModal(null);
            await refresh();
          }}
        />
      )}

      {modal === "generate" && (
        <GenerateModal
          agents={agents}
          campaigns={campaigns}
          onClose={() => setModal(null)}
          onRun={async (payload) => {
            const run = await api.createRun(payload);
            setModal(null);
            setActiveRun(run);
          }}
        />
      )}
    </div>
  );
}

function AuthScreen({ onComplete }: { onComplete: () => void }) {
  const [mode, setMode] = useState<"login" | "register">("register");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);

    try {
      setSubmitting(true);
      setError("");

      if (mode === "register") {
        await auth.register({
          name: String(form.get("name")),
          organization_name: String(form.get("organization_name")),
          email: String(form.get("email")),
          password: String(form.get("password")),
        });
      } else {
        await auth.login(String(form.get("email")), String(form.get("password")));
      }

      onComplete();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Authentication failed.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <section className="auth-panel">
        <div className="logo">
          <span className="logo-mark">
            <Sparkles size={18} />
          </span>
          <strong>AgentSocial</strong>
        </div>

        <p className="eyebrow">AI SOCIAL OPERATIONS</p>
        <h1>Build a social presence that compounds.</h1>
        <p className="auth-copy">
          Create specialized agents, run real generation jobs, require approval,
          and send approved content to your publishing webhook.
        </p>

        <form className="form" onSubmit={submit}>
          {mode === "register" ? (
            <>
              <label>
                Your name
                <input name="name" placeholder="Stephen Prahl" minLength={2} required />
              </label>
              <label>
                Organization
                <input
                  name="organization_name"
                  placeholder="Prahl Labs"
                  minLength={2}
                  required
                />
              </label>
            </>
          ) : null}

          <label>
            Work email
            <input name="email" type="email" placeholder="you@company.com" required />
          </label>

          <label>
            Password
            <input
              name="password"
              type="password"
              minLength={mode === "register" ? 10 : 1}
              placeholder="At least 10 characters"
              required
            />
          </label>

          {error ? <p className="form-error">{error}</p> : null}

          <button className="button primary full" disabled={submitting}>
            {submitting ? <LoaderCircle className="spin" size={17} /> : <ChevronRight size={17} />}
            {mode === "register" ? "Create workspace" : "Sign in"}
          </button>
        </form>

        <button
          className="link-button"
          onClick={() => {
            setError("");
            setMode(mode === "register" ? "login" : "register");
          }}
        >
          {mode === "register"
            ? "Already have an account? Sign in"
            : "Need a workspace? Create one"}
        </button>
      </section>

      <aside className="auth-art">
        <div className="orb orb-a" />
        <div className="orb orb-b" />
        <div className="floating-card">
          <p>
            <Sparkles size={15} /> Agent run completed
          </p>
          <strong>LinkedIn draft ready for approval</strong>
          <span>Model output validated · Audit event written</span>
        </div>
      </aside>
    </div>
  );
}

function Overview({
  dashboard,
  posts,
  onGenerate,
  onReview,
}: {
  dashboard: Dashboard;
  posts: ContentPost[];
  onGenerate: () => void;
  onReview: () => void;
}) {
  const stats = [
    { label: "Active campaigns", value: dashboard.active_campaigns, icon: Megaphone },
    { label: "Awaiting review", value: dashboard.awaiting_review, icon: ShieldCheck },
    { label: "Approved to publish", value: dashboard.approved_ready, icon: Rocket },
    { label: "Total agent runs", value: dashboard.total_runs, icon: Bot },
  ];

  return (
    <>
      <section className="hero">
        <div>
          <p className="eyebrow">YOUR AGENT TEAM</p>
          <h2>From business goal to approved social execution.</h2>
          <p>
            Every generation is persisted, every approval is auditable, and each
            publish action can call a signed external webhook.
          </p>
          <button className="button primary" onClick={onGenerate}>
            <Sparkles size={16} />
            Start an agent run
          </button>
        </div>
        <div className="hero-icon">
          <Bot size={42} />
          <span>AI</span>
        </div>
      </section>

      <section className="stat-grid">
        {stats.map((stat) => {
          const Icon = stat.icon;
          return (
            <article className="stat-card" key={stat.label}>
              <Icon size={18} />
              <span>{stat.label}</span>
              <strong>{stat.value}</strong>
            </article>
          );
        })}
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">CONTENT OPERATIONS</p>
            <h3>Latest content</h3>
          </div>
          <button className="text-button" onClick={onReview}>
            Open review queue <ChevronRight size={15} />
          </button>
        </div>

        {posts.length === 0 ? (
          <Empty
            icon={<FilePenLine size={26} />}
            title="No content created yet"
            description="Create an agent, campaign, and generation run to produce your first persisted draft."
          />
        ) : (
          <div className="table">
            {posts.slice(0, 5).map((post) => (
              <div className="table-row" key={post.id}>
                <span className="channel">{post.channel.slice(0, 1)}</span>
                <div className="grow">
                  <strong>{post.title}</strong>
                  <small>{relativeTime(post.created_at)} · Risk score {post.risk_score}/100</small>
                </div>
                <Status value={post.status} />
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  );
}

function Agents({ agents, onCreate }: { agents: Agent[]; onCreate: () => void }) {
  return (
    <>
      <section className="page-intro">
        <p>Create focused agents with restricted channels and explicit operating instructions.</p>
        <button className="button primary" onClick={onCreate}>
          <Plus size={16} /> New agent
        </button>
      </section>

      {agents.length === 0 ? (
        <Empty
          icon={<Bot size={28} />}
          title="No agents yet"
          description="Create a content agent first. It will be usable immediately in a generation run."
        />
      ) : (
        <div className="card-grid">
          {agents.map((agent) => (
            <article className="entity-card" key={agent.id}>
              <div className="card-top">
                <span className="avatar">{agent.name[0]}</span>
                <Status value={agent.status} />
              </div>
              <h3>{agent.name}</h3>
              <p className="role">{agent.role}</p>
              <p>{agent.instructions}</p>
              <div className="tags">
                {agent.channels.map((channel) => (
                  <span key={channel}>{channel}</span>
                ))}
              </div>
            </article>
          ))}
        </div>
      )}
    </>
  );
}

function Campaigns({
  campaigns,
  onCreate,
}: {
  campaigns: Campaign[];
  onCreate: () => void;
}) {
  return (
    <>
      <section className="page-intro">
        <p>Campaigns give your agents an objective, audience, channel scope, and brand voice.</p>
        <button className="button primary" onClick={onCreate}>
          <Plus size={16} /> New campaign
        </button>
      </section>

      {campaigns.length === 0 ? (
        <Empty
          icon={<Megaphone size={28} />}
          title="No campaigns yet"
          description="Create one campaign before running an agent."
        />
      ) : (
        <div className="campaign-list">
          {campaigns.map((campaign) => (
            <article className="campaign-card" key={campaign.id}>
              <div className="campaign-stripe" />
              <div className="grow">
                <div className="split">
                  <Status value={campaign.status} />
                  <small>Created {relativeTime(campaign.created_at)}</small>
                </div>
                <h3>{campaign.name}</h3>
                <p>{campaign.objective}</p>
                <div className="tags">
                  {campaign.channels.map((channel) => (
                    <span key={channel}>{channel}</span>
                  ))}
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </>
  );
}

function ReviewQueue({
  posts,
  onRefresh,
  setError,
}: {
  posts: ContentPost[];
  onRefresh: () => Promise<void>;
  setError: (value: string) => void;
}) {
  const [working, setWorking] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  const action = async (
    postId: string,
    type: "approve" | "changes" | "publish",
  ) => {
    try {
      setWorking(postId);
      setError("");
      setMessage("");

      if (type === "approve") await api.approvePost(postId);
      if (type === "changes") await api.requestChanges(postId);
      if (type === "publish") {
        const result = await api.publishPost(postId);
        setMessage(result.message);
      }

      await onRefresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Action failed.");
    } finally {
      setWorking(null);
    }
  };

  return (
    <>
      <section className="page-intro">
        <p>
          Drafts require an explicit decision before publishing. Publishing calls your
          configured signed webhook or local simulation mode.
        </p>
        <span className="review-label">
          <ShieldCheck size={16} />
          Human authority enabled
        </span>
      </section>

      {message ? <div className="success-banner">{message}</div> : null}

      {posts.length === 0 ? (
        <Empty
          icon={<ShieldCheck size={28} />}
          title="Your queue is clear"
          description="Agent-generated content will appear here once a run completes."
        />
      ) : (
        <div className="review-list">
          {posts.map((post) => (
            <article className="review-card" key={post.id}>
              <div className="review-head">
                <span className="channel">{post.channel.slice(0, 1)}</span>
                <div className="grow">
                  <h3>{post.title}</h3>
                  <small>
                    {post.channel} · {relativeTime(post.created_at)} · risk {post.risk_score}/100
                  </small>
                </div>
                <Status value={post.status} />
              </div>

              <div className="post-body">
                {post.body}
                {post.hashtags.length ? (
                  <div className="hashtags">{post.hashtags.join(" ")}</div>
                ) : null}
              </div>

              {post.risk_flags.length ? (
                <div className="risk-flags">
                  <CircleAlert size={15} />
                  {post.risk_flags.join(" · ")}
                </div>
              ) : null}

              <div className="review-actions">
                {post.status === "in_review" ? (
                  <>
                    <button
                      className="button danger"
                      disabled={working === post.id}
                      onClick={() => void action(post.id, "changes")}
                    >
                      <X size={16} /> Request changes
                    </button>
                    <button
                      className="button primary"
                      disabled={working === post.id}
                      onClick={() => void action(post.id, "approve")}
                    >
                      <Check size={16} /> Approve
                    </button>
                  </>
                ) : null}

                {post.status === "approved" ? (
                  <button
                    className="button primary"
                    disabled={working === post.id}
                    onClick={() => void action(post.id, "publish")}
                  >
                    {working === post.id ? (
                      <LoaderCircle className="spin" size={16} />
                    ) : (
                      <Send size={16} />
                    )}
                    Publish now
                  </button>
                ) : null}

                {post.status === "published" ? (
                  <span className="published-note">
                    <Check size={16} /> Published {post.published_at ? relativeTime(post.published_at) : ""}
                  </span>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      )}
    </>
  );
}

function Audit({ events }: { events: AuditEvent[] }) {
  return (
    <section className="panel">
      <div className="section-head">
        <div>
          <p className="eyebrow">IMMUTABLE EVENT HISTORY</p>
          <h3>Audit trail</h3>
        </div>
      </div>

      {events.length === 0 ? (
        <Empty
          icon={<Activity size={28} />}
          title="No events yet"
          description="System, user, agent, approval, and publication events appear here."
        />
      ) : (
        <div className="audit-list">
          {events.map((event) => (
            <div className="audit-row" key={event.id}>
              <span className={`audit-dot ${event.actor_type}`} />
              <div className="grow">
                <strong>{event.action.replaceAll(".", " ")}</strong>
                <p>
                  {event.actor_type} · {event.resource_type} · {event.resource_id}
                </p>
              </div>
              <small>{relativeTime(event.created_at)}</small>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function RunStatus({ run, onClose }: { run: AgentRun; onClose: () => void }) {
  const done = run.status === "completed";
  const failed = run.status === "failed";

  return (
    <div className={`run-status ${failed ? "failed" : ""}`}>
      {done ? <Check size={18} /> : failed ? <CircleAlert size={18} /> : <LoaderCircle className="spin" size={18} />}
      <div className="grow">
        <strong>
          {done ? "Draft generated and sent to review" : failed ? "Agent run failed" : `Agent run ${run.status}`}
        </strong>
        <span>
          {failed
            ? run.error_message
            : `${run.channel} · ${run.topic} · ${run.provider}/${run.model}`}
        </span>
      </div>
      {(done || failed) && (
        <button className="icon-button" onClick={onClose}>
          <X size={17} />
        </button>
      )}
    </div>
  );
}

function Status({ value }: { value: string }) {
  return (
    <span className={`status ${value}`}>
      <i />
      {shortStatus(value)}
    </span>
  );
}

function Empty({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="empty">
      {icon}
      <h3>{title}</h3>
      <p>{description}</p>
    </div>
  );
}

function Modal({
  title,
  text,
  onClose,
  children,
}: {
  title: string;
  text: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="modal" onMouseDown={(event) => event.stopPropagation()}>
        <button className="icon-button close" onClick={onClose}>
          <X size={18} />
        </button>
        <p className="eyebrow">AGENTSOCIAL</p>
        <h2>{title}</h2>
        <p className="modal-text">{text}</p>
        {children}
      </section>
    </div>
  );
}

function AgentModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (payload: Omit<Agent, "id" | "status" | "created_at">) => Promise<void>;
}) {
  const [saving, setSaving] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);

    try {
      setSaving(true);
      await onCreated({
        name: String(form.get("name")),
        role: String(form.get("role")),
        instructions: String(form.get("instructions")),
        channels: String(form.get("channels"))
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title="Create a specialized agent"
      text="Narrow responsibilities and explicit instructions produce more predictable work."
      onClose={onClose}
    >
      <form className="form modal-form" onSubmit={submit}>
        <label>
          Agent name
          <input name="name" placeholder="Nova" minLength={2} required />
        </label>
        <label>
          Operating role
          <input name="role" placeholder="B2B Content Strategist" minLength={2} required />
        </label>
        <label>
          Instructions
          <textarea
            name="instructions"
            minLength={20}
            required
            defaultValue="Write credible thought leadership for technical B2B decision makers. Prefer concrete workflow insights over hype."
          />
        </label>
        <label>
          Approved channels
          <input name="channels" defaultValue="LinkedIn, X" required />
        </label>
        <button className="button primary full" disabled={saving}>
          {saving ? <LoaderCircle className="spin" size={17} /> : <Bot size={17} />}
          Create agent
        </button>
      </form>
    </Modal>
  );
}

function CampaignModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (payload: Omit<Campaign, "id" | "status" | "created_at">) => Promise<void>;
}) {
  const [saving, setSaving] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);

    try {
      setSaving(true);
      await onCreated({
        name: String(form.get("name")),
        objective: String(form.get("objective")),
        audience: String(form.get("audience")),
        brand_voice: String(form.get("brand_voice")),
        channels: String(form.get("channels"))
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title="Create a campaign"
      text="Campaign context is injected into each agent run and persisted with it."
      onClose={onClose}
    >
      <form className="form modal-form" onSubmit={submit}>
        <label>
          Campaign name
          <input name="name" placeholder="AI Agent Platform Launch" required />
        </label>
        <label>
          Objective
          <textarea
            name="objective"
            minLength={10}
            required
            defaultValue="Generate qualified conversations with B2B operators exploring AI agent workflows."
          />
        </label>
        <label>
          Target audience
          <input
            name="audience"
            defaultValue="Technical founders, engineering leaders, and B2B operations teams"
            required
          />
        </label>
        <label>
          Brand voice
          <input
            name="brand_voice"
            defaultValue="Direct, intelligent, practical, and anti-hype"
            required
          />
        </label>
        <label>
          Approved channels
          <input name="channels" defaultValue="LinkedIn, X" required />
        </label>
        <button className="button primary full" disabled={saving}>
          {saving ? <LoaderCircle className="spin" size={17} /> : <Megaphone size={17} />}
          Create campaign
        </button>
      </form>
    </Modal>
  );
}

function GenerateModal({
  agents,
  campaigns,
  onClose,
  onRun,
}: {
  agents: Agent[];
  campaigns: Campaign[];
  onClose: () => void;
  onRun: (payload: {
    agent_id: string;
    campaign_id: string;
    topic: string;
    channel: string;
  }) => Promise<void>;
}) {
  const [saving, setSaving] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);

    try {
      setSaving(true);
      await onRun({
        agent_id: String(form.get("agent_id")),
        campaign_id: String(form.get("campaign_id")),
        topic: String(form.get("topic")),
        channel: String(form.get("channel")),
      });
    } finally {
      setSaving(false);
    }
  };

  if (!agents.length || !campaigns.length) {
    return (
      <Modal
        title="Set up your workspace first"
        text="You need at least one agent and one campaign before you can execute a generation run."
        onClose={onClose}
      >
        <button className="button primary full" onClick={onClose}>
          Got it
        </button>
      </Modal>
    );
  }

  return (
    <Modal
      title="Start a real agent run"
      text="This queues a durable run, calls your configured provider, validates JSON output, and creates a reviewable draft."
      onClose={onClose}
    >
      <form className="form modal-form" onSubmit={submit}>
        <label>
          Agent
          <select name="agent_id" defaultValue={agents[0].id}>
            {agents.map((agent) => (
              <option value={agent.id} key={agent.id}>
                {agent.name} — {agent.role}
              </option>
            ))}
          </select>
        </label>
        <label>
          Campaign
          <select name="campaign_id" defaultValue={campaigns[0].id}>
            {campaigns.map((campaign) => (
              <option value={campaign.id} key={campaign.id}>
                {campaign.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Topic
          <textarea
            name="topic"
            minLength={5}
            required
            defaultValue="Why reviewable AI agents are better than autonomous content bots"
          />
        </label>
        <label>
          Channel
          <select name="channel" defaultValue="LinkedIn">
            <option>LinkedIn</option>
            <option>X</option>
            <option>Instagram</option>
          </select>
        </label>
        <button className="button primary full" disabled={saving}>
          {saving ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}
          Queue generation run
        </button>
      </form>
    </Modal>
  );
}