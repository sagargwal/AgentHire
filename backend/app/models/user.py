from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    company = Column(String(255), nullable=True)

    # LinkedIn OAuth — populated later when recruiter connects their account in settings
    linkedin_access_token = Column(String(500), nullable=True)
    linkedin_refresh_token = Column(String(500), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())