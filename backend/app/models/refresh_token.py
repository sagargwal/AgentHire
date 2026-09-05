from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True)

    # which user this token belongs to
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # SHA-256 hash of the raw token — raw token never stored
    token_hash = Column(String(255), nullable=False, unique=True)

    # when this refresh token expires (7 days from creation)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    # whether this token has been revoked (logout or rotation)
    revoked = Column(Boolean, default=False)

    # when this row was created — useful for debugging and auditing
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # relationship back to the user who owns this token
    user = relationship("User", back_populates="refresh_tokens")

