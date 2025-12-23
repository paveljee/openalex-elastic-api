#!/usr/bin/env python3
"""
Populate Elasticsearch with author data from OpenAlex API
"""
import requests
import time
from elasticsearch import Elasticsearch

es = Elasticsearch(['http://127.0.0.1:9200'])

# Test queries to get diverse author data
# Covers: famous scientists, common names, diacritics, Asian names, special chars
queries = [
    # Famous scientists (high citation counts)
    "Albert Einstein",
    "Marie Curie",
    "Richard Feynman",
    "Stephen Hawking",

    # Single surname (ambiguous)
    "Einstein",
    "Curie",

    # Common Western names
    "John Smith",
    "Michael Johnson",

    # Diacritics (European)
    "José García",
    "Thomas Müller",
    "François Dubois",

    # Asian names (Chinese, Japanese, Korean)
    "Wei Wang",
    "Li Zhang",
    "Yuki Tanaka",
    "Kim Min-jun",

    # Middle Eastern/Arabic names
    "Mohamed Ahmed",
    "Ali Hassan",

    # Special characters
    "O'Brien",
    "Jean-Pierre",

    # Hyphenated/compound names
    "Anne-Marie Laurent",
    "Carlos García-Pérez",

    # Short names
    "Li Wei",
    "Ann Lee",
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

    # Retry with exponential backoff on rate limit
    max_retries = 3
    for attempt in range(max_retries):
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            break
        elif response.status_code == 503 and attempt < max_retries - 1:
            wait_time = 2 ** attempt  # 1s, 2s, 4s
            print(f"  Rate limited, waiting {wait_time}s...")
            time.sleep(wait_time)
        else:
            print(f"  API error: {response.status_code} - {response.text[:200]}")
            break

    if response.status_code != 200:
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
    time.sleep(0.5)  # Increased to avoid rate limiting

print(f"\nTotal indexed: {indexed} authors")

# Refresh index
es.indices.refresh(index="authors-v16")
print("Index refreshed")

# Show count
count = es.count(index="authors-v16")
print(f"Total documents in index: {count['count']}")
