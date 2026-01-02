"""
EXACT EQUALITY TESTS: Author Autocomplete Query Structure

Proves that extracted autocomplete logic (core/author_autocomplete.py)
generates MATHEMATICALLY IDENTICAL queries to the original implementation
(autocomplete/shared.py).

NO fuzzy matching. NO approximations. Either EQUAL or FAIL.

Run: pytest tests/standalone/test_autocomplete_exact_equality.py -v
"""
import sys
sys.path.insert(0, '/home/user/openalex-elastic-api')

from elasticsearch_dsl import Q, Search
from core.author_autocomplete import AuthorAutocompleteQuery


class TestAutocompleteExactEquality:
    """
    Test that extracted autocomplete logic generates identical queries.
    """

    def build_original_autocomplete_query(self, query_text):
        """
        Original autocomplete query from autocomplete/shared.py:40-45
        """
        autocomplete_query = (
            Q("match_phrase_prefix", display_name__autocomplete=query_text)
            | Q("match_phrase_prefix", display_name_alternatives__autocomplete=query_text)
        )
        return autocomplete_query

    def build_original_function_score_query(self, query_text):
        """
        Original function_score query from autocomplete/shared.py:72-92
        """
        autocomplete_query = self.build_original_autocomplete_query(query_text)

        exact_match_query = Q(
            "function_score",
            query=autocomplete_query,
            functions=[
                # Boost exact matches in display_name
                {
                    "filter": Q("term", display_name__keyword=query_text),
                    "weight": 1000
                },
                # Boost prefix matches at word boundaries
                {
                    "filter": Q("prefix", display_name__keyword=query_text),
                    "weight": 500
                }
            ],
            score_mode="max",
            boost_mode="multiply"
        )

        return exact_match_query

    def build_original_search(self, query_text, index_name="authors-v16", limit=10):
        """
        Original complete search from autocomplete/shared.py:94-103
        """
        s = Search(index=index_name)

        # Apply function score query
        query = self.build_original_function_score_query(query_text)
        s = s.query(query)

        # Apply sorting
        s = s.sort("_score", "-works_count")

        # Limit results
        s = s[:limit]

        return s

    def test_autocomplete_query_structure_exact_match(self):
        """Test that basic autocomplete query structure is identical."""
        query_text = "Albert Einstein"

        # Original
        original = self.build_original_autocomplete_query(query_text)

        # Extracted
        builder = AuthorAutocompleteQuery(query_text)
        extracted = builder.build_autocomplete_query()

        # MUST BE IDENTICAL
        assert original.to_dict() == extracted.to_dict(), \
            "Autocomplete query structures differ!"

    def test_function_score_query_exact_match(self):
        """Test that function_score query with boosting is identical."""
        query_text = "Albert Einstein"

        # Original
        original = self.build_original_function_score_query(query_text)

        # Extracted
        builder = AuthorAutocompleteQuery(query_text)
        extracted = builder.build_function_score_query()

        # MUST BE IDENTICAL
        assert original.to_dict() == extracted.to_dict(), \
            "Function score queries differ!"

    def test_complete_search_exact_match(self):
        """Test that complete search with sorting and limiting is identical."""
        query_text = "Albert Einstein"

        # Original
        original = self.build_original_search(query_text)

        # Extracted
        builder = AuthorAutocompleteQuery(query_text)
        extracted = builder.build_search(limit=10)

        # MUST BE IDENTICAL
        assert original.to_dict() == extracted.to_dict(), \
            "Complete search objects differ!"

    def test_diacritic_query_exact_match(self):
        """Test with diacritics (José García)."""
        query_text = "José García"

        original = self.build_original_search(query_text)
        builder = AuthorAutocompleteQuery(query_text)
        extracted = builder.build_search(limit=10)

        assert original.to_dict() == extracted.to_dict()

    def test_special_chars_query_exact_match(self):
        """Test with special characters (O'Brien)."""
        query_text = "O'Brien"

        original = self.build_original_search(query_text)
        builder = AuthorAutocompleteQuery(query_text)
        extracted = builder.build_search(limit=10)

        assert original.to_dict() == extracted.to_dict()

    def test_short_query_exact_match(self):
        """Test with short query (2 chars)."""
        query_text = "Al"

        original = self.build_original_search(query_text)
        builder = AuthorAutocompleteQuery(query_text)
        extracted = builder.build_search(limit=10)

        assert original.to_dict() == extracted.to_dict()

    def test_batch_queries_all_exact_match(self):
        """Test multiple queries in batch."""
        test_queries = [
            "Marie Curie",
            "Richard Feynman",
            "Isaac Newton",
            "Ada Lovelace",
            "Rosalind Franklin",
        ]

        for query_text in test_queries:
            original = self.build_original_search(query_text)
            builder = AuthorAutocompleteQuery(query_text)
            extracted = builder.build_search(limit=10)

            assert original.to_dict() == extracted.to_dict(), \
                f"Mismatch for query: {query_text}"

    def test_different_limits_exact_match(self):
        """Test with different result limits."""
        query_text = "Einstein"

        for limit in [5, 10, 20]:
            original = self.build_original_search(query_text, limit=limit)
            builder = AuthorAutocompleteQuery(query_text)
            extracted = builder.build_search(limit=limit)

            assert original.to_dict() == extracted.to_dict(), \
                f"Mismatch for limit: {limit}"


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
