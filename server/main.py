from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import httpx
import jwt
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pwdlib import PasswordHash
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agent_social.db")
SECRET_KEY = os.getenv("SECRET_KEY", "development-secret-change-me")
CLIENT_ORIGIN = os.getenv("CLIENT_ORIGIN", "http://localhost:5173")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock").lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
PUBLISH_WEBHOOK_URL = os.getenv("PUBLISH_WEBHOOK_URL", "")
PUBLISH_WEBHOOK_SECRET = os.getenv("PUBLISH_WEBHOOK_SECRET", "")

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_HOURS = 24
password_hash = PasswordHash.recommended()
security = HTTPBearer()

engine_kwargs: dict[str, Any] = {"future": True}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: utcnow())

    users: Mapped[list["User"]] = relationship(back_populates="organization")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), default="owner")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: utcnow())

    organization: Mapped["Organization"] = relationship(back_populates="users")


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(150), nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    channels: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: utcnow())


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    audience: Mapped[str] = mapped_column(Text, nullable=False)
    brand_voice: Mapped[str] = mapped_column(Text, nullable=False)
    channels: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: utcnow())


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"))
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    provider: Mapped[str] = mapped_column(String(50), default="mock")
    model: Mapped[str] = mapped_column(String(120), default="mock-social-writer")
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: utcnow())


class ContentPost(Base):
    __tablename__ = "content_posts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"))
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"))
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(String(60), nullable=False)
    hashtags: Mapped[list[str]] = mapped_column(JSON, default=list)
    risk_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="in_review")
    approved_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    publish_response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: utcnow())


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    actor_type: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(60), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(40), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: utcnow())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def make_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:18]}"


def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_access_token(user: User) -> str:
    payload = {
        "sub": user.id,
        "org": user.organization_id,
        "role": user.role,
        "exp": utcnow() + timedelta(hours=ACCESS_TOKEN_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(db_session),
) -> User:
    try:
        payload = jwt.decode(
            credentials.credentials,
            SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
        )
        user = db.get(User, payload.get("sub"))
        if not user:
            raise ValueError("User no longer exists")
        return user
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
        )


def require_owner_or_editor(user: User) -> None:
    if user.role not in {"owner", "admin", "editor"}:
        raise HTTPException(status_code=403, detail="Insufficient permission.")


def owned_or_404(db: Session, model: Any, item_id: str, organization_id: str):
    item = db.scalar(
        select(model).where(model.id == item_id, model.organization_id == organization_id)
    )
    if not item:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return item


def audit(
    db: Session,
    organization_id: str,
    actor_type: str,
    actor_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    detail: dict[str, Any],
) -> None:
    db.add(
        AuditEvent(
            id=make_id("audit"),
            organization_id=organization_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail,
        )
    )


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterInput(Schema):
    name: str = Field(min_length=2, max_length=120)
    organization_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)


class LoginInput(Schema):
    email: EmailStr
    password: str = Field(min_length=1)


class UserOut(Schema):
    id: str
    name: str
    email: str
    role: str
    organization_id: str


class AuthOut(Schema):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class AgentCreate(Schema):
    name: str = Field(min_length=2, max_length=100)
    role: str = Field(min_length=2, max_length=150)
    instructions: str = Field(min_length=20, max_length=3000)
    channels: list[str] = Field(min_length=1, max_length=5)


class AgentOut(Schema):
    id: str
    name: str
    role: str
    instructions: str
    channels: list[str]
    status: str
    created_at: datetime


class CampaignCreate(Schema):
    name: str = Field(min_length=2, max_length=160)
    objective: str = Field(min_length=10, max_length=1500)
    audience: str = Field(min_length=5, max_length=1000)
    brand_voice: str = Field(min_length=5, max_length=1000)
    channels: list[str] = Field(min_length=1, max_length=5)


class CampaignOut(Schema):
    id: str
    name: str
    objective: str
    audience: str
    brand_voice: str
    channels: list[str]
    status: str
    created_at: datetime


class RunCreate(Schema):
    agent_id: str
    campaign_id: str
    topic: str = Field(min_length=5, max_length=500)
    channel: str = Field(min_length=2, max_length=60)


class RunOut(Schema):
    id: str
    agent_id: str
    campaign_id: str
    topic: str
    channel: str
    status: str
    provider: str
    model: str
    output_json: dict[str, Any] | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class ContentOut(Schema):
    id: str
    campaign_id: str
    agent_id: str
    agent_run_id: str
    title: str
    body: str
    channel: str
    hashtags: list[str]
    risk_flags: list[str]
    risk_score: int
    status: str
    approved_at: datetime | None
    published_at: datetime | None
    publish_response: dict[str, Any] | None
    created_at: datetime


class AuditOut(Schema):
    id: str
    actor_type: str
    action: str
    resource_type: str
    resource_id: str
    detail: dict[str, Any]
    created_at: datetime


class PublishOut(Schema):
    post: ContentOut
    message: str


def extract_json(text: str) -> dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
    candidate = fenced.group(1) if fenced else text.strip()
    return json.loads(candidate)


def validate_model_output(raw: dict[str, Any], topic: str) -> dict[str, Any]:
    title = str(raw.get("title", topic)).strip()[:240]
    body = str(raw.get("body", "")).strip()
    hashtags = raw.get("hashtags", [])
    risk_flags = raw.get("risk_flags", [])

    if not title or len(body) < 40:
        raise ValueError("The LLM returned incomplete post content.")

    if not isinstance(hashtags, list):
        hashtags = []
    if not isinstance(risk_flags, list):
        risk_flags = []

    clean_hashtags = [
        f"#{str(tag).strip().lstrip('#').replace(' ', '')}"
        for tag in hashtags[:8]
        if str(tag).strip()
    ]
    clean_flags = [str(flag).strip()[:140] for flag in risk_flags[:8] if str(flag).strip()]

    return {
        "title": title,
        "body": body,
        "hashtags": clean_hashtags,
        "risk_flags": clean_flags,
        "risk_score": min(100, len(clean_flags) * 15),
    }


def mock_generate(topic: str, campaign: Campaign, agent: Agent, channel: str) -> dict[str, Any]:
    body = (
        f"{topic}\n\n"
        f"The best social programs are not built around posting more. They are built "
        f"around turning real expertise into useful, repeatable conversations.\n\n"
        f"For {campaign.name}, that means a clear objective: {campaign.objective}\n\n"
        f"Our operating model is simple: specialized AI agents prepare the work, "
        f"brand and policy checks constrain it, and people approve every meaningful "
        f"external action before it is published.\n\n"
        f"What part of your content workflow would benefit most from that model?"
    )

    return {
        "title": topic[:240],
        "body": body,
        "hashtags": ["AIAgents", "B2BMarketing", "SocialMediaStrategy"],
        "risk_flags": [],
        "risk_score": 0,
    }


async def llm_generate(topic: str, campaign: Campaign, agent: Agent, channel: str) -> dict[str, Any]:
    if LLM_PROVIDER == "mock":
        return mock_generate(topic, campaign, agent, channel)

    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER is not mock.")

    system_prompt = """
You are a senior B2B social-media strategist. Return ONLY valid JSON.
Do not include markdown fences or commentary.

Required schema:
{
  "title": "short title",
  "body": "channel-specific post body",
  "hashtags": ["TagOne", "TagTwo"],
  "risk_flags": ["only actual policy, compliance, or certainty concerns"]
}

Rules:
- Make the post useful, specific, credible, and concise.
- Do not invent results, customers, product features, statistics, or testimonials.
- Do not make legal, medical, financial, or guaranteed-performance claims.
- Respect the supplied brand voice.
""".strip()

    user_prompt = f"""
Campaign: {campaign.name}
Objective: {campaign.objective}
Audience: {campaign.audience}
Brand voice: {campaign.brand_voice}
Agent role: {agent.role}
Agent instructions: {agent.instructions}
Channel: {channel}
Topic: {topic}
""".strip()

    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
        ],
    }

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            f"{OPENAI_BASE_URL}/responses",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    text = data.get("output_text", "")
    if not text:
        chunks = []
        for output in data.get("output", []):
            for content in output.get("content", []):
                if content.get("type") in {"output_text", "text"}:
                    chunks.append(content.get("text", ""))
        text = "\n".join(chunks)

    return validate_model_output(extract_json(text), topic)


async def execute_run(run_id: str) -> None:
    db = SessionLocal()

    try:
        run = db.get(AgentRun, run_id)
        if not run:
            return

        agent = db.get(Agent, run.agent_id)
        campaign = db.get(Campaign, run.campaign_id)

        if not agent or not campaign:
            run.status = "failed"
            run.error_message = "Agent or campaign no longer exists."
            run.completed_at = utcnow()
            db.commit()
            return

        run.status = "running"
        run.started_at = utcnow()
        db.commit()

        generated = await llm_generate(run.topic, campaign, agent, run.channel)
        generated = validate_model_output(generated, run.topic)

        run.output_json = generated
        run.status = "completed"
        run.completed_at = utcnow()

        post = ContentPost(
            id=make_id("post"),
            organization_id=run.organization_id,
            campaign_id=campaign.id,
            agent_id=agent.id,
            agent_run_id=run.id,
            title=generated["title"],
            body=generated["body"],
            channel=run.channel,
            hashtags=generated["hashtags"],
            risk_flags=generated["risk_flags"],
            risk_score=generated["risk_score"],
            status="in_review",
        )
        db.add(post)

        audit(
            db,
            run.organization_id,
            "agent",
            agent.id,
            "agent_run.completed",
            "content_post",
            post.id,
            {"run_id": run.id, "channel": run.channel, "risk_score": post.risk_score},
        )
        db.commit()

    except Exception as exc:
        db.rollback()
        run = db.get(AgentRun, run_id)
        if run:
            run.status = "failed"
            run.error_message = str(exc)[:2000]
            run.completed_at = utcnow()
            db.commit()
    finally:
        db.close()


async def publish_to_webhook(post: ContentPost, campaign: Campaign) -> dict[str, Any]:
    if not PUBLISH_WEBHOOK_URL:
        return {
            "mode": "simulated",
            "message": "No PUBLISH_WEBHOOK_URL configured. Post is marked published in local mode.",
        }

    event = {
        "event": "agentsocial.post.publish",
        "idempotency_key": post.id,
        "post_id": post.id,
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "channel": post.channel,
        "title": post.title,
        "body": post.body,
        "hashtags": post.hashtags,
        "published_at": utcnow().isoformat(),
    }

    payload = json.dumps(event, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(
        PUBLISH_WEBHOOK_SECRET.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            PUBLISH_WEBHOOK_URL,
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-AgentSocial-Signature": f"sha256={signature}",
                "X-AgentSocial-Event": "post.publish",
            },
        )
        response.raise_for_status()

        try:
            body: Any = response.json()
        except Exception:
            body = response.text[:1000]

    return {
        "mode": "webhook",
        "status_code": response.status_code,
        "response": body,
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="AgentSocial API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[CLIENT_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "provider": LLM_PROVIDER}


@app.post("/api/auth/register", response_model=AuthOut, status_code=201)
def register(payload: RegisterInput, db: Session = Depends(db_session)) -> AuthOut:
    existing = db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing:
        raise HTTPException(status_code=409, detail="An account already exists for that email.")

    organization = Organization(
        id=make_id("org"),
        name=payload.organization_name.strip(),
    )
    user = User(
        id=make_id("usr"),
        organization_id=organization.id,
        name=payload.name.strip(),
        email=payload.email.lower(),
        password_hash=password_hash.hash(payload.password),
        role="owner",
    )

    db.add_all([organization, user])
    audit(
        db,
        organization.id,
        "user",
        user.id,
        "organization.created",
        "organization",
        organization.id,
        {"name": organization.name},
    )
    db.commit()

    return AuthOut(access_token=create_access_token(user), user=user)


@app.post("/api/auth/login", response_model=AuthOut)
def login(payload: LoginInput, db: Session = Depends(db_session)) -> AuthOut:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not password_hash.verify(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    return AuthOut(access_token=create_access_token(user), user=user)


@app.get("/api/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@app.get("/api/agents", response_model=list[AgentOut])
def list_agents(user: User = Depends(get_current_user), db: Session = Depends(db_session)):
    return list(
        db.scalars(
            select(Agent)
            .where(Agent.organization_id == user.organization_id)
            .order_by(Agent.created_at.desc())
        )
    )


@app.post("/api/agents", response_model=AgentOut, status_code=201)
def create_agent(
    payload: AgentCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(db_session),
):
    require_owner_or_editor(user)

    agent = Agent(
        id=make_id("agent"),
        organization_id=user.organization_id,
        name=payload.name.strip(),
        role=payload.role.strip(),
        instructions=payload.instructions.strip(),
        channels=payload.channels,
    )
    db.add(agent)
    audit(
        db,
        user.organization_id,
        "user",
        user.id,
        "agent.created",
        "agent",
        agent.id,
        {"name": agent.name, "role": agent.role},
    )
    db.commit()
    db.refresh(agent)
    return agent


@app.get("/api/campaigns", response_model=list[CampaignOut])
def list_campaigns(user: User = Depends(get_current_user), db: Session = Depends(db_session)):
    return list(
        db.scalars(
            select(Campaign)
            .where(Campaign.organization_id == user.organization_id)
            .order_by(Campaign.created_at.desc())
        )
    )


@app.post("/api/campaigns", response_model=CampaignOut, status_code=201)
def create_campaign(
    payload: CampaignCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(db_session),
):
    require_owner_or_editor(user)

    campaign = Campaign(
        id=make_id("camp"),
        organization_id=user.organization_id,
        name=payload.name.strip(),
        objective=payload.objective.strip(),
        audience=payload.audience.strip(),
        brand_voice=payload.brand_voice.strip(),
        channels=payload.channels,
    )
    db.add(campaign)
    audit(
        db,
        user.organization_id,
        "user",
        user.id,
        "campaign.created",
        "campaign",
        campaign.id,
        {"name": campaign.name},
    )
    db.commit()
    db.refresh(campaign)
    return campaign


@app.post("/api/runs", response_model=RunOut, status_code=202)
async def create_run(
    payload: RunCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(db_session),
):
    require_owner_or_editor(user)

    agent = owned_or_404(db, Agent, payload.agent_id, user.organization_id)
    campaign = owned_or_404(db, Campaign, payload.campaign_id, user.organization_id)

    if payload.channel not in campaign.channels:
        raise HTTPException(
            status_code=400,
            detail="The selected channel is not enabled for this campaign.",
        )

    if payload.channel not in agent.channels:
        raise HTTPException(
            status_code=400,
            detail="The selected channel is not enabled for this agent.",
        )

    run = AgentRun(
        id=make_id("run"),
        organization_id=user.organization_id,
        agent_id=agent.id,
        campaign_id=campaign.id,
        topic=payload.topic.strip(),
        channel=payload.channel,
        status="queued",
        provider=LLM_PROVIDER,
        model=OPENAI_MODEL if LLM_PROVIDER != "mock" else "mock-social-writer",
        input_json={
            "topic": payload.topic.strip(),
            "channel": payload.channel,
            "campaign": campaign.name,
            "agent": agent.name,
        },
    )
    db.add(run)
    audit(
        db,
        user.organization_id,
        "user",
        user.id,
        "agent_run.queued",
        "agent_run",
        run.id,
        {"agent_id": agent.id, "campaign_id": campaign.id, "topic": run.topic},
    )
    db.commit()
    db.refresh(run)

    background_tasks.add_task(execute_run, run.id)
    return run


@app.get("/api/runs/{run_id}", response_model=RunOut)
def get_run(
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(db_session),
):
    return owned_or_404(db, AgentRun, run_id, user.organization_id)


@app.get("/api/posts", response_model=list[ContentOut])
def list_posts(
    status_filter: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(db_session),
):
    statement = (
        select(ContentPost)
        .where(ContentPost.organization_id == user.organization_id)
        .order_by(ContentPost.created_at.desc())
    )

    if status_filter:
        statement = statement.where(ContentPost.status == status_filter)

    return list(db.scalars(statement))


@app.post("/api/posts/{post_id}/approve", response_model=ContentOut)
def approve_post(
    post_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(db_session),
):
    require_owner_or_editor(user)
    post = owned_or_404(db, ContentPost, post_id, user.organization_id)

    if post.status != "in_review":
        raise HTTPException(status_code=409, detail="Only posts in review can be approved.")

    post.status = "approved"
    post.approved_by_user_id = user.id
    post.approved_at = utcnow()
    audit(
        db,
        user.organization_id,
        "user",
        user.id,
        "post.approved",
        "content_post",
        post.id,
        {"title": post.title},
    )
    db.commit()
    db.refresh(post)
    return post


@app.post("/api/posts/{post_id}/request-changes", response_model=ContentOut)
def request_changes(
    post_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(db_session),
):
    require_owner_or_editor(user)
    post = owned_or_404(db, ContentPost, post_id, user.organization_id)

    if post.status != "in_review":
        raise HTTPException(status_code=409, detail="Only posts in review can be returned.")

    post.status = "changes_requested"
    audit(
        db,
        user.organization_id,
        "user",
        user.id,
        "post.changes_requested",
        "content_post",
        post.id,
        {"title": post.title},
    )
    db.commit()
    db.refresh(post)
    return post


@app.post("/api/posts/{post_id}/publish", response_model=PublishOut)
async def publish_post(
    post_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(db_session),
):
    require_owner_or_editor(user)
    post = owned_or_404(db, ContentPost, post_id, user.organization_id)

    if post.status != "approved":
        raise HTTPException(status_code=409, detail="Only approved posts can be published.")

    campaign = owned_or_404(db, Campaign, post.campaign_id, user.organization_id)

    try:
        result = await publish_to_webhook(post, campaign)
        post.status = "published"
        post.published_at = utcnow()
        post.publish_response = result

        audit(
            db,
            user.organization_id,
            "user",
            user.id,
            "post.published",
            "content_post",
            post.id,
            result,
        )
        db.commit()
        db.refresh(post)

        return PublishOut(
            post=post,
            message=(
                "Published through webhook."
                if result["mode"] == "webhook"
                else "Published in local simulation mode. Configure PUBLISH_WEBHOOK_URL for a real outbound action."
            ),
        )
    except httpx.HTTPError as exc:
        post.status = "publish_failed"
        post.publish_response = {"error": str(exc)}
        audit(
            db,
            user.organization_id,
            "system",
            "publisher",
            "post.publish_failed",
            "content_post",
            post.id,
            {"error": str(exc)},
        )
        db.commit()
        raise HTTPException(status_code=502, detail=f"Publishing failed: {exc}") from exc


@app.get("/api/audit", response_model=list[AuditOut])
def list_audit(
    user: User = Depends(get_current_user),
    db: Session = Depends(db_session),
):
    return list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.organization_id == user.organization_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(50)
        )
    )


@app.get("/api/dashboard")
def dashboard(
    user: User = Depends(get_current_user),
    db: Session = Depends(db_session),
):
    org_id = user.organization_id

    active_campaigns = db.scalar(
        select(func.count()).select_from(Campaign).where(
            Campaign.organization_id == org_id,
            Campaign.status == "active",
        )
    ) or 0

    review_count = db.scalar(
        select(func.count()).select_from(ContentPost).where(
            ContentPost.organization_id == org_id,
            ContentPost.status == "in_review",
        )
    ) or 0

    approved_count = db.scalar(
        select(func.count()).select_from(ContentPost).where(
            ContentPost.organization_id == org_id,
            ContentPost.status == "approved",
        )
    ) or 0

    published_count = db.scalar(
        select(func.count()).select_from(ContentPost).where(
            ContentPost.organization_id == org_id,
            ContentPost.status == "published",
        )
    ) or 0

    total_runs = db.scalar(
        select(func.count()).select_from(AgentRun).where(
            AgentRun.organization_id == org_id
        )
    ) or 0

    return {
        "active_campaigns": active_campaigns,
        "awaiting_review": review_count,
        "approved_ready": approved_count,
        "published": published_count,
        "total_runs": total_runs,
        "provider": LLM_PROVIDER,
    }