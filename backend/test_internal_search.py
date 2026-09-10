from elasticsearch import Elasticsearch

es = Elasticsearch("http://localhost:9200")

teams_to_compare = [
    ("claims_ai", "L4", 2022),
    ("clinical_ai_lab", "R3", 2022),
    ("compliance_audit", "SEC3", 2022),
    ("epidemiology_population_health", "R3", 2022),
]

for team_key, level_code, year in teams_to_compare:
    jd_id = f"nexus__{team_key}__{level_code}__{year}"
    try:
        result = es.get(index="internal_jds", id=jd_id)
        desc = result["_source"]["description"]
        title = result["_source"]["job_title"]
        print(f"\n{'='*60}")
        print(f"TEAM: {team_key} | {title}")
        print(f"{'='*60}")
        print(desc[:800])
        print("...")
    except Exception as e:
        print(f"Not found: {jd_id} — {e}")