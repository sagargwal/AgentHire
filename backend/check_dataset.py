from elasticsearch import Elasticsearch

es_client = Elasticsearch("http://localhost:9200")

response = es_client.search(
    index="jds",
    query={
        "multi_match": {
            "query": "backend developer python",
            "fields": ["title", "description"],
            "type": "best_fields"
        }
    },
    size=5
)

print(f"Total hits: {response['hits']['total']['value']}")
for hit in response["hits"]["hits"]:
    print(f"  score={hit['_score']:.2f} | {hit['_source']['title']}")