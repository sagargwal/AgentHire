import json
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from openai import OpenAI
from elasticsearch import Elasticsearch

load_dotenv()

# ─── Connections ──────────────────────────────────────────────────────────────

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
es = Elasticsearch("http://localhost:9200")

POSTGRES_URL = "postgresql+psycopg2://nexus_user:nexus_pass@localhost:5432/nexus_health"
engine = create_engine(POSTGRES_URL)
Session = sessionmaker(bind=engine)

YEARS = [2019, 2020, 2021, 2022, 2023, 2024]
BATCH_INPUT_FILE = "jd_batch_input.jsonl"
BATCH_OUTPUT_FILE = "jd_batch_output.jsonl"
COMBINATIONS_FILE = "combinations.json"

# ─── Domain name mapping ──────────────────────────────────────────────────────
# Maps internal team_key to market-facing domain name used in JD titles
# Format: "L4 Staff Software Engineer — {DOMAIN_NAME}"

DOMAIN_NAMES = {
    # Technology
    "claims_ai":                    "Healthcare AI Engineering",
    "patient_data_platform":        "Healthcare Data Engineering",
    "clinical_decision_support_api":"Clinical Platform Engineering",
    "member_portal":                "Healthcare Product Engineering",
    "data_analytics_engineering":   "Analytics Engineering",
    "ml_platform":                  "Machine Learning Infrastructure",
    # Health Sciences
    "clinical_ai_lab":              "Clinical AI Research",
    "epidemiology_population_health":"Population Health Research",
    "genomics_precision_medicine":  "Precision Medicine Research",
    "real_world_evidence":          "Health Economics Research",
    # Legal
    "hipaa_privacy":                "Healthcare Privacy & Compliance",
    "regulatory_affairs":           "Healthcare Regulatory Affairs",
    "contracts_commercial":         "Commercial Legal",
    "ip_patents":                   "Intellectual Property",
    # Operations
    "clinical_program_operations":  "Clinical Operations",
    "payer_relations":              "Payer Strategy & Operations",
    "healthcare_data_operations":   "Healthcare Data Operations",
    "customer_success":             "Enterprise Customer Success",
    # Security
    "application_security":         "Application Security Engineering",
    "infrastructure_security":      "Cloud Security Engineering",
    "iam":                          "Identity & Access Management",
    "soc":                          "Security Operations",
    "compliance_audit":             "Security Compliance & Audit",
}

NEXUS_HEALTH_DESCRIPTION = """Nexus Health is a healthcare technology company that helps hospitals, \
health systems, and insurance payers make better clinical and operational decisions through data \
and AI. We build intelligent platforms connecting clinical workflows, healthcare data management, \
and analytics — serving organizations that collectively support millions of patients. Our teams \
work at the intersection of machine learning, healthcare data standards, and large-scale \
distributed systems, building products that directly impact how care is delivered and managed \
across the healthcare ecosystem."""


# ─── Step 1: Fetch all combinations ──────────────────────────────────────────

def get_all_combinations():
    db = Session()
    combinations = []

    try:
        teams = db.execute(text("""
            SELECT t.id, t.team_key, t.name as team_name,
                   t.description as team_description,
                   t.internal_collaborations,
                   t.external_collaborations,
                   d.name as department_name,
                   d.leveling_track
            FROM teams t
            JOIN departments d ON d.id = t.department_id
            ORDER BY d.name, t.name
        """)).fetchall()

        for team in teams:
            levels = db.execute(text("""
                SELECT l.level_code, l.level_title, l.scope,
                       l.experience_min, l.experience_max,
                       l.publications_required, l.publications_min,
                       l.manages_people, l.mentors_levels,
                       l.typical_background, l.autonomy
                FROM levels l
                JOIN departments d ON d.id = l.department_id
                WHERE d.name = :dept_name
                ORDER BY l.level_code
            """), {"dept_name": team.department_name}).fetchall()

            for level in levels:
                for year in YEARS:
                    techs = db.execute(text("""
                        SELECT name, is_mandatory
                        FROM team_technologies
                        WHERE team_id = :team_id
                        AND adopted_year <= :year
                        AND (deprecated_year IS NULL OR deprecated_year > :year)
                        ORDER BY is_mandatory DESC, name
                    """), {"team_id": team.id, "year": year}).fetchall()

                    if not techs:
                        continue

                    projects = db.execute(text("""
                        SELECT name, description
                        FROM team_projects
                        WHERE team_id = :team_id
                        AND start_year <= :year
                        AND (end_year IS NULL OR end_year >= :year)
                        ORDER BY start_year DESC
                        LIMIT 3
                    """), {"team_id": team.id, "year": year}).fetchall()

                    required = [t.name for t in techs if t.is_mandatory]
                    preferred = [t.name for t in techs if not t.is_mandatory]

                    exp_max = f"-{level.experience_max}" if level.experience_max else "+"
                    exp_range = f"{level.experience_min or 0}{exp_max} years"

                    # build market-facing job title
                    domain = DOMAIN_NAMES.get(team.team_key, team.team_name)
                    job_title = f"{level.level_code} {level.level_title} — {domain}"
                    # example: "L4 Staff Engineer — Healthcare AI Engineering"
                    # example: "R3 Senior Researcher — Clinical AI Research"

                    combinations.append({
                        "jd_id": f"nexus__{team.team_key}__{level.level_code}__{year}",
                        "team_id": team.id,
                        "team_key": team.team_key,
                        "team_name": team.team_name,
                        "team_description": team.team_description,
                        "department": team.department_name,
                        "leveling_track": team.leveling_track,
                        "internal_collaborations": team.internal_collaborations or [],
                        "external_collaborations": team.external_collaborations or [],
                        "level_code": level.level_code,
                        "level_title": level.level_title,
                        "level_scope": level.scope,
                        "experience_range": exp_range,
                        "experience_min": level.experience_min or 0,
                        "experience_max": level.experience_max,
                        "publications_required": level.publications_required,
                        "publications_min": level.publications_min,
                        "manages_people": level.manages_people,
                        "mentors_levels": level.mentors_levels or [],
                        "typical_background": level.typical_background,
                        "autonomy": level.autonomy,
                        "year": year,
                        "required_technologies": required,
                        "preferred_technologies": preferred,
                        "active_projects": [
                            {"name": p.name, "description": p.description}
                            for p in projects
                        ],
                        "job_title": job_title,
                        "domain": domain
                    })

    finally:
        db.close()

    return combinations


# ─── Step 2: Build prompt ─────────────────────────────────────────────────────

def build_prompt(combo):
    required = ", ".join(combo["required_technologies"])
    preferred = ", ".join(combo["preferred_technologies"]) if combo["preferred_technologies"] else None
    mentors = ", ".join(combo["mentors_levels"]) if combo["mentors_levels"] else "none"
    manages = "Yes — this role has direct reports." if combo["manages_people"] else "No — individual contributor role."

    projects_text = "\n".join([
        f"  - {p['name']}: {p['description']}"
        for p in combo["active_projects"]
    ]) if combo["active_projects"] else "  - General team work aligned with department priorities"

    pub_section = ""
    if combo["publications_required"]:
        pub_section = f"\n- Minimum {combo['publications_min']} peer-reviewed publications in a relevant domain — this is a hard requirement, not preferred"

    preferred_section = ""
    if preferred:
        preferred_section = f"\nPreferred:\n- {preferred}"

    return f"""You are writing an external-facing job description for Nexus Health, a healthcare technology company.

Write a professional job description for this role. Follow all rules carefully.

═══ ROLE DETAILS ═══
Job Title: {combo['job_title']}
Level Code: {combo['level_code']}
Level Title: {combo['level_title']}
Domain: {combo['domain']}
Year: {combo['year']}

═══ LEVEL DEFINITION ═══
Scope: {combo['level_scope']}
Experience required: {combo['experience_range']}
Autonomy: {combo['autonomy']}
Manages people: {manages}
Mentors: {mentors}
Typical background: {combo['typical_background']}

═══ TECHNOLOGY STACK (use ONLY these — do not add or remove anything) ═══
Required: {required}{preferred_section}

═══ WORK CONTEXT IN {combo['year']} ═══
{projects_text}

═══ STRUCTURE TO FOLLOW ═══

Section 1 — About Nexus Health (use this exact text, do not change it):
{NEXUS_HEALTH_DESCRIPTION}

Section 2 — About the Role (3-4 sentences):
Describe what this person will do and own. Be specific about the TYPE of work 
(ML systems, data pipelines, clinical research, security architecture etc.) 
but do NOT name internal systems, specific clients, or internal project names.
Instead of "Real-time Inference Migration" say "real-time ML inference systems".
Instead of "Epic and Cerner" say "hospital system integrations".
Instead of "legacy Java claims system" say "large-scale healthcare data processing systems".

Section 3 — What You Will Work On (4-5 bullet points):
Describe real responsibilities based on the work context above.
Keep descriptions at the category level — what TYPE of work, not internal names.
Use active verbs: Design, Build, Own, Lead, Drive, Define, Maintain.

Section 4 — What We Are Looking For:
Required:
List each required technology as a bullet with one line explaining WHY it matters for this role.
Add the experience range: "{combo['experience_range']}"
{pub_section}

{f"Preferred:" + chr(10) + "List each preferred technology as a bullet." if preferred else ""}

Section 5 — Your Scope at {combo['level_code']} (3-4 sentences):
Describe what this level means at Nexus Health in plain English — 
ownership, autonomy, mentorship, decision-making authority.
Do NOT use the level code here — describe the scope in human terms.

═══ RULES ═══
1. NEVER name internal projects — describe the category of work instead
2. NEVER name specific hospital clients — say "hospital system integrations" or "healthcare clients"
3. NEVER reveal internal system architecture details
4. ONLY use technologies from the Required and Preferred lists above — do not add anything
5. Experience range must be exactly: {combo['experience_range']}
6. Publications rule: {"List as a HARD requirement — minimum " + str(combo['publications_min']) + " peer-reviewed publications required" if combo['publications_required'] else "Do not mention publications"}
7. Length: 400-500 words total
8. Tone: direct and professional — not marketing language, not generic corporate speak

Write only the job description. No preamble, no explanation."""


# ─── Step 3: Build batch file ─────────────────────────────────────────────────

def build_batch_file(combinations):
    written = 0
    with open(BATCH_INPUT_FILE, "w", encoding="utf-8") as f:
        for combo in combinations:
            request = {
                "custom_id": combo["jd_id"],
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": "gpt-4.1-mini",
                    "max_tokens": 900,
                    "temperature": 0.7,
                    "messages": [
                        {"role": "user", "content": build_prompt(combo)}
                    ]
                }
            }
            f.write(json.dumps(request, ensure_ascii=False) + "\n")
            written += 1

    print(f"Batch file written: {BATCH_INPUT_FILE}")
    print(f"Total requests: {written}")
    return written


# ─── Step 4: Submit batch ─────────────────────────────────────────────────────

def submit_batch():
    print("Uploading batch file to OpenAI...")
    with open(BATCH_INPUT_FILE, "rb") as f:
        batch_file = client.files.create(file=f, purpose="batch")

    print(f"File uploaded. ID: {batch_file.id}")

    batch = client.batches.create(
        input_file_id=batch_file.id,
        endpoint="/v1/chat/completions",
        completion_window="24h"
    )

    print(f"Batch submitted. ID: {batch.id}")
    print(f"Status: {batch.status}")

    with open("batch_id.txt", "w") as f:
        f.write(batch.id)

    print(f"Batch ID saved to batch_id.txt")
    return batch.id


# ─── Step 5: Check status ─────────────────────────────────────────────────────

def check_status(batch_id):
    batch = client.batches.retrieve(batch_id)
    print(f"Status:    {batch.status}")
    print(f"Completed: {batch.request_counts.completed}")
    print(f"Failed:    {batch.request_counts.failed}")
    print(f"Total:     {batch.request_counts.total}")
    return batch.status


# ─── Step 6: Download results ─────────────────────────────────────────────────

def download_results(batch_id):
    batch = client.batches.retrieve(batch_id)

    if batch.status != "completed":
        print(f"Not complete yet. Status: {batch.status}")
        return False

    print("Downloading results...")
    result = client.files.content(batch.output_file_id)

    with open(BATCH_OUTPUT_FILE, "wb") as f:
        f.write(result.content)

    print(f"Results saved to {BATCH_OUTPUT_FILE}")
    return True


# ─── Step 7: Index results ────────────────────────────────────────────────────

def index_results(combinations):
    # verify Elasticsearch index exists
    if not es.indices.exists(index="internal_jds"):
        print("ERROR: internal_jds index does not exist.")
        print("Run: python create_internal_jds_index.py")
        return

    # build lookup map: jd_id → combo metadata
    combo_map = {c["jd_id"]: c for c in combinations}

    db = Session()
    indexed = 0
    failed = 0
    skipped = 0

    try:
        with open(BATCH_OUTPUT_FILE, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    result = json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"Line {line_num}: JSON parse error — {e}")
                    failed += 1
                    continue

                # skip failed GPT calls
                if result.get("error"):
                    print(f"Failed: {result.get('custom_id')} — {result['error']}")
                    failed += 1
                    continue

                jd_id = result.get("custom_id")
                if not jd_id:
                    print(f"Line {line_num}: missing custom_id")
                    failed += 1
                    continue

                combo = combo_map.get(jd_id)
                if not combo:
                    print(f"No combo found for {jd_id} — skipping")
                    skipped += 1
                    continue

                # extract generated prose
                try:
                    description = result["response"]["body"]["choices"][0]["message"]["content"]
                except (KeyError, IndexError) as e:
                    print(f"Failed to extract content for {jd_id}: {e}")
                    failed += 1
                    continue

                # ── Write 1: Elasticsearch ──────────────────────────────────
                try:
                    es.index(
                        index="internal_jds",
                        id=jd_id,
                        document={
                            "jd_id":       jd_id,
                            "team_key":    combo["team_key"],
                            "level_code":  combo["level_code"],
                            "year_posted": combo["year"],
                            "job_title":   combo["job_title"],
                            "description": description
                        }
                    )
                except Exception as e:
                    print(f"Elasticsearch write failed for {jd_id}: {e}")
                    failed += 1
                    continue

                # ── Write 2: PostgreSQL ─────────────────────────────────────
                try:
                    existing = db.execute(
                        text("SELECT id FROM historical_jds WHERE jd_id = :jd_id"),
                        {"jd_id": jd_id}
                    ).fetchone()

                    if not existing:
                        is_current = (combo["year"] == 2024)
                        db.execute(text("""
                            INSERT INTO historical_jds 
                                (jd_id, team_id, level_code, year_posted, job_title, is_current)
                            VALUES 
                                (:jd_id, :team_id, :level_code, :year_posted, :job_title, :is_current)
                        """), {
                            "jd_id":       jd_id,
                            "team_id":     combo["team_id"],
                            "level_code":  combo["level_code"],
                            "year_posted": combo["year"],
                            "job_title":   combo["job_title"],
                            "is_current":  (combo["year"] == 2024)
                        })

                except Exception as e:
                    print(f"PostgreSQL write failed for {jd_id}: {e}")
                    failed += 1
                    continue

                indexed += 1

                # commit every 50 to avoid one huge transaction
                if indexed % 50 == 0:
                    db.commit()
                    print(f"Progress: {indexed} indexed, {failed} failed...")

        db.commit()
        print(f"\nDone.")
        print(f"Indexed:  {indexed}")
        print(f"Failed:   {failed}")
        print(f"Skipped:  {skipped}")

    except Exception as e:
        db.rollback()
        print(f"Fatal error during indexing: {e}")
        raise
    finally:
        db.close()


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "help"

    if command == "build":
        print("Fetching combinations from PostgreSQL...")
        combinations = get_all_combinations()
        print(f"Found {len(combinations)} combinations")

        # save for later use during index step
        with open(COMBINATIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(combinations, f, ensure_ascii=False, default=str)
        print(f"Combinations saved to {COMBINATIONS_FILE}")

        build_batch_file(combinations)
        print(f"\nNext step: python generate_internal_jds.py submit")

    elif command == "submit":
        submit_batch()
        print(f"\nNext step: python generate_internal_jds.py status")

    elif command == "status":
        batch_id = sys.argv[2] if len(sys.argv) > 2 else open("batch_id.txt").read().strip()
        check_status(batch_id)

    elif command == "download":
        batch_id = sys.argv[2] if len(sys.argv) > 2 else open("batch_id.txt").read().strip()
        download_results(batch_id)

    elif command == "index":
        with open(COMBINATIONS_FILE, "r", encoding="utf-8") as f:
            combinations = json.load(f)
        print(f"Loaded {len(combinations)} combinations from {COMBINATIONS_FILE}")
        index_results(combinations)

    else:
        print("Usage:")
        print("  python generate_internal_jds.py build")
        print("  python generate_internal_jds.py submit")
        print("  python generate_internal_jds.py status [batch_id]")
        print("  python generate_internal_jds.py download [batch_id]")
        print("  python generate_internal_jds.py index")