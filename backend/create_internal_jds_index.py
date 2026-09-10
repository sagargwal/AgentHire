from elasticsearch import Elasticsearch

es = Elasticsearch("http://localhost:9200")

# Delete if exists (clean slate)
if es.indices.exists(index="internal_jds"):
    es.indices.delete(index="internal_jds")
    print("Deleted existing internal_jds index")

# Create with correct mapping
es.indices.create(
    index="internal_jds",
    body={
        "mappings": {
            "properties": {
                "jd_id":       {"type": "keyword"},
                "team_key":    {"type": "keyword"},
                "level_code":  {"type": "keyword"},
                "year_posted": {"type": "integer"},
                "job_title": {
                    "type": "text",
                    "fields": {
                        "keyword": {"type": "keyword"}
                    }
                },
                "description": {"type": "text"}
            }
        }
    }
)

print("Created internal_jds index with correct mapping")

# Verify
info = es.indices.get(index="internal_jds")
print(f"Index created: {list(info.keys())}")