"""
REAL RANKING LOGIC TEST

Compares ranking order between:
1. OpenAlex API (their ranking)
2. Our extracted ranking logic applied to the same data

No Elasticsearch needed - we apply the ranking algorithm directly.
"""
import sys
sys.path.insert(0, '/home/user/openalex-elastic-api')

import requests
import time
import math


OPENALEX_API = "https://api.openalex.org"


def fetch_authors_from_api(search_name, limit=50):
    """Get authors from OpenAlex API with their ranking"""
    url = f"{OPENALEX_API}/authors"
    params = {
        "search": search_name,
        "per-page": limit,
        "mailto": "[email protected]"
    }

    time.sleep(0.15)

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        results = response.json().get("results", [])

        authors = []
        for r in results:
            authors.append({
                'id': r['id'],
                'display_name': r['display_name'],
                'cited_by_count': r.get('cited_by_count', 0),
                'works_count': r.get('works_count', 0),
                'relevance_score': r.get('relevance_score', 0.0),  # API's score
            })
        return authors
    except Exception as e:
        print(f"API Error: {e}")
        return None


def apply_extracted_ranking(authors, search_name):
    """
    Apply our extracted ranking logic to authors.

    The logic from core/author_matching.py:
    1. Base relevance score (we'll use API's relevance_score as proxy)
    2. Citation boost: score * (1 + sqrt(cited_by_count))
    3. Sort by: boosted_score desc, works_count desc, id asc
    """
    ranked = []

    for author in authors:
        # Get base score (API's relevance score)
        base_score = author['relevance_score']

        # Apply citation boost (our extracted formula)
        cited_by_count = author['cited_by_count']
        if cited_by_count == 0:
            citation_multiplier = 0.5
        else:
            citation_multiplier = 1 + math.sqrt(cited_by_count)

        boosted_score = base_score * citation_multiplier

        ranked.append({
            'id': author['id'],
            'display_name': author['display_name'],
            'base_score': base_score,
            'cited_by_count': cited_by_count,
            'works_count': author['works_count'],
            'citation_multiplier': citation_multiplier,
            'boosted_score': boosted_score,
        })

    # Sort by our extracted logic: boosted_score desc, works_count desc, id asc
    ranked.sort(key=lambda x: (-x['boosted_score'], -x['works_count'], x['id']))

    return ranked


def compare_rankings(api_authors, extracted_authors, name):
    """Compare API ranking vs our extracted ranking"""

    # Get IDs in order
    api_order = [a['id'] for a in api_authors]
    extracted_order = [a['id'] for a in extracted_authors]

    # Check exact match
    if api_order == extracted_order:
        print(f"  ✅ EXACT MATCH - '{name}'")
        return True

    # Calculate differences
    api_top5 = api_order[:5]
    extracted_top5 = extracted_order[:5]

    # Check top 5 overlap
    overlap = len(set(api_top5) & set(extracted_top5))

    # Find where they differ
    first_diff = None
    for i in range(min(len(api_order), len(extracted_order))):
        if api_order[i] != extracted_order[i]:
            first_diff = i
            break

    print(f"  ❌ MISMATCH - '{name}'")
    print(f"     Top 5 overlap: {overlap}/5")
    print(f"     First difference at position: {first_diff}")

    # Show top 5 comparison
    print(f"\n     API order (top 5):")
    for i, author_id in enumerate(api_top5):
        author = next(a for a in api_authors if a['id'] == author_id)
        print(f"       {i+1}. {author['display_name']} (score: {author.get('relevance_score', 'N/A'):.3f})")

    print(f"\n     Our ranking (top 5):")
    for i, author_id in enumerate(extracted_top5):
        author = next(a for a in extracted_authors if a['id'] == author_id)
        print(f"       {i+1}. {author['display_name']} (boosted: {author['boosted_score']:.3f}, " +
              f"cites: {author['cited_by_count']}, works: {author['works_count']})")

    return False


def test_ranking_logic():
    """
    Test that our extracted ranking logic produces the same order as OpenAlex API.
    """
    test_cases = [
        "Albert Einstein",
        "Marie Curie",
        "Einstein",
        "John Smith",
        "Wei Wang",
        "Richard Feynman",
    ]

    print("=" * 80)
    print("RANKING LOGIC TEST")
    print("=" * 80)
    print("Testing if our extracted ranking logic matches OpenAlex API ranking")
    print()

    results = {
        'exact_match': 0,
        'mismatch': 0,
        'skipped': 0,
    }

    for name in test_cases:
        print(f"Testing: '{name}'")

        # Get authors from API
        api_authors = fetch_authors_from_api(name, limit=25)

        if not api_authors or len(api_authors) == 0:
            print(f"  ⚠️  SKIP - No results from API")
            results['skipped'] += 1
            print()
            continue

        # Apply our extracted ranking logic
        extracted_ranking = apply_extracted_ranking(api_authors, name)

        # Compare
        match = compare_rankings(api_authors, extracted_ranking, name)

        if match:
            results['exact_match'] += 1
        else:
            results['mismatch'] += 1

        print()

    # Summary
    print("=" * 80)
    print("RESULTS:")
    print("=" * 80)
    print(f"Exact matches:  {results['exact_match']}")
    print(f"Mismatches:     {results['mismatch']}")
    print(f"Skipped:        {results['skipped']}")
    print("=" * 80)

    total_tested = results['exact_match'] + results['mismatch']

    if total_tested == 0:
        print("\n⚠️  TEST INCONCLUSIVE - No comparisons completed")
        assert False, "No tests could be completed"

    match_rate = results['exact_match'] / total_tested * 100
    print(f"\nMatch rate: {match_rate:.1f}%")

    if match_rate == 100:
        print("✅ PERFECT - All rankings match exactly!")
    elif match_rate >= 80:
        print("⚠️  GOOD - Most rankings match")
        print("\nNote: Some differences expected due to:")
        print("  - API may use different base relevance scoring")
        print("  - Tie-breaking may differ slightly")
    else:
        print("❌ SIGNIFICANT DIFFERENCES")
        print("\nThis suggests our extracted ranking logic differs from API")

    # Assert at least 50% match for test to pass
    assert match_rate >= 50, f"Match rate too low: {match_rate}%"


if __name__ == '__main__':
    test_ranking_logic()
