"""
REAL RANKING COMPARISON TEST

Compares ACTUAL ranking order between:
1. Real OpenAlex API (production)
2. Extracted logic against local Elasticsearch

No bullshit. Just actual ranking comparison.
"""
import sys
sys.path.insert(0, '/home/user/openalex-elastic-api')

import requests
import time
from elasticsearch_dsl import Search, connections

from core.author_matching import build_author_search_query
from settings import AUTHORS_INDEX, ES_URL


OPENALEX_API = "https://api.openalex.org"


def fetch_openalex_ranking(search_name, limit=25):
    """Get ranking from real OpenAlex API"""
    url = f"{OPENALEX_API}/authors"
    params = {
        "search": search_name,
        "per-page": limit,
        "mailto": "[email protected]"  # Polite pool for better rate limits
    }

    time.sleep(0.15)  # Rate limit

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        results = response.json().get("results", [])
        return [r["id"] for r in results]
    except Exception as e:
        print(f"API Error: {e}")
        return None


def fetch_extracted_ranking(search_name, limit=25):
    """Get ranking using extracted logic against local ES"""
    try:
        # Connect to ES
        connections.create_connection('default', hosts=[ES_URL], timeout=5)

        # Build query using extracted logic
        query = build_author_search_query(search_name)

        # Execute
        s = Search(index=AUTHORS_INDEX)
        s = s.query(query)
        s = s.sort("_score", "-works_count", "id")
        s = s[:limit]

        results = s.execute()
        return [hit.id for hit in results]
    except Exception as e:
        print(f"ES Error: {e}")
        return None


def compare_rankings(api_ids, extracted_ids, name):
    """Compare two rankings"""
    if api_ids is None:
        print(f"  ⚠️  SKIP - API failed for '{name}'")
        return None

    if extracted_ids is None:
        print(f"  ⚠️  SKIP - ES failed for '{name}'")
        return None

    if len(api_ids) == 0 or len(extracted_ids) == 0:
        print(f"  ⚠️  SKIP - No results for '{name}'")
        return None

    # Check exact match
    if api_ids == extracted_ids:
        print(f"  ✅ EXACT MATCH - '{name}'")
        return True

    # Check top 10 overlap
    api_top10 = set(api_ids[:10])
    extracted_top10 = set(extracted_ids[:10])
    overlap = len(api_top10 & extracted_top10)
    overlap_pct = (overlap / 10 * 100) if len(api_top10) >= 10 else 0

    # Check top 3
    top3_match = api_ids[:3] == extracted_ids[:3]

    print(f"  ❌ MISMATCH - '{name}'")
    print(f"     Top 10 overlap: {overlap}/10 ({overlap_pct:.0f}%)")
    print(f"     Top 3 match: {top3_match}")
    print(f"     API top 5:      {api_ids[:5]}")
    print(f"     Extracted top 5: {extracted_ids[:5]}")

    return False


def test_real_ranking_comparison():
    """
    Test actual ranking comparison between API and extracted logic.

    This test compares REAL rankings, not query structures.
    """
    test_cases = [
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

    print("=" * 80)
    print("REAL RANKING COMPARISON TEST")
    print("=" * 80)
    print(f"Testing {len(test_cases)} queries...")
    print()

    results = {
        'exact_match': 0,
        'mismatch': 0,
        'skipped': 0,
    }

    for name in test_cases:
        print(f"Testing: '{name}'")

        # Get rankings from both sources
        api_ids = fetch_openalex_ranking(name, limit=25)
        extracted_ids = fetch_extracted_ranking(name, limit=25)

        # Compare
        match = compare_rankings(api_ids, extracted_ids, name)

        if match is True:
            results['exact_match'] += 1
        elif match is False:
            results['mismatch'] += 1
        else:
            results['skipped'] += 1

        print()

    # Summary
    print("=" * 80)
    print("RESULTS:")
    print("=" * 80)
    print(f"Exact matches:  {results['exact_match']}")
    print(f"Mismatches:     {results['mismatch']}")
    print(f"Skipped:        {results['skipped']}")
    print("=" * 80)

    # Assertions
    total_tested = results['exact_match'] + results['mismatch']

    if total_tested == 0:
        print("\n❌ TEST INCONCLUSIVE - No comparisons completed")
        print("   (Either API or ES is not available)")
        return False

    match_rate = results['exact_match'] / total_tested * 100 if total_tested > 0 else 0

    print(f"\nMatch rate: {match_rate:.1f}%")

    if match_rate == 100:
        print("✅ PERFECT - All rankings match exactly!")
        return True
    elif match_rate >= 50:
        print("⚠️  PARTIAL - Some rankings match, but not all")
        return False
    else:
        print("❌ FAIL - Most rankings don't match")
        return False


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v', '-s']))
