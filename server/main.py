from __future__ import annotations

import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pwdlib import PasswordHash
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agent_social.db")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
CLIENT_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CLIENT_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

JWT_ALGORITHM = "HS256"
TOKEN_HOURS = 24
security = HTTPBearer()
password_hash = PasswordHash.recommended()

engine_kwargs: dict[str, Any] = {"future": True}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:18]}"


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), default="owner")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    handle: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(150), nullable=False)
    bio: Mapped[str] = mapped_column(Text, nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    channels: Mapped[list[str]] = mapped_column(JSON, default=list)
    autonomy_mode: Mapped[str] = mapped_column(String(40), default="approval_required")
    status: Mapped[str] = mapped_column(String(30), default="online")
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Follow(Base):
    __tablename__ = "follows"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    follower_agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    followed_agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SocialPost(Base):
    __tablename__ = "social_posts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    author_agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    post_type: Mapped[str] = mapped_column(String(40), default="insight")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="published")
    visibility: Mapped[str] = mapped_column(String(30), default="network")
    source: Mapped[str] = mapped_column(String(30), default="agent")
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Reaction(Base):
    __tablename__ = "reactions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    post_id: Mapped[str] = mapped_column(ForeignKey("social_posts.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    reaction_type: Mapped[str] = mapped_column(String(30), default="helpful")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    post_id: Mapped[str] = mapped_column(ForeignKey("social_posts.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(30), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_token(user: User) -> str:
    return jwt.encode(
        {
            "sub": user.id,
            "org": user.organization_id,
            "exp": now() + timedelta(hours=TOKEN_HOURS),
        },
        SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )


def current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user = db.get(User, payload.get("sub"))
        if not user:
            raise ValueError()
        return user
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired access token.")


def owned_agent(db: Session, agent_id: str, user: User) -> Agent:
    agent = db.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.organization_id == user.organization_id,
        )
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")
    return agent


def audit(
    db: Session,
    user: User,
    action: str,
    resource_id: str,
    resource_type: str,
    detail: dict[str, Any],
):
    db.add(
        AuditEvent(
            id=new_id("audit"),
            organization_id=user.organization_id,
            actor_id=user.id,
            actor_type="user",
            action=action,
            resource_id=resource_id,
            resource_type=resource_type,
            detail=detail,
        )
    )


class SocketManager:
    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.connections:
            self.connections.remove(websocket)

    async def broadcast(self, event_type: str, payload: dict[str, Any]):
        message = json.dumps({"type": event_type, "payload": payload}, default=str)
        dead: list[WebSocket] = []

        for socket in self.connections:
            try:
                await socket.send_text(message)
            except Exception:
                dead.append(socket)

        for socket in dead:
            self.disconnect(socket)


sockets = SocketManager()


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterInput(Schema):
    name: str = Field(min_length=2, max_length=120)
    organization_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)


class LoginInput(Schema):
    email: EmailStr
    password: str


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
    handle: str = Field(min_length=3, max_length=50)
    role: str = Field(min_length=2, max_length=150)
    bio: str = Field(min_length=20, max_length=1500)
    capabilities: list[str] = Field(min_length=1, max_length=10)
    channels: list[str] = Field(min_length=1, max_length=5)
    autonomy_mode: str = "approval_required"
    is_public: bool = True


class AgentOut(Schema):
    id: str
    organization_id: str
    name: str
    handle: str
    role: str
    bio: str
    capabilities: list[str]
    channels: list[str]
    autonomy_mode: str
    status: str
    is_public: bool
    created_at: datetime
    followers: int = 0
    following: int = 0


class AgentStatusInput(Schema):
    status: str = Field(pattern="^(online|thinking|paused|offline)$")


class PostCreate(Schema):
    author_agent_id: str
    post_type: str = Field(pattern="^(insight|question|collaboration_request|capability_offer|project_update|research_summary|opportunity)$")
    body: str = Field(min_length=10, max_length=4000)
    visibility: str = Field(default="network", pattern="^(network|public|private)$")


class PostOut(Schema):
    id: str
    author_agent_id: str
    author_name: str
    author_handle: str
    author_role: str
    post_type: str
    body: str
    status: str
    visibility: str
    source: str
    provenance: dict[str, Any]
    created_at: datetime
    reaction_count: int
    comment_count: int
    viewer_reaction: str | None


class ReactionInput(Schema):
    reaction_type: str = Field(pattern="^(helpful|insightful|interesting|support)$")


class CommentInput(Schema):
    body: str = Field(min_length=1, max_length=1500)


class CommentOut(Schema):
    id: str
    post_id: str
    user_name: str
    body: str
    created_at: datetime


class DashboardOut(Schema):
    owned_agents: int
    online_agents: int
    drafts_waiting: int
    published_posts: int
    total_followers: int


def agent_out(db: Session, agent: Agent) -> AgentOut:
    followers = db.scalar(
        select(func.count()).select_from(Follow).where(Follow.followed_agent_id == agent.id)
    ) or 0
    following = db.scalar(
        select(func.count()).select_from(Follow).where(Follow.follower_agent_id == agent.id)
    ) or 0

    return AgentOut(
        id=agent.id,
        organization_id=agent.organization_id,
        name=agent.name,
        handle=agent.handle,
        role=agent.role,
        bio=agent.bio,
        capabilities=agent.capabilities,
        channels=agent.channels,
        autonomy_mode=agent.autonomy_mode,
        status=agent.status,
        is_public=agent.is_public,
        created_at=agent.created_at,
        followers=followers,
        following=following,
    )


def post_out(db: Session, post: SocialPost, viewer_id: str | None) -> PostOut:
    author = db.get(Agent, post.author_agent_id)
    reaction_count = db.scalar(
        select(func.count()).select_from(Reaction).where(Reaction.post_id == post.id)
    ) or 0
    comment_count = db.scalar(
        select(func.count()).select_from(Comment).where(Comment.post_id == post.id)
    ) or 0

    viewer_reaction = None
    if viewer_id:
        reaction = db.scalar(
            select(Reaction).where(
                Reaction.post_id == post.id,
                Reaction.user_id == viewer_id,
            )
        )
        viewer_reaction = reaction.reaction_type if reaction else None

    return PostOut(
        id=post.id,
        author_agent_id=post.author_agent_id,
        author_name=author.name if author else "Unknown Agent",
        author_handle=author.handle if author else "unknown",
        author_role=author.role if author else "Unknown role",
        post_type=post.post_type,
        body=post.body,
        status=post.status,
        visibility=post.visibility,
        source=post.source,
        provenance=post.provenance,
        created_at=post.created_at,
        reaction_count=reaction_count,
        comment_count=comment_count,
        viewer_reaction=viewer_reaction,
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="AgentSocial", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CLIENT_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/auth/register", response_model=AuthOut, status_code=201)
def register(payload: RegisterInput, db: Session = Depends(get_db)):
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account already exists for that email.")

    organization = Organization(id=new_id("org"), name=payload.organization_name.strip())
    user = User(
        id=new_id("user"),
        organization_id=organization.id,
        name=payload.name.strip(),
        email=email,
        password_hash=password_hash.hash(payload.password),
        role="owner",
    )
    db.add_all([organization, user])
    db.commit()

    return AuthOut(access_token=create_token(user), user=user)


@app.post("/api/auth/login", response_model=AuthOut)
def login(payload: LoginInput, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not password_hash.verify(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    return AuthOut(access_token=create_token(user), user=user)


@app.get("/api/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@app.get("/api/dashboard", response_model=DashboardOut)
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    agents = list(
        db.scalars(select(Agent).where(Agent.organization_id == user.organization_id))
    )
    agent_ids = [agent.id for agent in agents]

    return DashboardOut(
        owned_agents=len(agents),
        online_agents=sum(1 for agent in agents if agent.status in {"online", "thinking"}),
        drafts_waiting=db.scalar(
            select(func.count()).select_from(SocialPost).where(
                SocialPost.organization_id == user.organization_id,
                SocialPost.status == "in_review",
            )
        ) or 0,
        published_posts=db.scalar(
            select(func.count()).select_from(SocialPost).where(
                SocialPost.organization_id == user.organization_id,
                SocialPost.status == "published",
            )
        ) or 0,
        total_followers=db.scalar(
            select(func.count()).select_from(Follow).where(
                Follow.followed_agent_id.in_(agent_ids or ["none"])
            )
        ) or 0,
    )


@app.get("/api/agents", response_model=list[AgentOut])
def list_agents(
    mine_only: bool = False,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    statement = select(Agent).order_by(Agent.created_at.desc())

    if mine_only:
        statement = statement.where(Agent.organization_id == user.organization_id)
    else:
        statement = statement.where(
            (Agent.is_public == True) | (Agent.organization_id == user.organization_id)
        )

    return [agent_out(db, agent) for agent in db.scalars(statement)]


@app.post("/api/agents", response_model=AgentOut, status_code=201)
async def create_agent(
    payload: AgentCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    handle = payload.handle.lower().replace("@", "").replace(" ", "-")

    if db.scalar(select(Agent).where(Agent.handle == handle)):
        raise HTTPException(status_code=409, detail="That agent handle is already taken.")

    agent = Agent(
        id=new_id("agent"),
        organization_id=user.organization_id,
        name=payload.name.strip(),
        handle=handle,
        role=payload.role.strip(),
        bio=payload.bio.strip(),
        capabilities=payload.capabilities,
        channels=payload.channels,
        autonomy_mode=payload.autonomy_mode,
        is_public=payload.is_public,
    )
    db.add(agent)
    audit(db, user, "agent.created", agent.id, "agent", {"name": agent.name})
    db.commit()
    db.refresh(agent)

    response = agent_out(db, agent)
    await sockets.broadcast("agent.created", response.model_dump(mode="json"))
    return response


@app.patch("/api/agents/{agent_id}/status", response_model=AgentOut)
async def update_agent_status(
    agent_id: str,
    payload: AgentStatusInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    agent = owned_agent(db, agent_id, user)
    agent.status = payload.status
    audit(db, user, "agent.status_changed", agent.id, "agent", {"status": agent.status})
    db.commit()
    db.refresh(agent)

    response = agent_out(db, agent)
    await sockets.broadcast("agent.status.changed", response.model_dump(mode="json"))
    return response


@app.post("/api/agents/{agent_id}/follow")
async def follow_agent(
    agent_id: str,
    follower_agent_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    follower = owned_agent(db, follower_agent_id, user)
    followed = db.get(Agent, agent_id)

    if not followed or not followed.is_public:
        raise HTTPException(status_code=404, detail="Public agent not found.")

    if follower.id == followed.id:
        raise HTTPException(status_code=400, detail="An agent cannot follow itself.")

    exists = db.scalar(
        select(Follow).where(
            Follow.follower_agent_id == follower.id,
            Follow.followed_agent_id == followed.id,
        )
    )
    if exists:
        return {"following": True}

    db.add(
        Follow(
            id=new_id("follow"),
            follower_agent_id=follower.id,
            followed_agent_id=followed.id,
        )
    )
    audit(
        db,
        user,
        "agent.followed",
        followed.id,
        "agent",
        {"follower_agent_id": follower.id},
    )
    db.commit()

    await sockets.broadcast(
        "agent.followed",
        {"follower_agent_id": follower.id, "followed_agent_id": followed.id},
    )
    return {"following": True}


@app.post("/api/posts", response_model=PostOut, status_code=201)
async def create_post(
    payload: PostCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    agent = owned_agent(db, payload.author_agent_id, user)

    if agent.status == "paused":
        raise HTTPException(status_code=409, detail="This agent is paused.")

    post_status = (
        "published"
        if agent.autonomy_mode == "policy_autonomous"
        else "in_review"
    )

    post = SocialPost(
        id=new_id("post"),
        author_agent_id=agent.id,
        organization_id=user.organization_id,
        post_type=payload.post_type,
        body=payload.body.strip(),
        status=post_status,
        visibility=payload.visibility,
        source="agent",
        provenance={
            "autonomy_mode": agent.autonomy_mode,
            "owner_organization_id": user.organization_id,
            "human_approved": False,
        },
    )
    db.add(post)
    audit(
        db,
        user,
        "post.created",
        post.id,
        "social_post",
        {"author_agent_id": agent.id, "status": post_status},
    )
    db.commit()
    db.refresh(post)

    response = post_out(db, post, user.id)
    await sockets.broadcast("feed.post.created", response.model_dump(mode="json"))
    return response


@app.post("/api/posts/{post_id}/approve", response_model=PostOut)
async def approve_post(
    post_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    post = db.scalar(
        select(SocialPost).where(
            SocialPost.id == post_id,
            SocialPost.organization_id == user.organization_id,
        )
    )
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")

    if post.status != "in_review":
        raise HTTPException(status_code=409, detail="Only review posts can be approved.")

    post.status = "published"
    post.provenance = {**post.provenance, "human_approved": True, "approved_by": user.id}
    audit(db, user, "post.approved", post.id, "social_post", {})
    db.commit()
    db.refresh(post)

    response = post_out(db, post, user.id)
    await sockets.broadcast("feed.post.published", response.model_dump(mode="json"))
    return response


@app.get("/api/feed", response_model=list[PostOut])
def feed(
    mode: str = "network",
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    statement = (
        select(SocialPost)
        .where(SocialPost.status == "published")
        .order_by(SocialPost.created_at.desc())
        .limit(100)
    )

    if mode == "mine":
        statement = statement.where(SocialPost.organization_id == user.organization_id)

    posts = list(db.scalars(statement))
    return [post_out(db, post, user.id) for post in posts]


@app.get("/api/posts/review", response_model=list[PostOut])
def review_posts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    posts = list(
        db.scalars(
            select(SocialPost)
            .where(
                SocialPost.organization_id == user.organization_id,
                SocialPost.status == "in_review",
            )
            .order_by(SocialPost.created_at.desc())
        )
    )
    return [post_out(db, post, user.id) for post in posts]


@app.post("/api/posts/{post_id}/reactions", response_model=PostOut)
async def react(
    post_id: str,
    payload: ReactionInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    post = db.get(SocialPost, post_id)
    if not post or post.status != "published":
        raise HTTPException(status_code=404, detail="Published post not found.")

    reaction = db.scalar(
        select(Reaction).where(
            Reaction.post_id == post.id,
            Reaction.user_id == user.id,
        )
    )

    if reaction:
        reaction.reaction_type = payload.reaction_type
    else:
        db.add(
            Reaction(
                id=new_id("reaction"),
                post_id=post.id,
                user_id=user.id,
                reaction_type=payload.reaction_type,
            )
        )

    db.commit()
    response = post_out(db, post, user.id)
    await sockets.broadcast("feed.post.reacted", response.model_dump(mode="json"))
    return response


@app.delete("/api/posts/{post_id}/reactions", response_model=PostOut)
async def remove_reaction(
    post_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    post = db.get(SocialPost, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")

    reaction = db.scalar(
        select(Reaction).where(
            Reaction.post_id == post.id,
            Reaction.user_id == user.id,
        )
    )

    if reaction:
        db.delete(reaction)
        db.commit()

    response = post_out(db, post, user.id)
    await sockets.broadcast("feed.post.reacted", response.model_dump(mode="json"))
    return response


@app.get("/api/posts/{post_id}/comments", response_model=list[CommentOut])
def comments(post_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    post = db.get(SocialPost, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")

    rows = list(
        db.scalars(
            select(Comment)
            .where(Comment.post_id == post_id)
            .order_by(Comment.created_at.asc())
        )
    )

    return [
        CommentOut(
            id=row.id,
            post_id=row.post_id,
            user_name=(db.get(User, row.user_id).name if db.get(User, row.user_id) else "Unknown"),
            body=row.body,
            created_at=row.created_at,
        )
        for row in rows
    ]


@app.post("/api/posts/{post_id}/comments", response_model=CommentOut, status_code=201)
async def add_comment(
    post_id: str,
    payload: CommentInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    post = db.get(SocialPost, post_id)
    if not post or post.status != "published":
        raise HTTPException(status_code=404, detail="Published post not found.")

    comment = Comment(
        id=new_id("comment"),
        post_id=post.id,
        user_id=user.id,
        body=payload.body.strip(),
    )
    db.add(comment)
    audit(db, user, "comment.created", comment.id, "comment", {"post_id": post.id})
    db.commit()
    db.refresh(comment)

    response = CommentOut(
        id=comment.id,
        post_id=comment.post_id,
        user_name=user.name,
        body=comment.body,
        created_at=comment.created_at,
    )

    await sockets.broadcast("feed.comment.created", response.model_dump(mode="json"))
    return response


@app.get("/api/audit")
def audit_log(user: User = Depends(current_user), db: Session = Depends(get_db)):
    events = list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.organization_id == user.organization_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(100)
        )
    )

    return [
        {
            "id": event.id,
            "action": event.action,
            "resource_id": event.resource_id,
            "resource_type": event.resource_type,
            "detail": event.detail,
            "created_at": event.created_at,
        }
        for event in events
    ]


@app.websocket("/ws/social")
async def social_socket(websocket: WebSocket):
    token = websocket.query_params.get("token")

    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await sockets.connect(websocket)

    try:
        await websocket.send_json({"type": "connected", "payload": {"message": "Live feed connected"}})

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        sockets.disconnect(websocket)