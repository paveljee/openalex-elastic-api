"""
Simplified validation tests for author matching logic.

These tests validate that the extracted logic works correctly without
requiring full Flask app initialization.
"""

from core.author_matching import (
    AuthorNameMatcher,
    AuthorRanker,
    build_author_search_query,
    DEFAULT_AUTHOR_SORT_ORDER,
)


class TestAuthorMatchingLogic:
    """Test the author matching logic components without Elasticsearch"""

    def test_author_name_matcher_query_structure(self):
        """Test that AuthorNameMatcher builds correct query structure"""
        matcher = AuthorNameMatcher(
            search_terms="Albert Einstein",
            primary_field="display_name",
            secondary_field="display_name_alternatives"
        )

        query = matcher.build_query()
        query_dict = query.to_dict()

        # Verify query structure
        assert "bool" in query_dict, "Query should be a bool query"
        assert "should" in query_dict["bool"], "Should have OR clauses"

        should_clauses = query_dict["bool"]["should"]
        assert len(should_clauses) == 2, "Should have 2 clauses: most_fields + phrase"

        # Find most_fields and phrase queries
        most_fields_query = None
        phrase_query = None

        for clause in should_clauses:
            if "multi_match" in clause:
                if clause["multi_match"].get("type") == "most_fields":
                    most_fields_query = clause["multi_match"]
                elif clause["multi_match"].get("type") == "phrase":
                    phrase_query = clause["multi_match"]

        # Verify most_fields query
        assert most_fields_query is not None, "Should have most_fields query"
        assert most_fields_query["query"] == "Albert Einstein", "Query text should match"
        assert most_fields_query["operator"] == "and", "Should use AND operator"
        assert len(most_fields_query["fields"]) == 4, \
            "Should search 4 fields: primary, primary.folded, secondary, secondary.folded"

        expected_fields = [
            "display_name",
            "display_name.folded",
            "display_name_alternatives",
            "display_name_alternatives.folded"
        ]
        assert set(most_fields_query["fields"]) == set(expected_fields), \
            "Fields should match expected"

        # Verify phrase query
        assert phrase_query is not None, "Should have phrase query"
        assert phrase_query["query"] == "Albert Einstein", "Phrase query text should match"
        assert phrase_query["boost"] == 2, "Phrase query should have 2x boost"
        assert set(phrase_query["fields"]) == set(expected_fields), \
            "Phrase should search same fields"

    def test_author_name_matcher_without_secondary_field(self):
        """Test matcher with only primary field"""
        matcher = AuthorNameMatcher(
            search_terms="Test",
            primary_field="display_name",
            secondary_field=None
        )

        query = matcher.build_query()
        query_dict = query.to_dict()

        # Extract field lists
        for clause in query_dict["bool"]["should"]:
            if "multi_match" in clause:
                fields = clause["multi_match"]["fields"]
                assert len(fields) == 2, "Without secondary field, should only have 2 fields"
                assert "display_name" in fields
                assert "display_name.folded" in fields

    def test_author_ranker_sqrt_scaling(self):
        """Test AuthorRanker with square root scaling"""
        from elasticsearch_dsl import Q

        base_query = Q("match", display_name="test")
        boosted = AuthorRanker.apply_citation_boost(base_query, scaling_type="sqrt")

        query_dict = boosted.to_dict()

        # Verify structure
        assert "function_score" in query_dict, "Should wrap in function_score"
        assert "query" in query_dict["function_score"], "Should have inner query"
        assert "functions" in query_dict["function_score"], "Should have functions"
        assert "boost_mode" in query_dict["function_score"], "Should have boost_mode"

        # Verify boost mode
        assert query_dict["function_score"]["boost_mode"] == "multiply", \
            "Should multiply scores"

        # Verify script
        functions = query_dict["function_score"]["functions"]
        assert len(functions) == 1, "Should have one function"
        assert "script_score" in functions[0], "Should use script_score"

        script = functions[0]["script_score"]["script"]["source"]
        assert "cited_by_count" in script, "Script should reference cited_by_count"
        assert "sqrt" in script or "Math.sqrt" in script, "Should use sqrt function"
        assert "0.5" in script, "Should have 0.5 for zero citations"

    def test_author_ranker_log_scaling(self):
        """Test AuthorRanker with logarithmic scaling"""
        from elasticsearch_dsl import Q

        base_query = Q("match", display_name="test")
        boosted = AuthorRanker.apply_citation_boost(base_query, scaling_type="log")

        query_dict = boosted.to_dict()

        # Verify script uses log
        script = query_dict["function_score"]["functions"][0]["script_score"]["script"]["source"]
        assert "Math.log" in script, "Should use Math.log (natural log) function"

    def test_author_ranker_invalid_scaling_type(self):
        """Test that invalid scaling type raises error"""
        from elasticsearch_dsl import Q

        base_query = Q("match", display_name="test")

        try:
            AuthorRanker.apply_citation_boost(base_query, scaling_type="invalid")
            # Should have raised ValueError
            assert False, "Should have raised ValueError for invalid scaling_type"
        except ValueError as e:
            assert "Unknown scaling_type" in str(e), "Error message should mention Unknown scaling_type"

    def test_build_author_search_query_with_boost(self):
        """Test complete query builder with citation boost"""
        query = build_author_search_query(
            "Marie Curie",
            apply_citation_boost=True,
            citation_scaling="sqrt"
        )

        query_dict = query.to_dict()

        # Top level should be function_score (citation boost)
        assert "function_score" in query_dict, "Should apply citation boost"

        # Inner query should be the name matching bool query
        inner_query = query_dict["function_score"]["query"]
        assert "bool" in inner_query, "Should have name matching query"

    def test_build_author_search_query_without_boost(self):
        """Test query builder without citation boost"""
        query = build_author_search_query(
            "Isaac Newton",
            apply_citation_boost=False
        )

        query_dict = query.to_dict()

        # Without boost, top level should be bool (name matching only)
        assert "bool" in query_dict, "Should be name matching query"
        # Should NOT have function_score at top level
        assert "function_score" not in query_dict, "Should not apply citation boost"

    def test_build_author_search_query_log_scaling(self):
        """Test query builder with log scaling"""
        query = build_author_search_query(
            "Richard Feynman",
            apply_citation_boost=True,
            citation_scaling="log"
        )

        query_dict = query.to_dict()

        script = query_dict["function_score"]["functions"][0]["script_score"]["script"]["source"]
        assert "Math.log" in script, "Should use Math.log (natural log) scaling"

    def test_default_sort_order(self):
        """Test default sort order constant"""
        assert DEFAULT_AUTHOR_SORT_ORDER == ["_score", "-works_count", "id"], \
            "Default sort order should be score, works_count desc, id"

    def test_query_with_diacritics(self):
        """Test that query is built correctly for names with diacritics"""
        matcher = AuthorNameMatcher(
            search_terms="José García",
            primary_field="display_name",
            secondary_field="display_name_alternatives"
        )

        query = matcher.build_query()
        query_dict = query.to_dict()

        # Verify the search terms are preserved
        for clause in query_dict["bool"]["should"]:
            if "multi_match" in clause:
                assert clause["multi_match"]["query"] == "José García", \
                    "Should preserve diacritics in query"

    def test_query_with_special_characters(self):
        """Test query with special characters like apostrophes"""
        matcher = AuthorNameMatcher(
            search_terms="O'Brien",
            primary_field="display_name",
            secondary_field=None
        )

        query = matcher.build_query()
        query_dict = query.to_dict()

        # Should build without errors
        assert "bool" in query_dict

    def test_empty_search_terms(self):
        """Test matcher with empty search terms"""
        matcher = AuthorNameMatcher(
            search_terms="",
            primary_field="display_name",
            secondary_field="display_name_alternatives"
        )

        query = matcher.build_query()

        # Should still build a valid query
        query_dict = query.to_dict()
        assert isinstance(query_dict, dict), "Should return valid query dict"

    def test_very_long_search_terms(self):
        """Test matcher with very long search terms"""
        long_name = "Alexander Philip Maximilian Wilhelm George Friedrich Charles Louis"

        matcher = AuthorNameMatcher(
            search_terms=long_name,
            primary_field="display_name",
            secondary_field="display_name_alternatives"
        )

        query = matcher.build_query()
        query_dict = query.to_dict()

        # Should handle long names
        for clause in query_dict["bool"]["should"]:
            if "multi_match" in clause:
                assert clause["multi_match"]["query"] == long_name

    def test_query_serialization(self):
        """Test that queries can be serialized to dict and back"""
        query = build_author_search_query("Test Author")

        # Should be able to convert to dict
        query_dict = query.to_dict()
        assert isinstance(query_dict, dict)

        # Dict should be JSON-serializable
        import json
        json_str = json.dumps(query_dict)
        assert isinstance(json_str, str)

        # Should be able to parse back
        parsed = json.loads(json_str)
        assert parsed == query_dict


if __name__ == "__main__":
    """Run tests manually for validation"""
    import sys

    test_class = TestAuthorMatchingLogic()
    test_methods = [
        method for method in dir(test_class)
        if method.startswith("test_")
    ]

    print("=" * 80)
    print(f"Running {len(test_methods)} author matching validation tests")
    print("=" * 80)

    passed = 0
    failed = 0

    for method_name in test_methods:
        try:
            method = getattr(test_class, method_name)
            method()
            print(f"✓ {method_name}")
            passed += 1
        except Exception as e:
            print(f"✗ {method_name}: {e}")
            failed += 1

    print("=" * 80)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 80)

    sys.exit(0 if failed == 0 else 1)
