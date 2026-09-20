# app/routers/careers.py

from fastapi import APIRouter, HTTPException
from app.core.postgres_db import PostgresSession
from app.models.nexus_company import PostedJD

# APIRouter groups related endpoints together
# prefix="/careers" means all routes here start with /careers
# tags=["careers"] groups them in the API docs at /docs
router = APIRouter(prefix="/careers", tags=["careers"])


@router.get("")
def list_careers():
    # Open a new database session (connection to PostgreSQL)
    db = PostgresSession()
    try:
        # Query the posted_jds table
        # .filter() → only get rows where is_active is True (not deleted/hidden)
        # .order_by() → newest jobs first
        # .all() → fetch all matching rows
        jobs = (
            db.query(PostedJD)
            .filter(PostedJD.is_active == True)
            .order_by(PostedJD.posted_at.desc())
            .all()
        )

        # Return a list of dicts — one per job
        # We do NOT return jd_text here because it is long
        # The listing page only needs the title, team, level, date
        return [
            {
                "id": job.id,
                "slug": job.slug,           # the URL-friendly identifier
                "job_title": job.job_title,
                "team_key": job.team_key,
                "level_code": job.level_code,
                "posted_at": job.posted_at,
                "is_active": job.is_active,
            }
            for job in jobs
        ]
    finally:
        # Always close the session whether the query succeeded or failed
        db.close()


@router.get("/{slug}")
def get_career(slug: str):
    # slug comes from the URL — e.g. /careers/claims-ai-l4-2026
    # FastAPI automatically extracts it and passes it as the slug argument
    db = PostgresSession()
    try:
        # Find the one job that matches this slug
        # .first() → returns one row or None if not found
        job = (
            db.query(PostedJD)
            .filter(PostedJD.slug == slug, PostedJD.is_active == True)
            .first()
        )

        # If no job found with this slug → return 404 error
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        # Return the full job including jd_text
        # The detail page needs the full JD to render all sections
        return {
            "id": job.id,
            "slug": job.slug,
            "job_title": job.job_title,
            "team_key": job.team_key,
            "level_code": job.level_code,
            "jd_text": job.jd_text,         # full JD text — only on detail page
            "posted_at": job.posted_at,
            "is_active": job.is_active,
        }
    finally:
        db.close()