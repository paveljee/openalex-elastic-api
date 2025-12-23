"""
Author Display Name Matching and Ranking Logic

This module contains reusable logic for matching and ranking authors based on
their display names and other attributes. It provides functionality for:

1. Multi-field name matching (display_name and display_name_alternatives)
2. Diacritic-insensitive search using folded field variants
3. Phrase boosting for exact matches
4. Citation-based ranking/scoring
5. Autocomplete matching with exact/prefix boosting

Extracted from core/search.py and autocomplete/shared.py for reusability.
"""

from elasticsearch_dsl import Q


class AuthorNameMatcher:
    """
    Handles author display name matching with support for:
    - Primary field (display_name) and secondary field (display_name_alternatives)
    - Diacritic-insensitive matching via .folded field variants
    - Phrase query boosting for exact matches
    """

    def __init__(
        self,
        search_terms,
        primary_field="display_name",
        secondary_field="display_name_alternatives",
    ):
        """
        Initialize the author name matcher.

        Args:
            search_terms (str): The search query terms
            primary_field (str): Primary field to search (default: "display_name")
            secondary_field (str): Secondary field to search (default: "display_name_alternatives")
        """
        self.search_terms = search_terms
        self.primary_field = primary_field
        self.secondary_field = secondary_field

    def build_query(self):
        """
        Build an Elasticsearch query for author name matching.

        Searches across display_name and display_name.folded (for diacritic handling),
        as well as display_name_alternatives and display_name_alternatives.folded
        if secondary_field is provided.

        Returns:
            elasticsearch_dsl.Q: Combined query with most_fields and phrase matching
        """
        fields = [self.primary_field, self.primary_field + ".folded"]

        if self.secondary_field:
            fields.extend([self.secondary_field, self.secondary_field + ".folded"])

        # Multi-match query with AND operator across all fields
        most_fields_query = Q(
            "multi_match",
            query=self.search_terms,
            fields=fields,
            operator="and",
            type="most_fields",
        )

        # Phrase query with 2x boost for exact phrase matches
        phrase_query = Q(
            "multi_match",
            query=self.search_terms,
            fields=fields,
            type="phrase",
            boost=2,
        )

        # Combine both queries (OR)
        return most_fields_query | phrase_query


class AuthorRanker:
    """
    Handles citation-based ranking/scoring for authors.
    Boosts authors with higher citation counts using function_score queries.
    """

    @staticmethod
    def apply_citation_boost(query, scaling_type="sqrt"):
        """
        Apply citation-based boosting to a query using cited_by_count.

        The boost is calculated as:
        - Authors with 0 citations: score multiplier = 0.5
        - Authors with citations: score multiplier = 1 + sqrt(cited_by_count)
        - For log scaling: score multiplier = 1 + log10(cited_by_count + 1)

        Args:
            query (elasticsearch_dsl.Q): The base query to boost
            scaling_type (str): Type of scaling - "sqrt" or "log" (default: "sqrt")

        Returns:
            elasticsearch_dsl.Q: Function score query with citation boosting
        """
        if scaling_type == "sqrt":
            script_source = """
            if (doc['cited_by_count'].size() == 0 || doc['cited_by_count'].value == 0) {
                return 0.5;
            } else {
                return 1 + Math.sqrt(doc['cited_by_count'].value);
            }
            """
        elif scaling_type == "log":
            script_source = """
            if (doc['cited_by_count'].size() == 0 || doc['cited_by_count'].value == 0) {
                return 0.5;
            } else {
                return 1 + Math.log10(doc['cited_by_count'].value + 1);
            }
            """
        else:
            raise ValueError(f"Unknown scaling_type: {scaling_type}")

        return Q(
            "function_score",
            functions=[{"script_score": {"script": {"source": script_source}}}],
            query=query,
            boost_mode="multiply",
        )


class AuthorAutocompleteMatcher:
    """
    Handles autocomplete matching for authors with exact and prefix match boosting.
    """

    @staticmethod
    def build_autocomplete_query(
        query_string,
        primary_field="display_name",
        secondary_field="display_name_alternatives",
    ):
        """
        Build autocomplete query for author names.

        Args:
            query_string (str): The autocomplete query string
            primary_field (str): Primary field name (default: "display_name")
            secondary_field (str): Secondary field name (default: "display_name_alternatives")

        Returns:
            elasticsearch_dsl.Q: Autocomplete query matching on __autocomplete subfields
        """
        autocomplete_query = Q(
            "match_phrase_prefix",
            **{f"{primary_field}__autocomplete": query_string}
        )

        if secondary_field:
            autocomplete_query = autocomplete_query | Q(
                "match_phrase_prefix",
                **{f"{secondary_field}__autocomplete": query_string}
            )

        return autocomplete_query

    @staticmethod
    def apply_exact_prefix_boost(
        autocomplete_query,
        query_string,
        primary_field="display_name",
        exact_match_weight=1000,
        prefix_match_weight=500,
    ):
        """
        Apply boosting for exact and prefix matches in autocomplete.

        Args:
            autocomplete_query (elasticsearch_dsl.Q): Base autocomplete query
            query_string (str): The query string to match against
            primary_field (str): Primary field name (default: "display_name")
            exact_match_weight (int): Weight for exact matches (default: 1000)
            prefix_match_weight (int): Weight for prefix matches (default: 500)

        Returns:
            elasticsearch_dsl.Q: Function score query with exact/prefix boosting
        """
        return Q(
            "function_score",
            query=autocomplete_query,
            functions=[
                {
                    "filter": Q("term", **{f"{primary_field}__keyword": query_string}),
                    "weight": exact_match_weight,
                },
                {
                    "filter": Q("prefix", **{f"{primary_field}__keyword": query_string}),
                    "weight": prefix_match_weight,
                },
            ],
            score_mode="max",
            boost_mode="multiply",
        )


def build_author_search_query(
    search_terms,
    apply_citation_boost=True,
    citation_scaling="sqrt",
):
    """
    Build a complete author search query with matching and ranking.

    This is a convenience function that combines name matching with citation boosting.

    Args:
        search_terms (str): The search query terms
        apply_citation_boost (bool): Whether to apply citation-based ranking (default: True)
        citation_scaling (str): Scaling type for citation boost - "sqrt" or "log" (default: "sqrt")

    Returns:
        elasticsearch_dsl.Q: Complete author search query

    Example:
        >>> query = build_author_search_query("Albert Einstein")
        >>> # Use in elasticsearch-dsl Search object
        >>> s = Search().query(query)
    """
    # Build name matching query
    matcher = AuthorNameMatcher(
        search_terms=search_terms,
        primary_field="display_name",
        secondary_field="display_name_alternatives",
    )
    query = matcher.build_query()

    # Apply citation boosting if requested
    if apply_citation_boost:
        ranker = AuthorRanker()
        query = ranker.apply_citation_boost(query, scaling_type=citation_scaling)

    return query


def build_author_autocomplete_query(
    query_string,
    apply_exact_prefix_boost=True,
):
    """
    Build a complete author autocomplete query with optional exact/prefix boosting.

    Args:
        query_string (str): The autocomplete query string
        apply_exact_prefix_boost (bool): Whether to apply exact/prefix match boosting (default: True)

    Returns:
        elasticsearch_dsl.Q: Complete autocomplete query

    Example:
        >>> query = build_author_autocomplete_query("Einst")
        >>> s = Search().query(query)
    """
    autocomplete_matcher = AuthorAutocompleteMatcher()
    query = autocomplete_matcher.build_autocomplete_query(query_string)

    if apply_exact_prefix_boost:
        query = autocomplete_matcher.apply_exact_prefix_boost(query, query_string)

    return query


# Default sorting configuration for author search results
DEFAULT_AUTHOR_SORT_ORDER = ["_score", "-works_count", "id"]

# Field configuration for author name matching
AUTHOR_NAME_FIELDS = {
    "primary": "display_name",
    "secondary": "display_name_alternatives",
    "primary_folded": "display_name.folded",
    "secondary_folded": "display_name_alternatives.folded",
}
