"""
Fetch REAL autocomplete responses from OpenAlex production API.

This script fetches actual responses from:
https://api.openalex.org/autocomplete/authors?q=...

Saves responses in format:
{
    "Albert Einstein": [list of author objects from API],
    "Marie Curie": [...],
    ...
}

Usage:
    python fetch_real_autocomplete_responses.py
"""
import json
import time
import requests
from pathlib import Path

# Test queries (diverse set for validation)
TEST_QUERIES = [
    "Albert Einstein",
    "Marie Curie",
    "Richard Feynman",
    "Ada Lovelace",
    "Alan Turing",
    "Rosalind Franklin",
    "Isaac Newton",
    "Charles Darwin",
    "Jane Goodall",
    "Stephen Hawking",
    "Niels Bohr",
    "Emmy Noether",
    "John von Neumann",
    "Grace Hopper",
    "Katherine Johnson",
    # Short queries (2-3 chars)
    "Al",
    "Ma",
    "Li",
    # Common names (many matches)
    "Smith",
    "Wang",
    "Johnson",
    # Special chars
    "O'Brien",
    # Diacritics
    "José García",
    "François Dupont",
    # Empty query
    "",
]

API_BASE = "https://api.openalex.org"
OUTPUT_FILE = Path(__file__).parent / "fixtures" / "openalex_autocomplete_responses.json"


def fetch_autocomplete(query, polite_email="test@example.com"):
    """
    Fetch autocomplete results from OpenAlex API.

    Args:
        query: Search query string
        polite_email: Email for polite pool

    Returns:
        List of author results
    """
    if query == "":
        # Empty query - API won't return results
        return []

    url = f"{API_BASE}/autocomplete/authors"
    params = {
        "q": query,
    }
    headers = {
        "User-Agent": f"OpenAlexValidation/1.0 (mailto:{polite_email})"
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Extract just the results array
        results = data.get("results", [])
        return results

    except Exception as e:
        print(f"  ❌ Error fetching '{query}': {e}")
        return []


def main():
    print("=" * 80)
    print("FETCHING REAL AUTOCOMPLETE RESPONSES FROM OPENALEX API")
    print("=" * 80)
    print()

    all_responses = {}
    total = len(TEST_QUERIES)

    for i, query in enumerate(TEST_QUERIES, 1):
        print(f"[{i}/{total}] Fetching: '{query}'...", end=" ")

        results = fetch_autocomplete(query)

        if results:
            print(f"✓ Got {len(results)} results")
        elif query == "":
            print("✓ Empty query (expected 0 results)")
        else:
            print("⚠️  No results")

        all_responses[query] = results

        # Be polite - don't hammer the API
        if i < total:
            time.sleep(0.1)

    # Save to file
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(all_responses, f, indent=2)

    print()
    print("=" * 80)
    print(f"✓ Saved {len(all_responses)} responses to: {OUTPUT_FILE}")
    print()

    # Summary
    non_empty = sum(1 for results in all_responses.values() if len(results) > 0)
    empty = len(all_responses) - non_empty

    print("SUMMARY:")
    print(f"  Total queries:      {len(all_responses)}")
    print(f"  With results:       {non_empty}")
    print(f"  Empty results:      {empty}")
    print()


if __name__ == '__main__':
    main()
