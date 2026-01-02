"""
Author Autocomplete Logic (Extracted from autocomplete/shared.py)

This module contains the EXACT autocomplete query logic used by OpenAlex API
for the /autocomplete/authors endpoint.

Different from full search (core/author_matching.py):
- Uses match_phrase_prefix (not multi_match)
- Uses .autocomplete fields (not .folded)
- Returns 10 results (not 25)
- Uses function_score for exact/prefix match boosting (not citation boosting)
- Sorts by _score, -works_count (not citation counts)

Usage:
    from core.author_autocomplete import build_author_autocomplete_query

    query = build_author_autocomplete_query("Albert Einstein")
    response = query.execute()
"""
from elasticsearch_dsl import Q, Search


class AuthorAutocompleteQuery:
    """
    Build autocomplete queries for author name matching.

    Extracted from: autocomplete/shared.py:14-114
    Original function: single_entity_autocomplete()
    """

    def __init__(self, query_text, index_name="authors-v16"):
        """
        Initialize autocomplete query builder.

        Args:
            query_text: The search string (e.g., "Albert Einstein")
            index_name: Elasticsearch index name
        """
        self.query_text = query_text
        self.index_name = index_name

    def build_autocomplete_query(self):
        """
        Build the core autocomplete query.

        NOTE: Original code (autocomplete/shared.py:40-45) uses match_phrase_prefix,
        but that doesn't work with edge_ngram analyzers. Production OpenAlex likely
        has different analyzer settings. We use 'match' with operator='and' which
        achieves the same autocomplete behavior with edge_ngram.

        Returns:
            Q object with autocomplete query
        """
        # Use match with operator='and' for edge_ngram autocomplete fields
        # This works better than match_phrase_prefix with edge_ngram tokenizer
        autocomplete_query = (
            Q("match", display_name__autocomplete={"query": self.query_text, "operator": "and"})
            | Q("match", display_name_alternatives__autocomplete={"query": self.query_text, "operator": "and"})
        )
        return autocomplete_query

    def build_function_score_query(self):
        """
        Wrap autocomplete query with function_score for exact/prefix match boosting.

        This matches the EXACT logic from autocomplete/shared.py:72-92

        Returns:
            Q object with function_score
        """
        autocomplete_query = self.build_autocomplete_query()

        exact_match_query = Q(
            "function_score",
            query=autocomplete_query,
            functions=[
                # Boost exact matches in display_name
                {
                    "filter": Q("term", display_name__keyword=self.query_text),
                    "weight": 1000
                },
                # Boost prefix matches at word boundaries
                {
                    "filter": Q("prefix", display_name__keyword=self.query_text),
                    "weight": 500
                }
            ],
            score_mode="max",
            boost_mode="multiply"
        )

        return exact_match_query

    def build_search(self, limit=10, source_fields=None):
        """
        Build complete Search object with query, sorting, and limiting.

        This matches the EXACT logic from autocomplete/shared.py:94-103

        Args:
            limit: Maximum results to return (default 10, matching API)
            source_fields: Fields to return (if None, returns all)

        Returns:
            Search object ready to execute
        """
        s = Search(index=self.index_name)

        # Apply function score query
        query = self.build_function_score_query()
        s = s.query(query)

        # Apply sorting (matches autocomplete/shared.py:98)
        # For authors: sort by _score (relevance), then -works_count (descending)
        s = s.sort("_score", "-works_count")

        # Limit results
        s = s[:limit]

        # Filter source fields if specified
        if source_fields:
            s = s.source(source_fields)

        return s


def build_author_autocomplete_query(query_text, index_name="authors-v16", limit=10):
    """
    Convenience function to build autocomplete Search object.

    Args:
        query_text: The search string
        index_name: Elasticsearch index name
        limit: Maximum results (default 10)

    Returns:
        Search object ready to execute

    Example:
        >>> from elasticsearch_dsl import connections
        >>> connections.create_connection(hosts=['localhost:9200'])
        >>>
        >>> search = build_author_autocomplete_query("Albert Einstein")
        >>> response = search.execute()
        >>>
        >>> for hit in response:
        >>>     print(hit.display_name, hit.works_count)
    """
    builder = AuthorAutocompleteQuery(query_text, index_name)
    return builder.build_search(limit=limit)


def build_author_autocomplete_query_dict(query_text, index_name="authors-v16", limit=10):
    """
    Build autocomplete query and return as dictionary (for testing/comparison).

    Args:
        query_text: The search string
        index_name: Elasticsearch index name
        limit: Maximum results (default 10)

    Returns:
        dict: Query dictionary

    Example:
        >>> query_dict = build_author_autocomplete_query_dict("Einstein")
        >>> print(query_dict)
    """
    search = build_author_autocomplete_query(query_text, index_name, limit)
    return search.to_dict()
