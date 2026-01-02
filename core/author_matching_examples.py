"""
Author Matching Module - Usage Examples

This file demonstrates practical usage scenarios for the author_matching module.
These examples show how to use the extracted logic in real applications.
"""

from elasticsearch_dsl import Search
from core.author_matching import (
    AuthorNameMatcher,
    AuthorRanker,
    AuthorAutocompleteMatcher,
    build_author_search_query,
    build_author_autocomplete_query,
    DEFAULT_AUTHOR_SORT_ORDER,
    AUTHOR_NAME_FIELDS,
)


# ============================================================================
# Example 1: Simple Author Search
# ============================================================================

def simple_author_search(es_client, search_terms):
    """
    Perform a simple author search with default settings.

    This uses citation boosting and searches both display_name and
    display_name_alternatives fields.
    """
    query = build_author_search_query(search_terms)

    s = Search(using=es_client, index="authors")
    s = s.query(query)
    s = s.sort(*DEFAULT_AUTHOR_SORT_ORDER)

    results = s[:10].execute()

    return [
        {
            "id": hit.id,
            "display_name": hit.display_name,
            "cited_by_count": hit.cited_by_count,
            "score": hit.meta.score,
        }
        for hit in results
    ]


# ============================================================================
# Example 2: Author Search Without Citation Boost
# ============================================================================

def search_by_name_only(es_client, search_terms):
    """
    Search authors by name only, without citation-based ranking.

    Useful when you want pure relevance matching without popularity bias.
    """
    query = build_author_search_query(
        search_terms,
        apply_citation_boost=False
    )

    s = Search(using=es_client, index="authors")
    s = s.query(query)

    return s.execute()


# ============================================================================
# Example 3: Custom Fields and Logarithmic Scaling
# ============================================================================

def advanced_author_search(es_client, search_terms):
    """
    Advanced search with custom configuration using individual classes.

    Uses logarithmic citation scaling instead of square root.
    """
    # Build name matching query
    matcher = AuthorNameMatcher(
        search_terms=search_terms,
        primary_field="display_name",
        secondary_field="display_name_alternatives",
    )
    name_query = matcher.build_query()

    # Apply logarithmic citation boosting
    ranker = AuthorRanker()
    final_query = ranker.apply_citation_boost(name_query, scaling_type="log")

    s = Search(using=es_client, index="authors")
    s = s.query(final_query)
    s = s.sort("_score", "-works_count")

    return s.execute()


# ============================================================================
# Example 4: Autocomplete Search
# ============================================================================

def author_autocomplete(es_client, partial_name):
    """
    Provide autocomplete suggestions for author names.

    Exact matches and prefix matches are heavily boosted.
    """
    query = build_author_autocomplete_query(partial_name)

    s = Search(using=es_client, index="authors")
    s = s.query(query)
    s = s.source(["display_name", "display_name_alternatives", "works_count"])

    results = s[:10].execute()

    return [
        {
            "display_name": hit.display_name,
            "alternatives": getattr(hit, "display_name_alternatives", []),
            "works_count": hit.works_count,
        }
        for hit in results
    ]


# ============================================================================
# Example 5: Custom Autocomplete with Adjusted Weights
# ============================================================================

def custom_autocomplete(es_client, partial_name):
    """
    Autocomplete with custom exact/prefix match weights.
    """
    matcher = AuthorAutocompleteMatcher()

    # Build base autocomplete query
    base_query = matcher.build_autocomplete_query(partial_name)

    # Apply custom boosting weights
    boosted_query = matcher.apply_exact_prefix_boost(
        base_query,
        partial_name,
        exact_match_weight=2000,  # Higher weight for exact matches
        prefix_match_weight=1000,  # Higher weight for prefix matches
    )

    s = Search(using=es_client, index="authors")
    s = s.query(boosted_query)

    return s.execute()


# ============================================================================
# Example 6: Pagination with Author Search
# ============================================================================

def paginated_author_search(es_client, search_terms, page=1, per_page=25):
    """
    Paginated author search results.
    """
    query = build_author_search_query(search_terms)

    s = Search(using=es_client, index="authors")
    s = s.query(query)
    s = s.sort(*DEFAULT_AUTHOR_SORT_ORDER)

    # Calculate offset
    start = (page - 1) * per_page
    end = start + per_page

    s = s[start:end]
    results = s.execute()

    return {
        "total": results.hits.total.value,
        "page": page,
        "per_page": per_page,
        "results": [
            {
                "id": hit.id,
                "display_name": hit.display_name,
                "cited_by_count": getattr(hit, "cited_by_count", 0),
                "works_count": getattr(hit, "works_count", 0),
                "score": hit.meta.score,
            }
            for hit in results
        ],
    }


# ============================================================================
# Example 7: Multi-Author Search (Batch Processing)
# ============================================================================

def batch_author_search(es_client, author_names):
    """
    Search for multiple authors in a single batch operation.

    Returns a dictionary mapping search terms to results.
    """
    results = {}

    for name in author_names:
        query = build_author_search_query(name)
        s = Search(using=es_client, index="authors")
        s = s.query(query)
        s = s[:5]  # Top 5 results per author

        hits = s.execute()
        results[name] = [
            {
                "display_name": hit.display_name,
                "id": hit.id,
                "score": hit.meta.score,
            }
            for hit in hits
        ]

    return results


# ============================================================================
# Example 8: Filter by Institution + Name Search
# ============================================================================

def search_author_by_institution(es_client, author_name, institution_id):
    """
    Search for an author by name, filtered by institution affiliation.

    Combines name matching with institutional filters.
    """
    from elasticsearch_dsl import Q

    # Build name query
    name_query = build_author_search_query(author_name)

    # Add institution filter
    institution_filter = Q("term", **{"last_known_institution.id": institution_id})

    # Combine with boolean query
    combined_query = Q("bool", must=name_query, filter=institution_filter)

    s = Search(using=es_client, index="authors")
    s = s.query(combined_query)

    return s.execute()


# ============================================================================
# Example 9: Diacritic-Insensitive Search Demonstration
# ============================================================================

def demonstrate_diacritic_handling(es_client):
    """
    Demonstrate how the matcher handles diacritics.

    Searches with and without diacritics should return the same results.
    """
    search_terms = [
        "Müller",      # With umlaut
        "Muller",      # Without umlaut
        "José García", # With accents
        "Jose Garcia", # Without accents
    ]

    results = {}
    for term in search_terms:
        query = build_author_search_query(term)
        s = Search(using=es_client, index="authors")
        s = s.query(query)[:3]

        hits = s.execute()
        results[term] = [hit.display_name for hit in hits]

    return results


# ============================================================================
# Example 10: Debugging - Inspect Query Structure
# ============================================================================

def inspect_query_structure(search_terms):
    """
    Inspect the generated Elasticsearch query structure.

    Useful for debugging and understanding how queries are built.
    """
    # Build the query
    query = build_author_search_query(search_terms)

    # Convert to dictionary to see structure
    query_dict = query.to_dict()

    print("=" * 80)
    print(f"Query for: '{search_terms}'")
    print("=" * 80)
    print(f"\nQuery Structure:\n{query_dict}")
    print("\n" + "=" * 80)

    # Also show individual components
    matcher = AuthorNameMatcher(search_terms)
    name_query = matcher.build_query()

    print("\nName Matching Query (before citation boost):")
    print(name_query.to_dict())

    return query_dict


# ============================================================================
# Example 11: Integration with Flask/FastAPI Endpoint
# ============================================================================

def flask_author_search_endpoint(request_params):
    """
    Example integration with a Flask or FastAPI endpoint.

    Expected params:
    - q: search query
    - page: page number (default: 1)
    - per_page: results per page (default: 25)
    - boost: whether to apply citation boost (default: true)
    """
    search_terms = request_params.get("q", "")
    page = int(request_params.get("page", 1))
    per_page = int(request_params.get("per_page", 25))
    apply_boost = request_params.get("boost", "true").lower() == "true"

    if not search_terms:
        return {"error": "Missing 'q' parameter"}, 400

    # Build query
    query = build_author_search_query(
        search_terms,
        apply_citation_boost=apply_boost,
    )

    # Note: You'd get es_client from your application context
    # s = Search(using=es_client, index="authors")
    # s = s.query(query)
    # ... pagination and execution

    return {
        "meta": {
            "count": per_page,
            "page": page,
            "query": search_terms,
        },
        # "results": [...],
    }


# ============================================================================
# Example 12: Field Configuration Reference
# ============================================================================

def show_field_configuration():
    """
    Display the field configuration used by the matcher.
    """
    print("Author Name Matching Fields:")
    print("-" * 40)
    for key, value in AUTHOR_NAME_FIELDS.items():
        print(f"{key:20} -> {value}")

    print("\nDefault Sort Order:")
    print("-" * 40)
    for idx, field in enumerate(DEFAULT_AUTHOR_SORT_ORDER, 1):
        print(f"{idx}. {field}")


# ============================================================================
# Main: Run Examples
# ============================================================================

if __name__ == "__main__":
    print("Author Matching Module - Usage Examples")
    print("=" * 80)
    print("\nThis file contains example functions demonstrating how to use")
    print("the author_matching module in various scenarios.")
    print("\nTo use these examples, you'll need an Elasticsearch client:")
    print("  from elasticsearch import Elasticsearch")
    print("  es_client = Elasticsearch(['localhost:9200'])")
    print("\nThen call any of the example functions with your es_client.")
    print("\n" + "=" * 80)

    # Show configuration
    show_field_configuration()

    # Show query structure for a sample search
    print("\n")
    inspect_query_structure("Albert Einstein")
