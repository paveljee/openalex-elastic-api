#!/usr/bin/env python3
"""
Populate Elasticsearch with author data from OpenAlex API
"""
import requests
import time
from elasticsearch import Elasticsearch

es = Elasticsearch(['http://127.0.0.1:9200'])

# Test queries to get diverse author data
queries = [
    "Albert Einstein",
    "Marie Curie",
    "Einstein",
    "John Smith",
    "Wei Wang",
    "Richard Feynman",
]

indexed = 0
for query in queries:
    print(f"Fetching authors for: {query}")

    url = "https://api.openalex.org/authors"
    params = {
        "search": query,
        "per-page": 50,
        "mailto": "[email protected]"
    }

    response = requests.get(url, params=params, timeout=10)
    if response.status_code != 200:
        print(f"  API error: {response.status_code} - {response.text[:200]}")
        continue
    authors = response.json().get("results", [])

    for author in authors:
        doc = {
            "id": author["id"],
            "display_name": author["display_name"],
            "display_name_alternatives": author.get("display_name_alternatives", []),
            "cited_by_count": author.get("cited_by_count", 0),
            "works_count": author.get("works_count", 0),
        }

        es.index(index="authors-v16", id=author["id"], document=doc)
        indexed += 1

    print(f"  Indexed {len(authors)} authors")
    time.sleep(0.2)

print(f"\nTotal indexed: {indexed} authors")

# Refresh index
es.indices.refresh(index="authors-v16")
print("Index refreshed")

# Show count
count = es.count(index="authors-v16")
print(f"Total documents in index: {count['count']}")
