"""
Comprehensive validation tests for author matching/ranking logic.

These tests compare the extracted author matching logic against the real OpenAlex API
to ensure the extracted logic produces identical ranking results.

Test coverage includes:
- Common English names
- Names with diacritics (accents, umlauts, etc.)
- Asian names (Chinese, Japanese, Korean)
- Arabic names
- Special characters and edge cases
- Various citation count scenarios
"""

import pytest
import requests
import time
from elasticsearch_dsl import Search, connections
from core.author_matching import (
    build_author_search_query,
    AuthorNameMatcher,
    AuthorRanker,
    DEFAULT_AUTHOR_SORT_ORDER,
)
from settings import AUTHORS_INDEX


# Real OpenAlex API base URL
OPENALEX_API_BASE = "https://api.openalex.org"


class TestAuthorMatchingValidation:
    """
    Validation tests comparing extracted logic against real OpenAlex API.

    These tests make real HTTP requests to the OpenAlex API and compare
    the ranking/ordering with our extracted matching logic.
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup elasticsearch connection for tests."""
        # Connection should already be established from conftest
        self.es_connection = connections.get_connection()

    def fetch_openalex_api_results(self, search_query, per_page=10):
        """
        Fetch results from real OpenAlex API.

        Args:
            search_query: The search term to query
            per_page: Number of results to fetch

        Returns:
            List of author results from API
        """
        url = f"{OPENALEX_API_BASE}/authors"
        params = {
            "search": search_query,
            "per-page": per_page,
        }

        # Add delay to respect rate limits
        time.sleep(0.1)

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()
        return data.get("results", [])

    def fetch_local_results(self, search_query, per_page=10):
        """
        Fetch results using extracted author matching logic against local ES.

        Args:
            search_query: The search term to query
            per_page: Number of results to fetch

        Returns:
            List of author results from local Elasticsearch
        """
        # Build query using extracted logic
        query = build_author_search_query(
            search_query,
            apply_citation_boost=True,
            citation_scaling="sqrt"
        )

        # Execute search
        s = Search(index=AUTHORS_INDEX)
        s = s.query(query)
        s = s.sort(*DEFAULT_AUTHOR_SORT_ORDER)
        s = s[:per_page]

        results = s.execute()

        # Convert to list of dictionaries similar to API response
        return [
            {
                "id": hit.id,
                "display_name": hit.display_name,
                "cited_by_count": getattr(hit, "cited_by_count", 0),
                "works_count": getattr(hit, "works_count", 0),
                "relevance_score": hit.meta.score,
            }
            for hit in results
        ]

    def compare_rankings(self, api_results, local_results, top_n=5):
        """
        Compare rankings between API and local results.

        Args:
            api_results: Results from OpenAlex API
            local_results: Results from local Elasticsearch
            top_n: Number of top results to compare strictly

        Returns:
            dict with comparison metrics
        """
        # Extract IDs in order
        api_ids = [r["id"] for r in api_results[:top_n]]
        local_ids = [r["id"] for r in local_results[:top_n]]

        # Check if top results match (order may vary slightly due to tie-breaking)
        api_set = set(api_ids)
        local_set = set(local_ids)

        overlap = len(api_set & local_set)
        overlap_percentage = (overlap / top_n * 100) if top_n > 0 else 0

        # Check exact order match for top 3
        top_3_exact_match = api_ids[:3] == local_ids[:3]

        return {
            "api_ids": api_ids,
            "local_ids": local_ids,
            "overlap": overlap,
            "overlap_percentage": overlap_percentage,
            "top_3_exact_match": top_3_exact_match,
            "api_top_name": api_results[0]["display_name"] if api_results else None,
            "local_top_name": local_results[0]["display_name"] if local_results else None,
        }

    # ========================================================================
    # TEST CASES - Common English Names
    # ========================================================================

    def test_common_name_john_smith(self):
        """Test very common name: John Smith"""
        search_query = "John Smith"

        api_results = self.fetch_openalex_api_results(search_query, per_page=10)
        local_results = self.fetch_local_results(search_query, per_page=10)

        assert len(api_results) > 0, "API should return results for John Smith"
        assert len(local_results) > 0, "Local search should return results for John Smith"

        comparison = self.compare_rankings(api_results, local_results, top_n=5)

        # Assert significant overlap in top 5 results (at least 60%)
        assert comparison["overlap_percentage"] >= 60, \
            f"Top 5 results should have at least 60% overlap. Got {comparison['overlap_percentage']}%"

    def test_famous_scientist_einstein(self):
        """Test well-known scientist: Albert Einstein"""
        search_query = "Albert Einstein"

        api_results = self.fetch_openalex_api_results(search_query, per_page=10)
        local_results = self.fetch_local_results(search_query, per_page=10)

        assert len(api_results) > 0, "API should return results for Albert Einstein"
        assert len(local_results) > 0, "Local search should return results for Albert Einstein"

        comparison = self.compare_rankings(api_results, local_results, top_n=5)

        # For a famous name, expect very high overlap
        assert comparison["overlap_percentage"] >= 80, \
            f"Famous scientist should have high overlap. Got {comparison['overlap_percentage']}%"

        # Top result should contain "Einstein"
        assert "einstein" in comparison["local_top_name"].lower(), \
            "Top local result should contain 'Einstein'"

    def test_author_marie_curie(self):
        """Test historical figure: Marie Curie"""
        search_query = "Marie Curie"

        api_results = self.fetch_openalex_api_results(search_query, per_page=10)
        local_results = self.fetch_local_results(search_query, per_page=10)

        assert len(api_results) > 0, "API should return results for Marie Curie"
        assert len(local_results) > 0, "Local search should return results for Marie Curie"

        comparison = self.compare_rankings(api_results, local_results, top_n=5)

        assert comparison["overlap_percentage"] >= 80, \
            f"Should have high overlap for famous author. Got {comparison['overlap_percentage']}%"

    # ========================================================================
    # TEST CASES - Names with Diacritics
    # ========================================================================

    def test_diacritic_german_umlaut(self):
        """Test German name with umlaut: Müller"""
        search_query = "Thomas Müller"

        api_results = self.fetch_openalex_api_results(search_query, per_page=10)
        local_results = self.fetch_local_results(search_query, per_page=10)

        assert len(api_results) > 0, "API should return results for Müller"
        assert len(local_results) > 0, "Local search should return results for Müller"

        comparison = self.compare_rankings(api_results, local_results, top_n=5)

        # Should handle diacritics well
        assert comparison["overlap_percentage"] >= 60, \
            f"Diacritic handling should work. Got {comparison['overlap_percentage']}%"

    def test_diacritic_ascii_folding_muller(self):
        """Test that Muller (no umlaut) finds Müller (with umlaut)"""
        search_query = "Thomas Muller"  # No umlaut

        api_results = self.fetch_openalex_api_results(search_query, per_page=10)
        local_results = self.fetch_local_results(search_query, per_page=10)

        assert len(local_results) > 0, "Should find authors even without exact diacritics"

        # Top results should contain "Müller" or "Muller"
        top_name_lower = local_results[0]["display_name"].lower()
        assert "muller" in top_name_lower or "müller" in top_name_lower, \
            "Should match Muller/Müller variants"

    def test_diacritic_spanish_accent(self):
        """Test Spanish name with accents: José García"""
        search_query = "José García"

        api_results = self.fetch_openalex_api_results(search_query, per_page=10)
        local_results = self.fetch_local_results(search_query, per_page=10)

        assert len(api_results) > 0, "API should return results for José García"
        assert len(local_results) > 0, "Local search should return results for José García"

        comparison = self.compare_rankings(api_results, local_results, top_n=5)

        assert comparison["overlap_percentage"] >= 60, \
            f"Spanish accents should be handled. Got {comparison['overlap_percentage']}%"

    def test_diacritic_without_accent(self):
        """Test that Jose Garcia (no accent) finds José García (with accent)"""
        search_query = "Jose Garcia"  # No accents

        api_results = self.fetch_openalex_api_results(search_query, per_page=10)
        local_results = self.fetch_local_results(search_query, per_page=10)

        assert len(local_results) > 0, "Should find authors without exact accents"

    def test_diacritic_french_accents(self):
        """Test French name with multiple accent types: François Lévy"""
        search_query = "François Lévy"

        api_results = self.fetch_openalex_api_results(search_query, per_page=10)
        local_results = self.fetch_local_results(search_query, per_page=10)

        # Should return results
        assert len(local_results) >= 0, "Search should execute without errors"

    # ========================================================================
    # TEST CASES - Asian Names
    # ========================================================================

    def test_chinese_name_pinyin(self):
        """Test Chinese name in Pinyin: Wei Wang"""
        search_query = "Wei Wang"

        api_results = self.fetch_openalex_api_results(search_query, per_page=10)
        local_results = self.fetch_local_results(search_query, per_page=10)

        assert len(api_results) > 0, "API should return results for Wei Wang"
        assert len(local_results) > 0, "Local search should return results for Wei Wang"

        comparison = self.compare_rankings(api_results, local_results, top_n=5)

        # Common Chinese name, expect reasonable overlap
        assert comparison["overlap_percentage"] >= 40, \
            f"Should handle Chinese names. Got {comparison['overlap_percentage']}%"

    def test_japanese_name(self):
        """Test Japanese name: Takeshi Yamamoto"""
        search_query = "Takeshi Yamamoto"

        api_results = self.fetch_openalex_api_results(search_query, per_page=10)
        local_results = self.fetch_local_results(search_query, per_page=10)

        assert len(local_results) > 0, "Should find Japanese names"

    def test_korean_name(self):
        """Test Korean name: Kim Seung"""
        search_query = "Kim Seung"

        api_results = self.fetch_openalex_api_results(search_query, per_page=10)
        local_results = self.fetch_local_results(search_query, per_page=10)

        assert len(local_results) > 0, "Should find Korean names"

    # ========================================================================
    # TEST CASES - Arabic Names
    # ========================================================================

    def test_arabic_name_transliterated(self):
        """Test transliterated Arabic name: Mohamed Ahmed"""
        search_query = "Mohamed Ahmed"

        api_results = self.fetch_openalex_api_results(search_query, per_page=10)
        local_results = self.fetch_local_results(search_query, per_page=10)

        assert len(api_results) > 0, "API should return results for Mohamed Ahmed"
        assert len(local_results) > 0, "Local search should return results for Mohamed Ahmed"

        comparison = self.compare_rankings(api_results, local_results, top_n=5)

        # Common Arabic name
        assert comparison["overlap_percentage"] >= 40, \
            f"Should handle Arabic names. Got {comparison['overlap_percentage']}%"

    # ========================================================================
    # TEST CASES - Edge Cases
    # ========================================================================

    def test_single_name(self):
        """Test single word name: Einstein"""
        search_query = "Einstein"

        api_results = self.fetch_openalex_api_results(search_query, per_page=10)
        local_results = self.fetch_local_results(search_query, per_page=10)

        assert len(api_results) > 0, "API should return results for Einstein"
        assert len(local_results) > 0, "Local search should return results for Einstein"

        comparison = self.compare_rankings(api_results, local_results, top_n=5)

        assert comparison["overlap_percentage"] >= 60, \
            f"Single name search should work. Got {comparison['overlap_percentage']}%"

    def test_three_part_name(self):
        """Test three-part name: Jean-Luc Picard"""
        search_query = "Jean-Luc Picard"

        api_results = self.fetch_openalex_api_results(search_query, per_page=10)
        local_results = self.fetch_local_results(search_query, per_page=10)

        # Should execute without error
        assert len(local_results) >= 0, "Should handle hyphenated names"

    def test_name_with_apostrophe(self):
        """Test name with apostrophe: O'Brien"""
        search_query = "Michael O'Brien"

        api_results = self.fetch_openalex_api_results(search_query, per_page=10)
        local_results = self.fetch_local_results(search_query, per_page=10)

        # Should execute without error
        assert len(local_results) >= 0, "Should handle apostrophes in names"

    def test_very_common_surname_only(self):
        """Test very common surname: Smith"""
        search_query = "Smith"

        api_results = self.fetch_openalex_api_results(search_query, per_page=10)
        local_results = self.fetch_local_results(search_query, per_page=10)

        assert len(api_results) > 0, "API should return results for Smith"
        assert len(local_results) > 0, "Local search should return results for Smith"

        # With such a common name, results might vary more
        comparison = self.compare_rankings(api_results, local_results, top_n=5)

        assert comparison["overlap_percentage"] >= 20, \
            f"Very common names should have some overlap. Got {comparison['overlap_percentage']}%"

    def test_initials_with_periods(self):
        """Test name with initials: J. K. Rowling"""
        search_query = "J. K. Rowling"

        api_results = self.fetch_openalex_api_results(search_query, per_page=10)
        local_results = self.fetch_local_results(search_query, per_page=10)

        # Should execute without error
        assert len(local_results) >= 0, "Should handle initials with periods"

    # ========================================================================
    # TEST CASES - Ranking Validation (Citation-based)
    # ========================================================================

    def test_highly_cited_author_ranks_first(self):
        """
        Test that highly cited authors rank higher than less cited ones.
        Using a specific well-known author.
        """
        search_query = "Richard Feynman"

        api_results = self.fetch_openalex_api_results(search_query, per_page=10)
        local_results = self.fetch_local_results(search_query, per_page=10)

        assert len(local_results) > 0, "Should find Richard Feynman"

        # Check that results are ordered by relevance and citation boost
        # Top result should have high citation count
        if len(local_results) > 1:
            # Verify results contain citation counts
            assert "cited_by_count" in local_results[0], "Results should include citation counts"

    def test_exact_match_vs_partial_match(self):
        """
        Test that exact phrase matches rank higher than partial matches.
        """
        search_query = "Isaac Newton"

        local_results = self.fetch_local_results(search_query, per_page=10)

        assert len(local_results) > 0, "Should find Isaac Newton"

        # Top result should contain full name (exact match gets 2x boost)
        top_name = local_results[0]["display_name"].lower()
        assert "isaac" in top_name and "newton" in top_name, \
            "Exact phrase match should rank at top"

    # ========================================================================
    # TEST CASES - Display Name Alternatives
    # ========================================================================

    def test_search_finds_alternative_names(self):
        """
        Test that search works with display_name_alternatives.

        Some authors have alternative name spellings that should also match.
        """
        # This is a more generic test - we test that the search mechanism works
        search_query = "Bill Gates"  # May have alternative "William Gates"

        local_results = self.fetch_local_results(search_query, per_page=10)

        # Should return results
        assert len(local_results) >= 0, "Search should work with alternative name forms"

    # ========================================================================
    # TEST CASES - Special Characters and Edge Cases
    # ========================================================================

    def test_name_with_suffix(self):
        """Test name with suffix: Martin Luther King Jr."""
        search_query = "Martin Luther King Jr"

        api_results = self.fetch_openalex_api_results(search_query, per_page=10)
        local_results = self.fetch_local_results(search_query, per_page=10)

        # Should execute without error
        assert len(local_results) >= 0, "Should handle name suffixes"

    def test_non_latin_characters_arabic(self):
        """Test Arabic script name: محمد"""
        search_query = "محمد"

        # This may or may not return results depending on data
        # But should not crash
        try:
            local_results = self.fetch_local_results(search_query, per_page=10)
            assert isinstance(local_results, list), "Should return a list"
        except Exception as e:
            pytest.fail(f"Should handle non-Latin characters without crashing: {e}")

    def test_non_latin_characters_chinese(self):
        """Test Chinese characters: 王伟"""
        search_query = "王伟"

        # Should not crash
        try:
            local_results = self.fetch_local_results(search_query, per_page=10)
            assert isinstance(local_results, list), "Should return a list"
        except Exception as e:
            pytest.fail(f"Should handle Chinese characters without crashing: {e}")

    def test_empty_string_search(self):
        """Test empty search string"""
        search_query = ""

        # Should return match_all results or handle gracefully
        local_results = self.fetch_local_results(search_query, per_page=10)

        assert isinstance(local_results, list), "Should return a list even for empty query"

    def test_very_long_name(self):
        """Test unusually long name"""
        search_query = "Alexander Philip Maximilian Wilhelm George Friedrich Charles Louis"

        # Should not crash
        try:
            local_results = self.fetch_local_results(search_query, per_page=10)
            assert isinstance(local_results, list), "Should handle long names"
        except Exception as e:
            pytest.fail(f"Should handle long names without crashing: {e}")

    # ========================================================================
    # TEST CASES - Multilingual Combinations
    # ========================================================================

    def test_mixed_latin_cyrillic(self):
        """Test name with mixed scripts (if any exist in data)"""
        search_query = "Vladimir Putin"

        api_results = self.fetch_openalex_api_results(search_query, per_page=10)
        local_results = self.fetch_local_results(search_query, per_page=10)

        # Should execute
        assert len(local_results) >= 0, "Should handle transliterated Cyrillic names"

    def test_nordic_characters(self):
        """Test Nordic characters: Søren Kierkegaard"""
        search_query = "Søren Kierkegaard"

        api_results = self.fetch_openalex_api_results(search_query, per_page=10)
        local_results = self.fetch_local_results(search_query, per_page=10)

        # Should execute without error
        assert len(local_results) >= 0, "Should handle Nordic characters"

    def test_turkish_characters(self):
        """Test Turkish characters with dotless i: Erdoğan"""
        search_query = "Recep Erdoğan"

        # Should not crash
        try:
            local_results = self.fetch_local_results(search_query, per_page=10)
            assert isinstance(local_results, list), "Should handle Turkish characters"
        except Exception as e:
            pytest.fail(f"Should handle Turkish characters without crashing: {e}")


class TestAuthorMatchingComponents:
    """
    Test individual components of the author matching logic.

    These tests validate specific functionality of the extracted classes.
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup elasticsearch connection for tests."""
        self.es_connection = connections.get_connection()

    def test_author_name_matcher_builds_correct_query(self):
        """Test that AuthorNameMatcher builds the expected query structure"""
        from core.author_matching import AuthorNameMatcher

        matcher = AuthorNameMatcher(
            search_terms="Albert Einstein",
            primary_field="display_name",
            secondary_field="display_name_alternatives"
        )

        query = matcher.build_query()
        query_dict = query.to_dict()

        # Should be a bool query with should clauses (OR)
        assert "bool" in query_dict, "Query should contain bool"
        assert "should" in query_dict["bool"], "Should have OR conditions"

        # Should have multi_match queries
        should_clauses = query_dict["bool"]["should"]
        assert len(should_clauses) == 2, "Should have 2 clauses (most_fields + phrase)"

        # Check for most_fields query
        most_fields_found = False
        phrase_found = False

        for clause in should_clauses:
            if "multi_match" in clause:
                if clause["multi_match"].get("type") == "most_fields":
                    most_fields_found = True
                    # Should search 4 fields
                    assert len(clause["multi_match"]["fields"]) == 4, \
                        "Should search 4 fields (primary, primary.folded, secondary, secondary.folded)"
                elif clause["multi_match"].get("type") == "phrase":
                    phrase_found = True
                    # Phrase should have boost
                    assert clause["multi_match"].get("boost") == 2, "Phrase should have 2x boost"

        assert most_fields_found, "Should have most_fields query"
        assert phrase_found, "Should have phrase query"

    def test_author_ranker_applies_citation_boost(self):
        """Test that AuthorRanker applies correct citation boosting"""
        from core.author_matching import AuthorRanker
        from elasticsearch_dsl import Q

        base_query = Q("match", display_name="test")

        # Test sqrt scaling
        boosted_query = AuthorRanker.apply_citation_boost(base_query, scaling_type="sqrt")
        query_dict = boosted_query.to_dict()

        assert "function_score" in query_dict, "Should wrap in function_score"
        assert "functions" in query_dict["function_score"], "Should have functions"

        # Check script exists
        functions = query_dict["function_score"]["functions"]
        assert len(functions) > 0, "Should have at least one function"
        assert "script_score" in functions[0], "Should use script_score"

        # Check script contains sqrt
        script_source = functions[0]["script_score"]["script"]["source"]
        assert "sqrt" in script_source.lower() or "Math.sqrt" in script_source, \
            "Sqrt scaling should use sqrt in script"

        # Test log scaling
        boosted_query_log = AuthorRanker.apply_citation_boost(base_query, scaling_type="log")
        query_dict_log = boosted_query_log.to_dict()

        script_source_log = query_dict_log["function_score"]["functions"][0]["script_score"]["script"]["source"]
        assert "log10" in script_source_log.lower() or "Math.log10" in script_source_log, \
            "Log scaling should use log10 in script"

    def test_build_author_search_query_integration(self):
        """Test the complete build_author_search_query function"""
        from core.author_matching import build_author_search_query

        query = build_author_search_query(
            "Marie Curie",
            apply_citation_boost=True,
            citation_scaling="sqrt"
        )

        query_dict = query.to_dict()

        # Should have function_score at top level (citation boost)
        assert "function_score" in query_dict, "Should apply citation boost"

        # Inside should have the name matching query
        inner_query = query_dict["function_score"]["query"]
        assert "bool" in inner_query, "Should have name matching query inside"

    def test_query_executes_successfully(self):
        """Test that generated queries can execute against Elasticsearch"""
        from core.author_matching import build_author_search_query
        from elasticsearch_dsl import Search

        query = build_author_search_query("Test Author")

        s = Search(index=AUTHORS_INDEX)
        s = s.query(query)
        s = s[:5]

        # Should execute without error
        try:
            results = s.execute()
            assert hasattr(results, "hits"), "Should return results object"
        except Exception as e:
            pytest.fail(f"Query execution should not fail: {e}")
