import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.nexus_company import (
    NexusBase, NexusCompany, NexusDepartment,
    NexusLevel, NexusTeam, NexusTeamTechnology, NexusTeamProject
)

# PostgreSQL connection — separate from your MySQL connection
POSTGRES_URL = "postgresql+psycopg2://nexus_user:nexus_pass@localhost:5432/nexus_health"
engine = create_engine(POSTGRES_URL)

# Create all tables defined under NexusBase in PostgreSQL
# Safe to run multiple times — skips tables that already exist
NexusBase.metadata.create_all(engine)
print("Tables created.")

Session = sessionmaker(bind=engine)
db = Session()

# Load the company model JSON you downloaded earlier
with open("nexus_health_model.json") as f:
    model = json.load(f)

try:
    # 1. Insert the company
    c = model["company"]
    company = NexusCompany(
        name=c["name"],
        industry=c["industry"],
        founded_year=c["founded_year"],
        description=c["description"],
        headquarters=c["headquarters"],
        size=c["size"]
    )
    db.add(company)
    db.flush()  # sends to DB, gets company.id back
    print(f"Company inserted: {company.name} (id={company.id})")

    # 2. Loop through departments
    for dept_data in model["departments"]:
        dept = NexusDepartment(
            company_id=company.id,
            name=dept_data["name"],
            leveling_track=dept_data["leveling_track"],
            description=dept_data["description"]
        )
        db.add(dept)
        db.flush()  # gets dept.id back before inserting levels/teams
        print(f"  Department: {dept.name} (id={dept.id})")

        # 3. Insert levels for this department
        for level_data in dept_data.get("levels", []):
            level = NexusLevel(
                department_id=dept.id,
                level_code=level_data["code"],
                level_title=level_data["title"],
                scope=level_data["scope"],
                autonomy=level_data["autonomy"],
                manages_people=level_data["manages_people"],
                mentors_levels=level_data["mentors_levels"],
                experience_min=level_data["experience_min"],
                experience_max=level_data["experience_max"],
                publications_required=level_data["publications_required"],
                publications_min=level_data["publications_min"],
                typical_background=level_data["typical_background"]
            )
            db.add(level)
        print(f"    {len(dept_data.get('levels', []))} levels inserted")

        # 4. Insert teams for this department
        for team_data in dept_data.get("teams", []):
            team = NexusTeam(
                department_id=dept.id,
                team_key=team_data["id"],
                name=team_data["name"],
                description=team_data["description"],
                headcount=team_data["headcount"],
                founded_year=team_data["founded_year"],
                internal_collaborations=team_data["internal_collaborations"],
                external_collaborations=team_data["external_collaborations"]
            )
            db.add(team)
            db.flush()  # gets team.id back before inserting technologies/projects
            print(f"    Team: {team.name} (id={team.id})")

            # 5. Insert technologies for this team
            for tech_data in team_data.get("technologies", []):
                tech = NexusTeamTechnology(
                    team_id=team.id,
                    name=tech_data["name"],
                    category=tech_data["category"],
                    is_mandatory=tech_data["mandatory"],
                    adopted_year=tech_data["adopted"],
                    deprecated_year=tech_data["deprecated"],
                    notes=tech_data["notes"]
                )
                db.add(tech)

            # 6. Insert projects for this team
            for proj_data in team_data.get("projects", []):
                proj = NexusTeamProject(
                    team_id=team.id,
                    name=proj_data["name"],
                    status=proj_data["status"],
                    start_year=proj_data["start"],
                    end_year=proj_data["end"],
                    description=proj_data["description"]
                )
                db.add(proj)

    # Commit everything at once — all or nothing
    db.commit()
    print("\nDone. All data committed successfully.")

except Exception as e:
    db.rollback()  # if anything fails, undo everything
    print(f"Error: {e}")
    raise

finally:
    db.close()