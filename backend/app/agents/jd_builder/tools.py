from elasticsearch import Elasticsearch
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.types import interrupt
from sqlalchemy import text
from app.core.postgres_db import PostgresSession

es_client = Elasticsearch("http://localhost:9200")
post_llm = ChatOpenAI(model="gpt-4o-mini")
interpreter_llm = ChatOpenAI(model="gpt-4o-mini")


def _extract_title(jd_draft: dict) -> str:
    return jd_draft.get("title") or jd_draft.get("job_title", "Untitled role")


def _extract_skills(jd_draft: dict) -> list:
    return jd_draft.get("skills") or jd_draft.get("required_skills", [])


def _extract_description(jd_draft: dict) -> str:
    return jd_draft.get("description") or jd_draft.get("job_description", "")


@tool
def search_market_jds(query: str, seniority: str = None) -> str:
    """Search for similar job descriptions in the market JD database.
    Use this when the recruiter's input is vague and you need real examples
    of how similar roles are typically described, including common skills
    and phrasing. Pass a short search phrase like 'backend engineer' or
    'senior data analyst'. Optionally pass seniority ('junior', 'mid', or
    'senior') if the recruiter specified a level, to narrow results."""
    try:
        if seniority:
            query_body = {
                "bool": {
                    "must": {
                        "multi_match": {
                            "query": query,
                            "fields": ["title", "description"],
                            "type": "best_fields"
                        }
                    },
                    "filter": {"term": {"seniority": seniority}}
                }
            }
        else:
            query_body = {
                "multi_match": {
                    "query": query,
                    "fields": ["title", "description"],
                    "type": "best_fields"
                }
            }

        response = es_client.search(
            index="jds",
            query=query_body,
            size=5
        )

        hits = response["hits"]["hits"]
        if not hits:
            return "No similar job descriptions found."

        RELEVANCE_THRESHOLD = 4.0
        relevant_hits = [h for h in hits if h["_score"] >= RELEVANCE_THRESHOLD]

        if not relevant_hits:
            return "No sufficiently relevant job descriptions found. Proceed using the recruiter's own description without market examples."

        results = []
        for hit in relevant_hits[:3]:
            source = hit["_source"]
            results.append(f"Title: {source['title']}\n{source['description'][:200]}...")

        return "\n\n".join(results)
    except Exception as e:
        print(f"search_market_jds error: {e}")
        return f"Search failed: {str(e)}. Proceed without market examples."


@tool
def finalize_jd(jd_draft: dict) -> str:
    """Call this when you believe the JD is ready to finalize. This will
    pause and ask the recruiter for confirmation in their own words before
    actually locking the draft. Pass the full jd_draft dict with keys:
    title, description, skills."""
    title = _extract_title(jd_draft)

    human_response = interrupt(
        f"Ready to finalize '{title}'. Reply with your decision — approve, "
        f"request changes, or reject — in your own words."
    )

    interpretation_prompt = f"""A recruiter was asked to approve finalizing a job description.
They replied: "{human_response}"

Classify their intent as exactly one of: APPROVED, REJECTED, or CHANGES_REQUESTED.
If CHANGES_REQUESTED, summarize the requested changes in one short sentence.

Respond in exactly this format:
INTENT: <APPROVED|REJECTED|CHANGES_REQUESTED>
DETAILS: <summary if changes requested, else "none">"""

    interpretation = interpreter_llm.invoke(interpretation_prompt).content

    if "INTENT: APPROVED" in interpretation:
        return f"JD finalized: {title}"
    elif "INTENT: REJECTED" in interpretation:
        return f"Recruiter declined to finalize '{title}'. Draft remains open for editing."
    else:
        return f"Recruiter requested changes before finalizing: {interpretation}"


@tool
def generate_platform_post(jd_draft: dict, platform: str) -> str:
    """Generate compelling, platform-appropriate post copy from a finalized
    JD, using an LLM to write real marketing language rather than a plain
    template. platform should be 'linkedin' or 'naukri'. Pass the full
    jd_draft dict with keys: title, description, skills."""
    title = _extract_title(jd_draft)
    description = _extract_description(jd_draft)
    skills = ", ".join(_extract_skills(jd_draft))

    prompt = f"""Write a short, engaging {platform} post to advertise this job opening.
Make it sound exciting but professional, use relevant emojis sparingly, and end with a call to action.

Title: {title}
Description: {description}
Key skills: {skills}"""

    response = post_llm.invoke(prompt)
    return response.content


@tool
def post_jd(jd_draft: dict, platform_post_text: str) -> str:
    """Call this after generate_platform_post has produced text and the JD
    is finalized. Pauses to confirm with the recruiter before simulating
    the publish. Pass the full jd_draft dict with keys: title, description,
    skills."""
    title = _extract_title(jd_draft)

    human_response = interrupt(
        f"Ready to post this to LinkedIn:\n\n{platform_post_text}\n\n"
        f"Reply to approve, ask for edits, or decline."
    )

    interpretation_prompt = f"""A recruiter was asked to approve publishing a LinkedIn post.
They replied: "{human_response}"

Classify their intent as exactly one of: APPROVED, REJECTED, or CHANGES_REQUESTED.
If CHANGES_REQUESTED, summarize the requested changes in one short sentence.

Respond in exactly this format:
INTENT: <APPROVED|REJECTED|CHANGES_REQUESTED>
DETAILS: <summary if changes requested, else "none">"""

    interpretation = interpreter_llm.invoke(interpretation_prompt).content

    if "INTENT: APPROVED" in interpretation:
        # TODO: replace with real LinkedIn Share API call
        return f"[SIMULATED] Posted to LinkedIn: {title}"
    elif "INTENT: REJECTED" in interpretation:
        return f"Recruiter declined to post '{title}'."
    else:
        return f"Recruiter requested changes before posting: {interpretation}"



@tool
def get_team_context(team_key: str, year: int = None) -> str:
    """
    Retrieve the technical profile of a specific Nexus Health team.
    Returns their current technology stack, active projects, and
    collaboration partners. Use this when drafting a JD for a role
    on a specific team — to ground the JD in what the team actually
    uses, not generic market descriptions.

    team_key: the team's identifier e.g. 'claims_ai', 'clinical_ai_lab',
              'ml_platform', 'patient_data_platform', 'member_portal',
              'data_analytics_engineering', 'epidemiology_population_health',
              'genomics_precision_medicine', 'real_world_evidence',
              'hipaa_privacy', 'regulatory_affairs', 'contracts_commercial',
              'ip_patents', 'clinical_program_operations', 'payer_relations',
              'healthcare_data_operations', 'customer_success',
              'application_security', 'infrastructure_security', 'iam',
              'soc', 'compliance_audit'

    year: optional — if provided, returns the stack as it existed
          in that year (useful for historical JD generation).
          If not provided, returns the current stack.
    """
    db = PostgresSession()
    try:
        # get team basic info
        team_query = text("""
            SELECT t.id, t.name, t.description, t.headcount, t.founded_year,
                   t.internal_collaborations, t.external_collaborations,
                   d.name as department_name, d.leveling_track
            FROM teams t
            JOIN departments d ON d.id = t.department_id
            WHERE t.team_key = :team_key
        """)
        team = db.execute(team_query, {"team_key": team_key}).fetchone()

        if not team:
            return f"No team found with key '{team_key}'. Check the team_key spelling."

        # determine year filter
        filter_year = year if year else 2024

        # get technologies valid for this year
        tech_query = text("""
            SELECT name, category, is_mandatory, adopted_year, 
                   deprecated_year, notes
            FROM team_technologies
            WHERE team_id = :team_id
            AND adopted_year <= :year
            AND (deprecated_year IS NULL OR deprecated_year > :year)
            ORDER BY is_mandatory DESC, name
        """)
        techs = db.execute(tech_query, {
            "team_id": team.id,
            "year": filter_year
        }).fetchall()

        # get projects active in this year
        proj_query = text("""
            SELECT name, status, start_year, end_year, description
            FROM team_projects
            WHERE team_id = :team_id
            AND start_year <= :year
            AND (end_year IS NULL OR end_year >= :year)
            ORDER BY status, start_year DESC
        """)
        projects = db.execute(proj_query, {
            "team_id": team.id,
            "year": filter_year
        }).fetchall()

        # format the response
        year_label = f"in {year}" if year else "currently"
        required = [t.name for t in techs if t.is_mandatory]
        preferred = [t.name for t in techs if not t.is_mandatory]
        active_projects = [p for p in projects if p.status == "active" or not p.end_year]
        completed_projects = [p for p in projects if p.status == "completed"]

        output = []
        output.append(f"TEAM: {team.name}")
        output.append(f"Department: {team.department_name} ({team.leveling_track} track)")
        output.append(f"Description: {team.description}")
        output.append(f"Headcount: {team.headcount}")
        output.append(f"Founded: {team.founded_year}")
        output.append("")
        output.append(f"TECHNOLOGY STACK ({year_label}):")
        output.append(f"  Required: {', '.join(required) if required else 'none listed'}")
        output.append(f"  Preferred: {', '.join(preferred) if preferred else 'none listed'}")
        output.append("")

        if active_projects:
            output.append("ACTIVE PROJECTS:")
            for p in active_projects:
                output.append(f"  - {p.name} (since {p.start_year}): {p.description}")

        if completed_projects:
            output.append("RECENTLY COMPLETED PROJECTS:")
            for p in completed_projects[:3]:  # top 3 most recent
                output.append(f"  - {p.name} ({p.start_year}-{p.end_year}): {p.description}")

        output.append("")
        output.append(f"INTERNAL COLLABORATIONS: {', '.join(team.internal_collaborations) if team.internal_collaborations else 'none'}")
        output.append(f"EXTERNAL COLLABORATIONS: {', '.join(team.external_collaborations) if team.external_collaborations else 'none'}")

        return "\n".join(output)

    except Exception as e:
        return f"Error retrieving team context: {str(e)}"
    finally:
        db.close()


@tool
def get_level(level_code: str, department_name: str) -> str:
    """
    Retrieve the exact level definition for a given level code at
    Nexus Health. Use this whenever an HR person mentions a specific
    level (L4, R3, SEC5, LA3, OA4 etc.) to get the precise scope,
    experience range, publication requirements, and what this level
    actually means at this company — not the generic industry convention.

    level_code: the level identifier e.g. 'L4', 'R3', 'SEC5', 'LA3', 'OA4'
    department_name: the department this level belongs to e.g.
                     'Technology', 'Health Sciences & Research',
                     'Web & Application Security', 'Legal & Compliance',
                     'Operations'
    """
    db = PostgresSession()
    try:
        query = text("""
            SELECT l.level_code, l.level_title, l.scope, l.autonomy,
                   l.manages_people, l.mentors_levels,
                   l.experience_min, l.experience_max,
                   l.publications_required, l.publications_min,
                   l.typical_background, d.name as department_name,
                   d.leveling_track
            FROM levels l
            JOIN departments d ON d.id = l.department_id
            WHERE l.level_code = :level_code
            AND d.name ILIKE :dept_name
        """)
        level = db.execute(query, {
            "level_code": level_code.upper(),
            "dept_name": f"%{department_name}%"
        }).fetchone()

        if not level:
            return (f"No level '{level_code}' found in department matching "
                    f"'{department_name}'. Check the level code and department name.")

        # format experience range
        exp_min = level.experience_min or 0
        exp_max = f"-{level.experience_max}" if level.experience_max else "+"
        exp_range = f"{exp_min}{exp_max} years"

        # format mentors
        mentors = ", ".join(level.mentors_levels) if level.mentors_levels else "none"

        output = []
        output.append(f"LEVEL: {level.level_code} — {level.level_title}")
        output.append(f"Department: {level.department_name} ({level.leveling_track} track)")
        output.append("")
        output.append(f"SCOPE: {level.scope}")
        output.append("")
        output.append(f"EXPERIENCE RANGE: {exp_range}")
        output.append(f"AUTONOMY: {level.autonomy}")
        output.append(f"MANAGES PEOPLE: {'Yes' if level.manages_people else 'No'}")
        output.append(f"MENTORS: {mentors}")
        output.append("")

        if level.publications_required:
            output.append(f"PUBLICATIONS: Required — minimum {level.publications_min} "
                         f"peer-reviewed publications (HARD requirement, not preferred)")
        else:
            output.append("PUBLICATIONS: Not required for this level")

        output.append("")
        output.append(f"TYPICAL BACKGROUND: {level.typical_background}")

        return "\n".join(output)

    except Exception as e:
        return f"Error retrieving level: {str(e)}"
    finally:
        db.close()


@tool
def query_company_database(sql: str) -> str:
    """
    Execute a read-only SQL query against the Nexus Health company
    knowledge database. Use this for any structured question about
    the company that get_team_context and get_level do not cover —
    comparisons across teams, historical analysis, collaboration
    patterns, project timelines, or any custom aggregation.

    The database schema:
    - companies (id, name, industry, founded_year, description)
    - departments (id, company_id, name, leveling_track, description)
    - levels (id, department_id, level_code, level_title, scope,
              autonomy, manages_people, mentors_levels JSONB,
              experience_min, experience_max, publications_required,
              publications_min, typical_background)
    - teams (id, department_id, team_key, name, description,
             headcount, founded_year,
             internal_collaborations JSONB,
             external_collaborations JSONB)
    - team_technologies (id, team_id, name, category, is_mandatory,
                        adopted_year, deprecated_year, notes)
    - team_projects (id, team_id, name, status, start_year,
                    end_year, description)

    TEMPORAL FILTERING for technology questions:
    WHERE adopted_year <= YEAR
    AND (deprecated_year IS NULL OR deprecated_year > YEAR)

    IMPORTANT: SELECT only. Never INSERT, UPDATE, DELETE, or DROP.
    """
    db = PostgresSession()
    try:
        # safety — only allow SELECT
        sql_clean = sql.strip().upper()
        if not sql_clean.startswith("SELECT"):
            return "Error: only SELECT queries are permitted in this tool."

        result = db.execute(text(sql))
        rows = result.fetchall()
        columns = list(result.keys())

        if not rows:
            return "Query executed successfully but returned no results."

        # cap at 50 rows to avoid flooding the context
        if len(rows) > 50:
            rows = rows[:50]
            truncated = True
        else:
            truncated = False

        output = []
        output.append(f"Columns: {columns}")
        output.append(f"Results ({len(rows)} rows{', truncated to 50' if truncated else ''}):")
        for row in rows:
            output.append(str(dict(zip(columns, row))))

        return "\n".join(output)

    except Exception as e:
        return f"Query error: {str(e)}"
    finally:
        db.close()