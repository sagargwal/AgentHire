# AgentHire

**A company-aware agentic job description intelligence platform.**

AgentHire replaces the manual, error-prone process of writing job descriptions with an AI agent that understands your company — its teams, technologies, levels, and institutional voice — and produces grounded, sanitized, publish-ready JDs through a single conversation.

---

## The Problem

Writing a job description is deceptively hard.

A hiring manager calls HR and says: *"We need someone for Claims AI who can handle the Kafka work."* HR now has to:

1. Figure out which team that maps to
2. Determine the right level — L3 or L4?
3. Find the current tech stack — hope the shared drive is up to date
4. Remember to exclude client names like Epic and Cerner from the public posting
5. Match the company's institutional writing voice
6. Write the JD manually in Word
7. Email for approval
8. Log into a separate careers platform, copy-paste, fix formatting, publish

**Every step is a chance for a mistake.** Stale technologies get listed. Internal project names leak into public postings. The wrong leveling track gets used. HR doesn't know the difference between an L3 and L4 because the distinction lives in the hiring manager's head, not in any document.

### The root cause

The knowledge needed to write a good JD is distributed across the organisation:

- **HR** knows the hiring process
- **The hiring manager** knows the business need
- **The employee doing the job** knows the day-to-day reality

But when HR sits down to write the JD, they are working from memory, outdated documents, and assumptions. **The JD is not grounded in what the company actually is right now.**

---

## The Solution

AgentHire solves this in two parts:

### Part 1 — Build a living company knowledge graph

Every employee fills a simple monthly form:
- What are you working on right now?
- What tools and technologies are you using?
- Which teams do you collaborate with?
- What changed since last month?

This data is aggregated into a structured PostgreSQL database — a knowledge graph of the company's actual current state. Every technology has an `adopted_year` and a `deprecated_year`. Every team has its current stack, its projects, and its collaborations. No HR administrator maintains this. The people doing the work maintain it.

### Part 2 — An AI agent that reasons over this graph

When HR needs a JD, they type one sentence in a chat interface. The agent:

1. **Understands the query** — resolves the team, detects the right leveling track, identifies the level from scope not years
2. **Retrieves grounded information** — queries PostgreSQL for the current tech stack, queries Elasticsearch for historical JDs to match the company's institutional writing voice
3. **Enforces business rules in code** — removes client names, internal project names, and deprecated technologies in Python, not in a prompt
4. **Presents a context summary** — shows HR exactly what it will use before drafting anything
5. **Drafts the full JD** — five required sections, correct experience range, correct track, correct publication requirements
6. **Waits for HR approval** — HITL gate before anything goes live
7. **Publishes to the careers page** — one conversation, end to end

---

## Demo

**Live demo:** [agenthire-frontend.vercel.app](https://agenthire-frontend.vercel.app)

```
Email:       demo@nexushealth.com
Password:    AgentHire2026
Invite code: NEXUSHEALTH2026
```

The demo runs against **Nexus Health** — a synthetic healthcare technology company with:
- 5 departments · 23 teams · 37 level definitions across 5 tracks (L, R, SEC, LA, OA)
- 165 technologies with `adopted_year` and `deprecated_year` per team
- 81 active projects
- 974 historical JDs indexed in Elasticsearch for institutional voice retrieval

---

## Architecture

```
Chat Interface (Next.js · Vercel)
        ↓
JWT Auth Layer → MySQL (users · tokens · roles)
        ↓
FastAPI Backend (Hetzner VPS · Ubuntu 22.04)
        ↓
AI Agent (LangGraph + GPT-4o)
    ├── Chat Node ←→ Tools Node (iterative loop)
    ↕
Redis Stack (session state · conversation memory)

Tools:
  Information tools   → PostgreSQL (company knowledge graph)
    query_company_database
    get_team_context
    get_levels_for_team
    find_team_by_project

  Drafting tools      → Sanitization Layer → Elasticsearch (974 JDs)
    draft_jd

  Publishing tools    → HITL Approval Gate → Careers Page
    finalize_jd
    post_jd
```

---

## Key Design Decisions

### 1. Tools enforce guarantees — not prompts

A naive implementation would put business rules in the system prompt:

```
"Never include client names like Epic or Cerner in JDs"
```

The LLM follows this ~95% of the time. AgentHire's approach runs a Python loop after every draft:

```python
for name in banned_names:
    jd_text = jd_text.replace(name, sanitized_equivalent[name])
```

**100% guaranteed.** The model cannot override it.

### 2. Temporal knowledge graph

The `team_technologies` table has two columns most systems don't have:

```sql
adopted_year     INTEGER   -- when did this team start using this tech
deprecated_year  INTEGER   -- when did this team stop using it (NULL = current)
```

A JD generated today automatically reflects the 2026 stack — not what someone filled in a form in 2021. XML deprecated in 2022 never appears in a 2026 JD.

### 3. Three-phase HITL flow

The agent never drafts without HR confirming the context first:

```
Phase 1: Agent silently gathers context (team, level, stack, voice)
Phase 2: Agent presents structured summary → HR confirms
Phase 3: Agent drafts JD → finalize_jd raises interrupt → HR approves → published
```

HR stays in control at every decision point.

### 4. Two-database architecture

```
PostgreSQL   → grounded facts (company knowledge graph)
               structured queries, relational joins, constraints

Elasticsearch → institutional voice (974 historical JDs)
               full-text search, similarity, style retrieval
```

Each database does what it is best at.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js · Vercel |
| Backend | FastAPI · Python 3.10 |
| Agent | LangGraph · GPT-4o |
| Company graph | PostgreSQL 16 |
| Voice retrieval | Elasticsearch 8.11 |
| Session state | Redis Stack |
| Auth | MySQL 8 · JWT |
| Infrastructure | Docker · Hetzner CX23 · Ubuntu 22.04 · nginx · systemd |

---

## Project Structure

```
backend/
├── app/
│   ├── agents/
│   │   └── jd_builder/
│   │       ├── graph.py       # LangGraph graph definition
│   │       ├── tools.py       # All 9 agent tools
│   │       ├── state.py       # JDBuilderState TypedDict
│   │       └── prompts.py     # System prompt
│   ├── core/
│   │   ├── postgres_db.py     # PostgreSQL engine + session
│   │   └── security.py        # JWT + password hashing
│   ├── models/
│   │   ├── nexus_company.py   # PostgreSQL ORM models
│   │   └── user.py            # MySQL ORM models
│   ├── routers/
│   │   ├── jd_builder.py      # Chat endpoints
│   │   ├── auth.py            # Auth endpoints
│   │   └── careers.py         # GET /careers, GET /careers/{slug}
│   └── scripts/
│       └── seed_nexus_health.py  # DB seeding script
├── main.py
└── requirements.txt
```

---

## Running Locally

### Prerequisites
- Docker Desktop
- Python 3.10+
- Node.js 18+
- OpenAI API key

### 1. Clone the repo

```bash
git clone https://github.com/sagargwal/AgentHire.git
cd AgentHire
```

### 2. Start services

```bash
docker-compose up -d
```

This starts PostgreSQL, MySQL, Elasticsearch, and Redis.

### 3. Set up backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create `.env`:

```env
DATABASE_URL=mysql+pymysql://agenthire_user:agenthire_pass@localhost:3306/agenthire
POSTGRES_URL=postgresql+psycopg2://nexus_user:nexus_pass@localhost:5432/nexus_health
OPENAI_API_KEY=your_openai_key
SECRET_KEY=your_secret_key
INVITE_CODE=NEXUSHEALTH2026
```

Create tables and seed the database:

```bash
python -m app.core.postgres_db
python app/scripts/seed_nexus_health.py
```

Start the backend:

```bash
uvicorn main:app --reload
```

### 4. Set up frontend

```bash
cd ../frontend  # or your frontend repo
npm install
```

Create `.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

---

## Evaluation Framework

AgentHire includes a benchmark framework with **66 ground truth test cases** across **13 categories**:

| Category | Cases | Threshold |
|----------|-------|-----------|
| Standard JD requests | 10 | 0.80 |
| Level disambiguation | 5 | 0.80 |
| Project-based lookup | 5 | 0.75 |
| Sanitization stress | 5 | 1.00 |
| Out of scope rejection | 5 | 0.80 |
| Company knowledge queries | 8 | 0.75 |
| JD audit / currency check | 5 | 0.70 |
| Non-existent role requests | 6 | 0.60 |
| Combined / hybrid JD | 3 | 0.70 |
| Partial information | 4 | 0.75 |
| HR override edge cases | 4 | 0.75 |
| Multi-JD context isolation | 2 | 0.70 |
| Retrieval quality | 4 | 0.75 |

Every check is a deterministic Python string operation — not an LLM judge. Reproducible, actionable, free.

```bash
cd benchmark
python runners/run_all.py --url http://localhost:8000 --delay 3.0
```

---

## What Makes This Different

| | Filter + Button Software | AgentHire |
|---|---|---|
| Input | Dropdown selection | Natural language |
| Level determination | HR must know | Agent reasons from scope |
| Tech stack accuracy | Hope the form is current | Temporal DB with adopted/deprecated year |
| Sanitization | HR memory | Python code guarantee |
| Cross-team requests | Two separate queries | Agent finds intersection |
| Stale JD detection | Not possible | Compares Elasticsearch JD vs current DB |
| Publishing | Separate tool, copy-paste | One conversation, auto-publish |

---

## Author

**Sagar Gwal** — AI Engineer

Built as a portfolio project demonstrating agentic system design, evaluation-driven development, and production deployment of LLM-powered applications in the HRTech domain.

- Previously: AI Engineer at Recruitment Smart Technologies
- Education: M.Tech Biomolecular & Bioprocess Engineering, IIT Delhi

---

## License

MIT
