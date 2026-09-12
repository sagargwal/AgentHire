from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.sql import func
from app.core.database import Base
from sqlalchemy.orm import relationship


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    company = Column(String(255), nullable=True)

    # ── NEW: Role and token tracking ──────────────────────────────────────

    # role determines what the user can do
    # 'admin' = unlimited access (you)
    # 'user'  = invited user, has token limit
    # 'demo'  = public demo account, shared token limit
    # server_default='user' means new accounts are 'user' by default
    role = Column(String(20), nullable=False, server_default='user')

    # how many tokens this user has consumed total across all sessions
    # starts at 0, increases after every agent turn
    tokens_used = Column(Integer, nullable=False, server_default='0')

    # maximum tokens this user is allowed to use
    # NULL means unlimited (used for admin accounts)
    # 50000 is the default for user and demo accounts
    token_limit = Column(Integer, nullable=True, server_default='50000')

    # ── END NEW ───────────────────────────────────────────────────────────

    # LinkedIn OAuth — populated later when recruiter connects their account
    linkedin_access_token = Column(String(500), nullable=True)
    linkedin_refresh_token = Column(String(500), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # one user can have many refresh tokens (one per device/session)
    refresh_tokens = relationship("RefreshToken", back_populates="user")