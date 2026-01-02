"""
REAL validation tests for author matching logic.

These tests compare the EXTRACTED logic against the ORIGINAL code path
using the SAME Elasticsearch data and assert EXACT EQUALITY.

No fuzzy matching bullshit. If the extracted logic doesn't produce
identical results to the original, the test FAILS.
"""

import pytest
from elasticsearch_dsl import Search, connections

# ORIGINAL CODE PATH
from core.search import SearchOpenAlex

# EXTRACTED CODE PATH
from core.author_matching import (
    AuthorNameMatcher,
    AuthorRanker,
    build_author_search_query,
)

from settings import AUTHORS_INDEX


class TestAuthorMatchingExactEquality:
    """
    Compare extracted logic against original code on SAME data.
    Assert EXACT EQUALITY - no fuzzy matching.
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup elasticsearch connection."""
        self.es_connection = connections.get_connection()

    def execute_query(self, query, limit=25):
        """Execute query and return results."""
        s = Search(index=AUTHORS_INDEX)
        s = s.query(query)
        s = s.sort("_score", "-works_count", "id")
        s = s[:limit]

        results = s.execute()

        return [
            {
                "id": hit.id,
                "display_name": hit.display_name,
                "score": hit.meta.score,
                "cited_by_count": getattr(hit, "cited_by_count", 0),
                "works_count": getattr(hit, "works_count", 0),
            }
            for hit in results
        ]

    def test_query_structure_exact_match(self):
        """
        Test that extracted query structure is EXACTLY the same as original.

        Compare the Elasticsearch DSL query dictionaries.
        """
        search_terms = "Albert Einstein"

        # ORIGINAL code path
        original_matcher = SearchOpenAlex(
            search_terms=search_terms,
            secondary_field="display_name_alternatives",
            is_author_name_query=True,
        )
        original_name_query = original_matcher.author_name_query()

        # EXTRACTED code path
        extracted_matcher = AuthorNameMatcher(
            search_terms=search_terms,
            primary_field="display_name",
            secondary_field="display_name_alternatives",
        )
        extracted_name_query = extracted_matcher.build_query()

        # Convert to dicts
        original_dict = original_name_query.to_dict()
        extracted_dict = extracted_name_query.to_dict()

        # Assert EXACT equality
        assert original_dict == extracted_dict, \
            f"Query structures must be EXACTLY equal.\nOriginal: {original_dict}\nExtracted: {extracted_dict}"

    def test_citation_boost_query_exact_match(self):
        """
        Test that citation boost query structure is EXACTLY the same.
        """
        from elasticsearch_dsl import Q

        base_query = Q("match", display_name="test")

        # ORIGINAL code path
        original_matcher = SearchOpenAlex(search_terms="test")
        original_boosted = original_matcher.citation_boost_query(base_query, scaling_type="sqrt")

        # EXTRACTED code path
        extracted_boosted = AuthorRanker.apply_citation_boost(base_query, scaling_type="sqrt")

        # Convert to dicts
        original_dict = original_boosted.to_dict()
        extracted_dict = extracted_boosted.to_dict()

        # Assert EXACT equality
        assert original_dict == extracted_dict, \
            f"Citation boost queries must be EXACTLY equal.\nOriginal: {original_dict}\nExtracted: {extracted_dict}"

    def test_complete_query_exact_match(self):
        """
        Test complete query (name matching + citation boost) is EXACTLY the same.
        """
        search_terms = "Marie Curie"

        # ORIGINAL code path
        original_search = SearchOpenAlex(
            search_terms=search_terms,
            secondary_field="display_name_alternatives",
            is_author_name_query=True,
        )
        original_name_query = original_search.author_name_query()
        original_complete_query = original_search.citation_boost_query(original_name_query)

        # EXTRACTED code path
        extracted_complete_query = build_author_search_query(
            search_terms,
            apply_citation_boost=True,
            citation_scaling="sqrt"
        )

        # Convert to dicts
        original_dict = original_complete_query.to_dict()
        extracted_dict = extracted_complete_query.to_dict()

        # Assert EXACT equality
        assert original_dict == extracted_dict, \
            f"Complete queries must be EXACTLY equal.\nOriginal: {original_dict}\nExtracted: {extracted_dict}"

    def test_ranking_exact_equality_simple_name(self):
        """
        Test that ranking order is EXACTLY the same for a simple name.

        Same query, same ES instance, same data = MUST produce same results.
        """
        search_terms = "Einstein"

        # ORIGINAL code path
        original_search = SearchOpenAlex(
            search_terms=search_terms,
            secondary_field="display_name_alternatives",
            is_author_name_query=True,
        )
        original_name_query = original_search.author_name_query()
        original_query = original_search.citation_boost_query(original_name_query)

        # EXTRACTED code path
        extracted_query = build_author_search_query(search_terms)

        # Execute both
        original_results = self.execute_query(original_query, limit=25)
        extracted_results = self.execute_query(extracted_query, limit=25)

        # Extract IDs in order
        original_ids = [r["id"] for r in original_results]
        extracted_ids = [r["id"] for r in extracted_results]

        # Assert EXACT equality of ranking order
        assert original_ids == extracted_ids, \
            f"Ranking order must be EXACTLY the same.\nOriginal: {original_ids[:5]}\nExtracted: {extracted_ids[:5]}"

        # Assert scores are exactly the same
        original_scores = [r["score"] for r in original_results]
        extracted_scores = [r["score"] for r in extracted_results]

        assert original_scores == extracted_scores, \
            f"Scores must be EXACTLY the same.\nOriginal: {original_scores[:5]}\nExtracted: {extracted_scores[:5]}"

    def test_ranking_exact_equality_two_words(self):
        """
        Test exact ranking equality for two-word name.
        """
        search_terms = "John Smith"

        # ORIGINAL
        original_search = SearchOpenAlex(
            search_terms=search_terms,
            secondary_field="display_name_alternatives",
            is_author_name_query=True,
        )
        original_query = original_search.citation_boost_query(
            original_search.author_name_query()
        )

        # EXTRACTED
        extracted_query = build_author_search_query(search_terms)

        # Execute
        original_results = self.execute_query(original_query, limit=25)
        extracted_results = self.execute_query(extracted_query, limit=25)

        # Assert EXACT equality
        original_ids = [r["id"] for r in original_results]
        extracted_ids = [r["id"] for r in extracted_results]

        assert original_ids == extracted_ids, \
            "Ranking must be EXACTLY the same for two-word names"

    def test_ranking_exact_equality_with_diacritics(self):
        """
        Test exact ranking equality for name with diacritics.
        """
        search_terms = "José García"

        # ORIGINAL
        original_search = SearchOpenAlex(
            search_terms=search_terms,
            secondary_field="display_name_alternatives",
            is_author_name_query=True,
        )
        original_query = original_search.citation_boost_query(
            original_search.author_name_query()
        )

        # EXTRACTED
        extracted_query = build_author_search_query(search_terms)

        # Execute
        original_results = self.execute_query(original_query, limit=25)
        extracted_results = self.execute_query(extracted_query, limit=25)

        # Assert EXACT equality
        original_ids = [r["id"] for r in original_results]
        extracted_ids = [r["id"] for r in extracted_results]

        assert original_ids == extracted_ids, \
            "Ranking must be EXACTLY the same for names with diacritics"

    def test_ranking_exact_equality_three_words(self):
        """
        Test exact ranking equality for three-word name.
        """
        search_terms = "Martin Luther King"

        # ORIGINAL
        original_search = SearchOpenAlex(
            search_terms=search_terms,
            secondary_field="display_name_alternatives",
            is_author_name_query=True,
        )
        original_query = original_search.citation_boost_query(
            original_search.author_name_query()
        )

        # EXTRACTED
        extracted_query = build_author_search_query(search_terms)

        # Execute
        original_results = self.execute_query(original_query, limit=25)
        extracted_results = self.execute_query(extracted_query, limit=25)

        # Assert EXACT equality
        original_ids = [r["id"] for r in original_results]
        extracted_ids = [r["id"] for r in extracted_results]

        assert original_ids == extracted_ids, \
            "Ranking must be EXACTLY the same for three-word names"

    def test_ranking_exact_equality_asian_name(self):
        """
        Test exact ranking equality for Asian name.
        """
        search_terms = "Wei Wang"

        # ORIGINAL
        original_search = SearchOpenAlex(
            search_terms=search_terms,
            secondary_field="display_name_alternatives",
            is_author_name_query=True,
        )
        original_query = original_search.citation_boost_query(
            original_search.author_name_query()
        )

        # EXTRACTED
        extracted_query = build_author_search_query(search_terms)

        # Execute
        original_results = self.execute_query(original_query, limit=25)
        extracted_results = self.execute_query(extracted_query, limit=25)

        # Assert EXACT equality
        original_ids = [r["id"] for r in original_results]
        extracted_ids = [r["id"] for r in extracted_results]

        assert original_ids == extracted_ids, \
            "Ranking must be EXACTLY the same for Asian names"

    def test_ranking_exact_equality_special_chars(self):
        """
        Test exact ranking equality for name with special characters.
        """
        search_terms = "O'Brien"

        # ORIGINAL
        original_search = SearchOpenAlex(
            search_terms=search_terms,
            secondary_field="display_name_alternatives",
            is_author_name_query=True,
        )
        original_query = original_search.citation_boost_query(
            original_search.author_name_query()
        )

        # EXTRACTED
        extracted_query = build_author_search_query(search_terms)

        # Execute
        original_results = self.execute_query(original_query, limit=25)
        extracted_results = self.execute_query(extracted_query, limit=25)

        # Assert EXACT equality
        original_ids = [r["id"] for r in original_results]
        extracted_ids = [r["id"] for r in extracted_results]

        assert original_ids == extracted_ids, \
            "Ranking must be EXACTLY the same for names with special characters"

    def test_log_scaling_exact_equality(self):
        """
        Test that log scaling produces exactly the same results.
        """
        search_terms = "Richard Feynman"

        # ORIGINAL with log scaling
        original_search = SearchOpenAlex(
            search_terms=search_terms,
            secondary_field="display_name_alternatives",
            is_author_name_query=True,
        )
        original_query = original_search.citation_boost_query(
            original_search.author_name_query(),
            scaling_type="log"
        )

        # EXTRACTED with log scaling
        extracted_query = build_author_search_query(
            search_terms,
            citation_scaling="log"
        )

        # Execute
        original_results = self.execute_query(original_query, limit=25)
        extracted_results = self.execute_query(extracted_query, limit=25)

        # Assert EXACT equality
        original_ids = [r["id"] for r in original_results]
        extracted_ids = [r["id"] for r in extracted_results]

        assert original_ids == extracted_ids, \
            "Ranking with log scaling must be EXACTLY the same"

    def test_no_citation_boost_exact_equality(self):
        """
        Test that queries without citation boost are exactly equal.
        """
        search_terms = "Isaac Newton"

        # ORIGINAL without boost (just name query)
        original_search = SearchOpenAlex(
            search_terms=search_terms,
            secondary_field="display_name_alternatives",
            is_author_name_query=True,
        )
        original_query = original_search.author_name_query()

        # EXTRACTED without boost
        extracted_query = build_author_search_query(
            search_terms,
            apply_citation_boost=False
        )

        # Execute
        original_results = self.execute_query(original_query, limit=25)
        extracted_results = self.execute_query(extracted_query, limit=25)

        # Assert EXACT equality
        original_ids = [r["id"] for r in original_results]
        extracted_ids = [r["id"] for r in extracted_results]

        assert original_ids == extracted_ids, \
            "Ranking without citation boost must be EXACTLY the same"

    def test_multiple_queries_batch(self):
        """
        Test multiple different queries all produce exact equality.
        """
        test_queries = [
            "Albert Einstein",
            "Marie Curie",
            "Thomas Müller",
            "Wei Wang",
            "Mohamed Ahmed",
        ]

        for search_terms in test_queries:
            # ORIGINAL
            original_search = SearchOpenAlex(
                search_terms=search_terms,
                secondary_field="display_name_alternatives",
                is_author_name_query=True,
            )
            original_query = original_search.citation_boost_query(
                original_search.author_name_query()
            )

            # EXTRACTED
            extracted_query = build_author_search_query(search_terms)

            # Execute
            original_results = self.execute_query(original_query, limit=10)
            extracted_results = self.execute_query(extracted_query, limit=10)

            # Assert EXACT equality for each query
            original_ids = [r["id"] for r in original_results]
            extracted_ids = [r["id"] for r in extracted_results]

            assert original_ids == extracted_ids, \
                f"Ranking for '{search_terms}' must be EXACTLY the same.\nOriginal: {original_ids}\nExtracted: {extracted_ids}"

    def test_top_100_results_exact_equality(self):
        """
        Test that even top 100 results are exactly equal (not just top 10).
        """
        search_terms = "Smith"

        # ORIGINAL
        original_search = SearchOpenAlex(
            search_terms=search_terms,
            secondary_field="display_name_alternatives",
            is_author_name_query=True,
        )
        original_query = original_search.citation_boost_query(
            original_search.author_name_query()
        )

        # EXTRACTED
        extracted_query = build_author_search_query(search_terms)

        # Execute with 100 results
        original_results = self.execute_query(original_query, limit=100)
        extracted_results = self.execute_query(extracted_query, limit=100)

        # Assert EXACT equality for all 100
        original_ids = [r["id"] for r in original_results]
        extracted_ids = [r["id"] for r in extracted_results]

        assert len(original_ids) == len(extracted_ids), \
            "Must return same number of results"

        assert original_ids == extracted_ids, \
            "All 100 results must be in EXACTLY the same order"


if __name__ == "__main__":
    """Run tests standalone to verify exact equality."""
    import sys

    # Check imports work
    try:
        from core.search import SearchOpenAlex
        from core.author_matching import build_author_search_query
        print("✓ Imports successful")
    except ImportError as e:
        print(f"✗ Import error: {e}")
        sys.exit(1)

    print("\nThese tests assert EXACT EQUALITY between:")
    print("  - ORIGINAL: core/search.py SearchOpenAlex")
    print("  - EXTRACTED: core/author_matching.py")
    print("\nNo fuzzy matching. If extracted != original, tests FAIL.")
    print("\nRun with: pytest tests/functional/test_author_matching_exact.py -v")
