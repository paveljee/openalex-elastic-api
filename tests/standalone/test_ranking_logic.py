"""
REAL DEAL TEST: Original vs Extracted on SAME Elasticsearch

Compares ranking order between:
1. ORIGINAL code from core/search.py
2. EXTRACTED code from core/author_matching.py

Both querying the SAME local Elasticsearch instance.

If queries are identical, results MUST be 100% identical.
"""
import sys
sys.path.insert(0, '/home/user/openalex-elastic-api')

from elasticsearch_dsl import Search, connections

from core.search import SearchOpenAlex
from core.author_matching import build_author_search_query
from settings import AUTHORS_INDEX, ES_URL


def fetch_original_ranking(search_name, limit=25):
    """Get ranking using ORIGINAL core/search.py logic"""
    try:
        connections.create_connection('default', hosts=[ES_URL], timeout=5)

        # Build query using ORIGINAL logic
        search_obj = SearchOpenAlex(
            search_terms=search_name,
            secondary_field='display_name_alternatives',
            is_author_name_query=True
        )

        # Build base query then apply citation boost
        base_query = search_obj.author_name_query()
        query = search_obj.citation_boost_query(base_query, scaling_type="sqrt")

        # Execute with same sorting as production
        s = Search(index=AUTHORS_INDEX)
        s = s.query(query)
        s = s.sort("_score", "-works_count", "id")
        s = s[:limit]

        results = s.execute()
        return [hit.id for hit in results], [hit.meta.score for hit in results]
    except Exception as e:
        print(f"Original Error: {e}")
        import traceback
        traceback.print_exc()
        return None, None


def fetch_extracted_ranking(search_name, limit=25):
    """Get ranking using EXTRACTED core/author_matching.py logic"""
    try:
        connections.create_connection('default', hosts=[ES_URL], timeout=5)

        # Build query using EXTRACTED logic
        query = build_author_search_query(search_name)

        # Execute with same sorting as production
        s = Search(index=AUTHORS_INDEX)
        s = s.query(query)
        s = s.sort("_score", "-works_count", "id")
        s = s[:limit]

        results = s.execute()
        return [hit.id for hit in results], [hit.meta.score for hit in results]
    except Exception as e:
        print(f"Extracted Error: {e}")
        import traceback
        traceback.print_exc()
        return None, None


def compare_rankings(original_ids, original_scores, extracted_ids, extracted_scores, name):
    """Compare two rankings with detailed output"""
    if original_ids is None or extracted_ids is None:
        print(f"  ⚠️  SKIP - Failed for '{name}'")
        return None

    # Check EXACT match
    if original_ids == extracted_ids:
        print(f"  ✅ PERFECT MATCH - '{name}'")
        print(f"     All {len(original_ids)} results in EXACT same order")
        return True

    # Show differences
    print(f"  ❌ RANKING MISMATCH - '{name}'")
    print(f"     Original:  {original_ids[:5]}")
    print(f"     Extracted: {extracted_ids[:5]}")

    # Check if same IDs, different order
    if set(original_ids) == set(extracted_ids):
        print(f"     → Same documents, DIFFERENT ORDER (scoring issue!)")

        # Show score differences
        print(f"\n     Score comparison:")
        for i in range(min(5, len(original_ids))):
            orig_score = original_scores[i] if i < len(original_scores) else "N/A"
            extr_score = extracted_scores[i] if i < len(extracted_scores) else "N/A"
            print(f"       Position {i+1}: Original={orig_score:.4f}, Extracted={extr_score:.4f}")
    else:
        print(f"     → DIFFERENT DOCUMENTS (query mismatch!)")

    return False


def test_original_vs_extracted_same_es():
    """
    THE REAL DEAL TEST.

    Compare ORIGINAL vs EXTRACTED on SAME Elasticsearch instance.
    If queries are identical, results MUST be 100% identical.
    """
    test_cases = [
        # Famous scientists
        "Albert Einstein",
        "Marie Curie",
        "Richard Feynman",
        "Stephen Hawking",

        # Ambiguous
        "Einstein",
        "Curie",

        # Common names
        "John Smith",
        "Michael Johnson",

        # Diacritics
        "José García",
        "Thomas Müller",
        "François Dubois",

        # Asian names
        "Wei Wang",
        "Li Zhang",
        "Yuki Tanaka",
        "Kim Min-jun",

        # Middle Eastern
        "Mohamed Ahmed",
        "Ali Hassan",

        # Special chars
        "O'Brien",
        "Jean-Pierre",

        # Compound names
        "Anne-Marie Laurent",
        "Carlos García-Pérez",

        # Short names
        "Li Wei",
        "Ann Lee",
    ]

    print("=" * 80)
    print("ORIGINAL VS EXTRACTED - SAME ELASTICSEARCH INSTANCE")
    print("=" * 80)
    print(f"Testing {len(test_cases)} queries...")
    print()

    results = {
        'perfect_match': 0,
        'mismatch': 0,
        'skipped': 0,
    }

    for name in test_cases:
        print(f"Testing: '{name}'")

        # Get rankings from both implementations
        original_ids, original_scores = fetch_original_ranking(name, limit=25)
        extracted_ids, extracted_scores = fetch_extracted_ranking(name, limit=25)

        # Compare
        match = compare_rankings(original_ids, original_scores, extracted_ids, extracted_scores, name)

        if match is True:
            results['perfect_match'] += 1
        elif match is False:
            results['mismatch'] += 1
        else:
            results['skipped'] += 1

        print()

    # Summary
    print("=" * 80)
    print("RESULTS:")
    print("=" * 80)
    print(f"Perfect matches: {results['perfect_match']}")
    print(f"Mismatches:      {results['mismatch']}")
    print(f"Skipped:         {results['skipped']}")
    print("=" * 80)

    # Assertion
    total_tested = results['perfect_match'] + results['mismatch']

    if total_tested == 0:
        print("\n❌ TEST INCONCLUSIVE - No comparisons completed")
        return False

    match_rate = results['perfect_match'] / total_tested * 100 if total_tested > 0 else 0

    print(f"\nMatch rate: {match_rate:.1f}%")

    if match_rate == 100:
        print("✅ PERFECT - 100% exact matches! Extracted logic is IDENTICAL!")
        assert True
        return True
    else:
        print(f"❌ FAIL - Only {match_rate:.1f}% exact matches")
        print("   This means the extracted logic is NOT identical to the original!")
        assert False, f"Expected 100% match rate, got {match_rate:.1f}%"
        return False


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v', '-s']))
