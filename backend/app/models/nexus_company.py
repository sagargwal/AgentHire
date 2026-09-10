from sqlalchemy import (
    Column, Integer, String, Boolean, Text,
    ForeignKey, DateTime, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base

NexusBase = declarative_base()


class NexusCompany(NexusBase):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    industry = Column(String(255))
    founded_year = Column(Integer)
    description = Column(Text)
    headquarters = Column(String(255))
    size = Column(String(100))

    departments = relationship("NexusDepartment", back_populates="company")


class NexusDepartment(NexusBase):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    name = Column(String(255), nullable=False)
    leveling_track = Column(String(100))
    description = Column(Text)

    company = relationship("NexusCompany", back_populates="departments")
    levels = relationship("NexusLevel", back_populates="department")
    teams = relationship("NexusTeam", back_populates="department")


class NexusLevel(NexusBase):
    __tablename__ = "levels"

    id = Column(Integer, primary_key=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    level_code = Column(String(20), nullable=False)
    level_title = Column(String(255), nullable=False)
    scope = Column(Text)
    autonomy = Column(String(50))
    manages_people = Column(Boolean, default=False)
    mentors_levels = Column(JSONB)
    experience_min = Column(Integer)
    experience_max = Column(Integer)
    publications_required = Column(Boolean, default=False)
    publications_min = Column(Integer)
    typical_background = Column(Text)

    department = relationship("NexusDepartment", back_populates="levels")

    __table_args__ = (
        UniqueConstraint("department_id", "level_code", name="uq_dept_level"),
    )


class NexusTeam(NexusBase):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    team_key = Column(String(100), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    headcount = Column(Integer)
    founded_year = Column(Integer)
    internal_collaborations = Column(JSONB)
    external_collaborations = Column(JSONB)

    department = relationship("NexusDepartment", back_populates="teams")
    technologies = relationship("NexusTeamTechnology", back_populates="team")
    projects = relationship("NexusTeamProject", back_populates="team")


class NexusTeamTechnology(NexusBase):
    __tablename__ = "team_technologies"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    name = Column(String(255), nullable=False)
    category = Column(String(100))
    is_mandatory = Column(Boolean, default=True)
    adopted_year = Column(Integer)
    deprecated_year = Column(Integer)
    notes = Column(Text)

    team = relationship("NexusTeam", back_populates="technologies")


class NexusTeamProject(NexusBase):
    __tablename__ = "team_projects"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    name = Column(String(255), nullable=False)
    status = Column(String(50))
    start_year = Column(Integer)
    end_year = Column(Integer)
    description = Column(Text)

    team = relationship("NexusTeam", back_populates="projects")

class NexusHistoricalJD(NexusBase):
    __tablename__ = "historical_jds"

    id = Column(Integer, primary_key=True)
    jd_id = Column(String(255), nullable=False, unique=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    level_code = Column(String(20), nullable=False)
    year_posted = Column(Integer, nullable=False)
    job_title = Column(String(255), nullable=True)   # ← add this
    is_current = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())