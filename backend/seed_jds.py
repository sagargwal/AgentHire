from datasets import load_dataset
from elasticsearch import Elasticsearch

es_client = Elasticsearch("http://localhost:9200")

print("Loading dataset...")
dataset = load_dataset("lang-uk/recruitment-dataset-job-descriptions-english")

target_keywords = ["Python", "Golang", "Java", "React", "Node.js",
                    "Data Science", "Data Engineer", "DevOps", "QA"]


def infer_seniority(title: str) -> str:
    title_lower = title.lower()
    if "senior" in title_lower or "lead" in title_lower:
        return "senior"
    elif "middle" in title_lower or "mid" in title_lower:
        return "mid"
    elif "junior" in title_lower:
        return "junior"
    else:
        return "mid"


count = 0
for keyword in target_keywords:
    print(f"\nFiltering for: {keyword}")
    filtered = dataset["train"].filter(lambda x: x["Primary Keyword"] == keyword)
    subset = filtered.select(range(min(30, len(filtered))))

    for i, row in enumerate(subset):
        doc_id = f"{keyword.lower().replace(' ', '_')}_{i}"
        doc = {
            "title": row["Position"],
            "seniority": infer_seniority(row["Position"]),
            "skills": [keyword],
            "description": row["Long Description"],
            "source_keyword": keyword
        }
        es_client.index(index="jds", id=doc_id, document=doc)
        count += 1
        print(f"  Indexed {doc_id}: {doc['title'][:60]}")

print(f"\nDone. Indexed {count} documents total.")