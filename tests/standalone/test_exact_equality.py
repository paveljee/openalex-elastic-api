"""
EXACT EQUALITY TESTS - No conftest dependencies, pure pytest.

Tests that ORIGINAL code == EXTRACTED code with EXACT equality assertions.
"""
import sys
sys.path.insert(0, '/home/user/openalex-elastic-api')

from elasticsearch_dsl import Q
from core.search import SearchOpenAlex
from core.author_matching import AuthorNameMatcher, AuthorRanker, build_author_search_query


class TestExactEquality:
    """Pure equality tests without ES dependencies"""

    def test_name_query_structure_exact_match(self):
        """Name query structure must be EXACTLY equal"""
        search_terms = 'Albert Einstein'

        # ORIGINAL
        original = SearchOpenAlex(
            search_terms=search_terms,
            secondary_field='display_name_alternatives',
            is_author_name_query=True
        )
        original_query = original.author_name_query()

        # EXTRACTED
        extracted = AuthorNameMatcher(
            search_terms=search_terms,
            primary_field='display_name',
            secondary_field='display_name_alternatives'
        )
        extracted_query = extracted.build_query()

        # ASSERT EXACT EQUALITY
        assert original_query.to_dict() == extracted_query.to_dict(), \
            "Query structures must be EXACTLY equal"

    def test_citation_boost_sqrt_exact_match(self):
        """Citation boost (sqrt) must be EXACTLY equal"""
        base_query = Q('match', display_name='test')

        # ORIGINAL
        original = SearchOpenAlex(search_terms='test')
        original_boosted = original.citation_boost_query(base_query, scaling_type='sqrt')

        # EXTRACTED
        extracted_boosted = AuthorRanker.apply_citation_boost(base_query, scaling_type='sqrt')

        # ASSERT EXACT EQUALITY
        assert original_boosted.to_dict() == extracted_boosted.to_dict(), \
            "Sqrt citation boost must be EXACTLY equal"

    def test_citation_boost_log_exact_match(self):
        """Citation boost (log) must be EXACTLY equal"""
        base_query = Q('match', display_name='test')

        # ORIGINAL
        original = SearchOpenAlex(search_terms='test')
        original_boosted = original.citation_boost_query(base_query, scaling_type='log')

        # EXTRACTED
        extracted_boosted = AuthorRanker.apply_citation_boost(base_query, scaling_type='log')

        # ASSERT EXACT EQUALITY
        orig_dict = original_boosted.to_dict()
        extr_dict = extracted_boosted.to_dict()

        assert orig_dict == extr_dict, \
            f"Log citation boost must be EXACTLY equal.\nOriginal: {orig_dict}\nExtracted: {extr_dict}"

    def test_complete_query_exact_match(self):
        """Complete query (name + citation boost) must be EXACTLY equal"""
        search_terms = 'Marie Curie'

        # ORIGINAL
        original_search = SearchOpenAlex(
            search_terms=search_terms,
            secondary_field='display_name_alternatives',
            is_author_name_query=True
        )
        original_complete = original_search.citation_boost_query(
            original_search.author_name_query()
        )

        # EXTRACTED
        extracted_complete = build_author_search_query(
            search_terms,
            apply_citation_boost=True,
            citation_scaling='sqrt'
        )

        # ASSERT EXACT EQUALITY
        assert original_complete.to_dict() == extracted_complete.to_dict(), \
            "Complete queries must be EXACTLY equal"

    def test_diacritic_query_exact_match(self):
        """Queries with diacritics must be EXACTLY equal"""
        search_terms = 'José García'

        # ORIGINAL
        original = SearchOpenAlex(
            search_terms=search_terms,
            secondary_field='display_name_alternatives',
            is_author_name_query=True
        )
        original_query = original.citation_boost_query(original.author_name_query())

        # EXTRACTED
        extracted_query = build_author_search_query(search_terms)

        # ASSERT EXACT EQUALITY
        assert original_query.to_dict() == extracted_query.to_dict(), \
            "Diacritic queries must be EXACTLY equal"

    def test_special_chars_query_exact_match(self):
        """Queries with special characters must be EXACTLY equal"""
        search_terms = "O'Brien"

        # ORIGINAL
        original = SearchOpenAlex(
            search_terms=search_terms,
            secondary_field='display_name_alternatives',
            is_author_name_query=True
        )
        original_query = original.citation_boost_query(original.author_name_query())

        # EXTRACTED
        extracted_query = build_author_search_query(search_terms)

        # ASSERT EXACT EQUALITY
        assert original_query.to_dict() == extracted_query.to_dict(), \
            "Special character queries must be EXACTLY equal"

    def test_batch_queries_all_exact_match(self):
        """Multiple different queries must ALL be EXACTLY equal"""
        test_queries = [
            'Einstein',
            'John Smith',
            'Wei Wang',
            'Thomas Müller',
            'Mohamed Ahmed',
        ]

        for search_terms in test_queries:
            # ORIGINAL
            original = SearchOpenAlex(
                search_terms=search_terms,
                secondary_field='display_name_alternatives',
                is_author_name_query=True
            )
            original_query = original.citation_boost_query(original.author_name_query())

            # EXTRACTED
            extracted_query = build_author_search_query(search_terms)

            # ASSERT EXACT EQUALITY
            assert original_query.to_dict() == extracted_query.to_dict(), \
                f"Query for '{search_terms}' must be EXACTLY equal"

    def test_without_citation_boost_exact_match(self):
        """Queries without citation boost must be EXACTLY equal"""
        search_terms = 'Isaac Newton'

        # ORIGINAL (just name query, no boost)
        original = SearchOpenAlex(
            search_terms=search_terms,
            secondary_field='display_name_alternatives',
            is_author_name_query=True
        )
        original_query = original.author_name_query()

        # EXTRACTED
        extracted_query = build_author_search_query(
            search_terms,
            apply_citation_boost=False
        )

        # ASSERT EXACT EQUALITY
        assert original_query.to_dict() == extracted_query.to_dict(), \
            "Queries without citation boost must be EXACTLY equal"


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v']))
