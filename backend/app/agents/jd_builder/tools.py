from elasticsearch import Elasticsearch
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.types import interrupt
from sqlalchemy import text
from app.core.postgres_db import PostgresSession
from elasticsearch import Elasticsearch

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

@tool
def search_internal_jds(query: str, team_key: str = None, level_code: str = None, year: int = None) -> str:
    """
    Search Nexus Health's internal historical job description corpus.
    Use this to find past JDs for a specific team and level — to understand
    how the role has been described before, how requirements have evolved
    over time, and to ground new JDs in the company's institutional voice.

    query: what to search for e.g. "ML engineer claims processing"
    team_key: optional — filter to a specific team e.g. "claims_ai", "clinical_ai_lab"
    level_code: optional — filter to a specific level e.g. "L4", "R3", "SEC5"
    year: optional — filter to a specific year e.g. 2021, 2022

    Use this tool when:
    - Drafting a JD and want to see what the last JD for this role looked like
    - Checking how a role's requirements have evolved over time
    - Needing to match Nexus Health's institutional voice and style
    - HR asks "what did we post last time for this role?"

    Do NOT use this for market comparison — use search_market_jds for that.
    """
    try:
        es = Elasticsearch("http://localhost:9200")

        # build the base query — BM25 full text search on description and job_title
        must_clauses = [
            {
                "multi_match": {
                    "query": query,
                    "fields": ["job_title", "description"],
                    "type": "best_fields"
                }
            }
        ]

        # build filter clauses — exact match on structured fields
        # filters don't affect relevance scoring — they just include/exclude
        filter_clauses = []

        if team_key:
            # keyword field — exact match
            filter_clauses.append({"term": {"team_key": team_key}})

        if level_code:
            # keyword field — exact match, uppercase for consistency
            filter_clauses.append({"term": {"level_code": level_code.upper()}})

        if year:
            # integer field — exact match
            filter_clauses.append({"term": {"year_posted": year}})

        # combine must (scoring) + filter (exact) in a bool query
        es_query = {
            "bool": {
                "must": must_clauses,
                "filter": filter_clauses
            }
        }

        response = es.search(
            index="internal_jds",
            query=es_query,
            size=3,  # return top 3 most relevant results
            source=["jd_id", "job_title", "team_key", "level_code", "year_posted", "description"]
        )

        hits = response["hits"]["hits"]

        # relevance threshold — ignore weak matches
        # same pattern as search_market_jds
        RELEVANCE_THRESHOLD = 3.0
        relevant_hits = [h for h in hits if h["_score"] > RELEVANCE_THRESHOLD]

        if not relevant_hits:
            return (
                "No sufficiently relevant internal JDs found for this query. "
                "This may be a new role type with no internal precedent. "
                "Proceed using team context from get_team_context() and "
                "market examples from search_market_jds()."
            )

        # format results for the agent
        results = []
        for hit in relevant_hits:
            source = hit["_source"]
            score = hit["_score"]

            results.append(
                f"JD: {source['job_title']} "
                f"(Team: {source['team_key']}, "
                f"Level: {source['level_code']}, "
                f"Year: {source['year_posted']}, "
                f"Relevance: {score:.1f})\n"
                f"{source['description'][:600]}..."
            )

        header = f"Found {len(relevant_hits)} relevant internal JD(s):\n\n"
        return header + "\n\n---\n\n".join(results)

    except Exception as e:
        return f"Error searching internal JDs: {str(e)}"

@tool
def draft_jd(team_key: str, level_code: str, additional_requirements: str = None) -> str:
    """
    Generate a complete, structured, sanitized external-facing JD for a
    specific Nexus Health team and level. Call this when the HR person has
    confirmed the team and level and is ready for a draft.

    This tool handles everything internally — do not pass data from other
    tool calls. Just pass the confirmed team_key and level_code.

    team_key: internal team identifier e.g. "claims_ai", "clinical_ai_lab"
    level_code: level code e.g. "L4", "R3", "SEC5"
    additional_requirements: any extra requirements HR explicitly stated
                             e.g. "make Kubernetes required, minimum 10 years"

    IMPORTANT: When this tool returns output, present it to the HR person
    EXACTLY as returned — word for word, no summarizing, no compressing,
    no reformatting. Add only one line before it:
    "Here is the draft — let me know if you would like any changes:"
    Then paste the complete output unchanged.
    """
    from langchain_openai import ChatOpenAI

    # ── Domain name mapping ───────────────────────────────────────────────────
    DOMAIN_NAMES = {
        "claims_ai":                      "Healthcare AI Engineering",
        "patient_data_platform":          "Healthcare Data Engineering",
        "clinical_decision_support_api":  "Clinical Platform Engineering",
        "member_portal":                  "Healthcare Product Engineering",
        "data_analytics_engineering":     "Analytics Engineering",
        "ml_platform":                    "Machine Learning Infrastructure",
        "clinical_ai_lab":                "Clinical AI Research",
        "epidemiology_population_health": "Population Health Research",
        "genomics_precision_medicine":    "Precision Medicine Research",
        "real_world_evidence":            "Health Economics Research",
        "hipaa_privacy":                  "Healthcare Privacy & Compliance",
        "regulatory_affairs":             "Healthcare Regulatory Affairs",
        "contracts_commercial":           "Commercial Legal",
        "ip_patents":                     "Intellectual Property",
        "clinical_program_operations":    "Clinical Operations",
        "payer_relations":                "Payer Strategy & Operations",
        "healthcare_data_operations":     "Healthcare Data Operations",
        "customer_success":               "Enterprise Customer Success",
        "application_security":           "Application Security Engineering",
        "infrastructure_security":        "Cloud Security Engineering",
        "iam":                            "Identity & Access Management",
        "soc":                            "Security Operations",
        "compliance_audit":               "Security Compliance & Audit",
    }

    # ── Fixed company description ─────────────────────────────────────────────
    NEXUS_DESCRIPTION = (
        "Nexus Health is a healthcare technology company that helps hospitals, "
        "health systems, and insurance payers make better clinical and operational "
        "decisions through data and AI. We build intelligent platforms connecting "
        "clinical workflows, healthcare data management, and analytics — serving "
        "organizations that collectively support millions of patients. Our teams "
        "work at the intersection of machine learning, healthcare data standards, "
        "and large-scale distributed systems, building products that directly "
        "impact how care is delivered and managed across the healthcare ecosystem."
    )

    es = Elasticsearch("http://localhost:9200")
    db = PostgresSession()

    try:
        # ── 1. Get team context from PostgreSQL ───────────────────────────────
        team_row = db.execute(text("""
            SELECT t.id, t.team_key, t.name as team_name,
                   t.description as team_description,
                   t.internal_collaborations,
                   t.external_collaborations,
                   d.name as department_name
            FROM teams t
            JOIN departments d ON d.id = t.department_id
            WHERE t.team_key = :team_key
        """), {"team_key": team_key}).fetchone()

        if not team_row:
            return (
                f"Error: team '{team_key}' not found in database. "
                f"Check the team_key and try again."
            )

        # ── 2. Get level definition from PostgreSQL ───────────────────────────
        level_row = db.execute(text("""
            SELECT l.level_code, l.level_title, l.scope,
                   l.experience_min, l.experience_max,
                   l.publications_required, l.publications_min,
                   l.manages_people, l.mentors_levels,
                   l.typical_background, l.autonomy
            FROM levels l
            JOIN departments d ON d.id = l.department_id
            WHERE l.level_code = :level_code
            AND d.name = :dept_name
        """), {
            "level_code": level_code.upper(),
            "dept_name": team_row.department_name
        }).fetchone()

        if not level_row:
            return (
                f"Error: level '{level_code}' not found for "
                f"department '{team_row.department_name}'. "
                f"Check the level_code and try again."
            )

        # ── 3. Get current technology stack from PostgreSQL ───────────────────
        # Temporal filter: technologies active as of 2024
        # adopted_year <= 2024 AND (deprecated_year IS NULL OR deprecated_year > 2024)
        techs = db.execute(text("""
            SELECT name, is_mandatory
            FROM team_technologies
            WHERE team_id = :team_id
            AND adopted_year <= 2024
            AND (deprecated_year IS NULL OR deprecated_year > 2024)
            ORDER BY is_mandatory DESC, name
        """), {"team_id": team_row.id}).fetchall()

        required_techs = [t.name for t in techs if t.is_mandatory]
        preferred_techs = [t.name for t in techs if not t.is_mandatory]

        # ── 4. Get active projects from PostgreSQL ────────────────────────────
        projects = db.execute(text("""
            SELECT name, description
            FROM team_projects
            WHERE team_id = :team_id
            AND (end_year IS NULL OR end_year >= 2024)
            ORDER BY start_year DESC
            LIMIT 3
        """), {"team_id": team_row.id}).fetchall()

        # ── 5. Get historical JD for style reference from Elasticsearch ───────
        # Retrieves the most relevant historical JD for this team and level
        # Used only for style matching — not for facts (facts come from PostgreSQL)
        style_reference = ""
        try:
            es_response = es.search(
                index="internal_jds",
                query={
                    "bool": {
                        "must": [{
                            "multi_match": {
                                "query": (
                                    f"{level_row.level_title} "
                                    f"{team_row.team_name}"
                                ),
                                "fields": ["job_title", "description"],
                                "type": "best_fields"
                            }
                        }],
                        "filter": [
                            {"term": {"team_key": team_key}},
                            {"term": {"level_code": level_code.upper()}}
                        ]
                    }
                },
                size=1,
                source=["description", "year_posted", "job_title"]
            )

            hits = es_response["hits"]["hits"]
            if hits and hits[0]["_score"] > 3.0:
                best = hits[0]["_source"]
                style_reference = f"""
═══ STYLE REFERENCE ═══
This is a historical JD written for this exact team and level ({best['year_posted']}).
Match its section structure, opening style, verb choices, and tone precisely.
Do NOT copy its content — the technology stack and projects may be outdated.
Use it purely as a style and voice reference.

{best['description']}
═══ END STYLE REFERENCE ═══
"""
        except Exception:
            # if Elasticsearch fails, proceed without style reference
            # the structured prompt still produces a good JD
            style_reference = ""

        # ── 6. Format all values for the prompt ──────────────────────────────

        # join technology lists into comma-separated strings
        required = ", ".join(required_techs) or "none specified"
        preferred = ", ".join(preferred_techs) if preferred_techs else None

        # mentors list from JSONB column
        mentors = (
            ", ".join(level_row.mentors_levels)
            if level_row.mentors_levels
            else "none"
        )

        # people management
        manages = (
            "Yes — this role has direct reports."
            if level_row.manages_people
            else "No — individual contributor role."
        )

        # experience range
        exp_max = f"-{level_row.experience_max}" if level_row.experience_max else "+"
        exp_range = f"{level_row.experience_min or 0}{exp_max} years"

        # market-facing title
        domain = DOMAIN_NAMES.get(team_key, team_row.team_name)
        job_title = f"{level_row.level_code} {level_row.level_title} — {domain}"

        # active projects text
        projects_text = "\n".join([
            f"  - {p.name}: {p.description}"
            for p in projects
        ]) if projects else "  - General team work aligned with department priorities"

        # publications section — only for research levels
        pub_section = ""
        if level_row.publications_required:
            pub_section = (
                f"\n- Minimum {level_row.publications_min} peer-reviewed "
                f"publications in a relevant domain — "
                f"this is a HARD requirement, not preferred"
            )

        # preferred technologies section
        preferred_section = ""
        if preferred:
            preferred_section = f"\nPreferred:\n- {preferred}"

        # additional HR requirements
        additional_note = ""
        if additional_requirements:
            additional_note = (
                f"\n\nADDITIONAL REQUIREMENTS FROM HR "
                f"(incorporate these exactly as stated):\n"
                f"{additional_requirements}"
            )

        # ── 7. Build the structured prompt ────────────────────────────────────
        prompt = f"""You are writing an external-facing job description for Nexus Health.
Follow all instructions precisely. Do not deviate from the structure or rules.
{style_reference}
═══ ROLE DETAILS ═══
Job Title: {job_title}
Level Code: {level_row.level_code}
Level Title: {level_row.level_title}
Domain: {domain}

═══ LEVEL DEFINITION ═══
Scope: {level_row.scope}
Experience required: {exp_range}
Autonomy: {level_row.autonomy}
Manages people: {manages}
Mentors: {mentors}
Typical background: {level_row.typical_background}

═══ TECHNOLOGY STACK ═══
Use ONLY these technologies — do not add, remove, or substitute anything.
Required: {required}{preferred_section}

═══ WORK CONTEXT ═══
Base responsibilities on these active projects.
Describe the TYPE of work — never name the projects directly.
{projects_text}
{additional_note}

═══ STRUCTURE — follow exactly, no deviation ═══

Section 1 — About Nexus Health
Use this exact text, word for word, do not change a single word:
{NEXUS_DESCRIPTION}

Section 2 — About the Role (3-4 sentences)
Describe what this person owns and leads.
Be specific about the TYPE of work — ML systems, data pipelines,
security architecture, clinical research, etc.
NEVER name:
  Internal projects → describe the category e.g. "real-time ML inference systems"
  Specific clients → say "hospital system integrations" or "healthcare clients"
  Internal systems → say "large-scale healthcare data processing systems"

Section 3 — What You Will Work On (exactly 4-5 bullets)
Each bullet must:
  - Start with an action verb: Design, Build, Own, Lead, Drive, Define, Maintain
  - Describe the category of work, not internal project names
  - Be grounded in the active projects above

Section 4 — What We Are Looking For
Required:
  - One bullet per required technology
  - Each bullet: [Technology Name]: one sentence explaining WHY it matters for this role
  - Final bullet: Experience: exactly "{exp_range}"
  {pub_section}

{f"Preferred:{chr(10)}  - One bullet per preferred technology with one-line description." if preferred else ""}

Section 5 — Your Scope at {level_row.level_code} (3-4 sentences)
Describe what this level means at Nexus Health in plain English:
  - What decisions this person owns
  - Their autonomy level
  - Who they mentor (if anyone)
  - Whether IC or people manager
Do NOT use the level code itself in the prose.

═══ RULES — non-negotiable ═══
1. NEVER name internal projects — describe category of work instead
2. NEVER name specific clients — say "hospital system integrations"
3. NEVER reveal internal system architecture — generalize
4. ONLY use technologies from the Required/Preferred lists — nothing else
5. Experience range must be exactly: {exp_range} — do not round or approximate
6. Publications: {"HARD requirement — minimum " + str(level_row.publications_min) + " peer-reviewed publications required. State this clearly." if level_row.publications_required else "Do not mention publications anywhere in the JD."}
7. Length: 400-500 words total
8. Tone: direct and professional — not marketing language, not generic corporate speak
9. About Nexus Health: use the exact text provided — never paraphrase or shorten it
10. Return ONLY the job description text — no preamble, no explanation, no commentary

Write the job description now."""

        # ── 8. Call GPT-4o to generate the JD ────────────────────────────────
        # temperature 0.4 — low enough to follow structure precisely,
        # high enough to produce natural prose (not robotic)
        llm = ChatOpenAI(model="gpt-4o", temperature=0.4)
        response = llm.invoke(prompt)
        generated_jd = response.content

        # ── 9. Return with clear delimiter ────────────────────────────────────
        # The delimiter tells the agent exactly how to handle this output:
        # present it verbatim, do not compress or reformat
        return f"""DRAFT JD READY — PRESENT THIS EXACTLY TO THE HR PERSON.
DO NOT SUMMARIZE, COMPRESS, OR REFORMAT. PASTE IT VERBATIM.
ADD ONLY ONE LINE BEFORE IT: "Here is the draft — let me know if you would like any changes:"

════════════════════════════════════════════════════════════════
{generated_jd}
════════════════════════════════════════════════════════════════"""

    except Exception as e:
        return f"Error generating JD: {str(e)}"

    finally:
        db.close()


@tool
def get_levels_for_team(team_key: str) -> str:
    """
    Get all level definitions for the department that a specific team 
    belongs to. Use this when HR uses a generic title like "Senior", 
    "Junior", "Principal", "Lead" — to find the correct internal level 
    options for that team's department.

    Always use this tool instead of query_company_database for level
    lookups — it guarantees the correct department is used by going
    through the team, not by assuming a department name.

    team_key: e.g. "claims_ai", "clinical_ai_lab", "compliance_audit"

    Returns all levels for this team's department with scope and 
    experience range — use these to present 2 appropriate options to HR.
    """
    db = PostgresSession()
    try:
        levels = db.execute(text("""
            SELECT l.level_code, l.level_title, l.scope,
                   l.experience_min, l.experience_max,
                   l.publications_required, l.publications_min,
                   l.manages_people, l.mentors_levels,
                   d.name as department_name
            FROM levels l
            JOIN departments d ON d.id = l.department_id
            JOIN teams t ON t.department_id = d.id
            WHERE t.team_key = :team_key
            ORDER BY l.level_code
        """), {"team_key": team_key}).fetchall()

        if not levels:
            return f"No levels found for team '{team_key}'. Check the team_key."

        dept_name = levels[0].department_name
        output = []
        output.append(f"Department: {dept_name}")
        output.append(f"Levels available:\n")

        for l in levels:
            exp_max = f"-{l.experience_max}" if l.experience_max else "+"
            exp_range = f"{l.experience_min or 0}{exp_max} years"

            pub_note = ""
            if l.publications_required:
                pub_note = f" | Min {l.publications_min} publications required"

            manages_note = " | Manages people" if l.manages_people else ""

            output.append(
                f"{l.level_code} — {l.level_title} "
                f"({exp_range}{pub_note}{manages_note})"
            )
            output.append(f"  Scope: {l.scope[:150]}")
            output.append("")

        return "\n".join(output)

    except Exception as e:
        return f"Error retrieving levels: {str(e)}"
    finally:
        db.close()


@tool
def find_team_by_project(project_keyword: str) -> str:
    """
    Find which Nexus Health team owns a project matching the keyword.
    Use this when HR mentions a project name but not a team name.
    Examples: "sepsis project", "fraud detection", "HITRUST audit",
              "real-time inference", "member portal redesign"

    project_keyword: one or two keywords from the project name
                     e.g. "sepsis", "fraud", "HITRUST", "inference"
    """
    db = PostgresSession()
    try:
        results = db.execute(text("""
            SELECT t.name as team_name, t.team_key,
                   d.name as department,
                   tp.name as project_name,
                   tp.description as project_description,
                   tp.status
            FROM team_projects tp
            JOIN teams t ON t.id = tp.team_id
            JOIN departments d ON d.id = t.department_id
            WHERE tp.name ILIKE :keyword
            OR tp.description ILIKE :keyword
            ORDER BY tp.status, t.name
        """), {"keyword": f"%{project_keyword}%"}).fetchall()

        if not results:
            return (
                f"No project found matching '{project_keyword}'. "
                f"Try a shorter keyword — e.g. 'sepsis' instead of "
                f"'sepsis project'."
            )

        output = []
        for r in results:
            output.append(
                f"Project: {r.project_name}\n"
                f"Team: {r.team_name} (team_key: {r.team_key})\n"
                f"Department: {r.department}\n"
                f"Status: {r.status}\n"
                f"Description: {r.project_description}"
            )
        return "\n\n".join(output)

    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        db.close()