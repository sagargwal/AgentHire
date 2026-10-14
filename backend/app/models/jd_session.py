from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base


class JDSession(Base):
    __tablename__ = "jd_sessions"

    session_id = Column(String(36), primary_key=True)

    # which user this session belongs to
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # when this session was created — useful for debugging and auditing
    created_at = Column(DateTime(timezone=True), server_default=func.now())
