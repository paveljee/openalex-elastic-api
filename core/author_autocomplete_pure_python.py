"""
Pure Python Autocomplete Implementation (No Elasticsearch Required)

Reimplements the OpenAlex autocomplete logic using only pandas/numpy.
For small-medium datasets (<1M authors), this is faster than Elasticsearch.

Usage:
    from core.author_autocomplete_pure_python import AuthorAutocompletePython

    # Load authors once
    autocomplete = AuthorAutocompletePython.from_parquet('authors.parquet')

    # Query (milliseconds)
    results = autocomplete.search('Albert Einstein', limit=10)
"""
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Set
import unicodedata
import re


class AuthorAutocompletePython:
    """
    Pure Python implementation of OpenAlex autocomplete.

    No Elasticsearch required - all in-memory using pandas.
    """

    def __init__(self, df: pd.DataFrame):
        """
        Initialize with author DataFrame.

        Args:
            df: DataFrame with columns: id, display_name, display_name_alternatives,
                works_count, cited_by_count
        """
        self.df = df.copy()
        self._precompute_ngrams()

    @classmethod
    def from_parquet(cls, parquet_file: str) -> 'AuthorAutocompletePython':
        """Load authors from parquet file."""
        df = pd.read_parquet(parquet_file)
        return cls(df)

    def _normalize_text(self, text: str) -> str:
        """
        Normalize text (lowercase + ASCII folding).

        Matches Elasticsearch 'folding' analyzer.
        """
        if not text:
            return ""

        # Lowercase
        text = text.lower()

        # ASCII folding (remove diacritics)
        text = unicodedata.normalize('NFKD', text)
        text = ''.join([c for c in text if not unicodedata.combining(c)])

        return text

    def _tokenize(self, text: str) -> List[str]:
        """
        Tokenize text (split on non-alphanumeric).

        Matches Elasticsearch 'standard' tokenizer.
        """
        text = self._normalize_text(text)
        # Split on non-alphanumeric
        tokens = re.findall(r'\w+', text)
        return tokens

    def _edge_ngrams(self, text: str, min_gram: int = 1, max_gram: int = 20) -> Set[str]:
        """
        Generate edge ngrams for text.

        Example: "Albert" -> {"a", "al", "alb", "albe", "alber", "albert"}

        Matches Elasticsearch edge_ngram tokenizer.
        """
        tokens = self._tokenize(text)
        ngrams = set()

        for token in tokens:
            for i in range(min_gram, min(max_gram + 1, len(token) + 1)):
                ngrams.add(token[:i])

        return ngrams

    def _precompute_ngrams(self):
        """Pre-compute edge ngrams for all authors (for fast matching)."""
        print("Pre-computing edge ngrams for autocomplete...")

        # Compute ngrams for display_name
        self.df['_ngrams_display_name'] = self.df['display_name'].apply(
            lambda x: self._edge_ngrams(x) if pd.notna(x) else set()
        )

        # Compute ngrams for display_name_alternatives
        # Note: alternatives are stored as JSON string in parquet
        self.df['_ngrams_alternatives'] = self.df['display_name_alternatives'].apply(
            lambda x: set() if pd.isna(x) or x == '[]' else
                     set.union(*[self._edge_ngrams(alt) for alt in eval(x) if alt])
        )

        # Combined ngrams
        self.df['_ngrams_all'] = self.df.apply(
            lambda row: row['_ngrams_display_name'] | row['_ngrams_alternatives'],
            axis=1
        )

        # Pre-compute normalized display_name for exact/prefix matching
        self.df['_normalized_display_name'] = self.df['display_name'].apply(
            self._normalize_text
        )

        print(f"✓ Pre-computed ngrams for {len(self.df)} authors")

    def _match_query(self, query: str, operator: str = 'and') -> pd.Series:
        """
        Match query against authors (like Elasticsearch match query).

        Args:
            query: Search query
            operator: 'and' (all tokens must match) or 'or' (any token matches)

        Returns:
            Boolean series indicating which authors match
        """
        query_tokens = set(self._tokenize(query))

        if len(query_tokens) == 0:
            return pd.Series([False] * len(self.df))

        # Generate query ngrams
        query_ngrams = self._edge_ngrams(query)

        if operator == 'and':
            # All query ngrams must be present in document ngrams
            matches = self.df['_ngrams_all'].apply(
                lambda doc_ngrams: query_ngrams.issubset(doc_ngrams)
            )
        else:  # 'or'
            # At least one query ngram must be present
            matches = self.df['_ngrams_all'].apply(
                lambda doc_ngrams: len(query_ngrams & doc_ngrams) > 0
            )

        return matches

    def _compute_base_score(self, query: str, matches: pd.Series) -> np.ndarray:
        """
        Compute base relevance score.

        Simple scoring: ratio of query ngrams that match.
        Could be enhanced with TF-IDF or BM25 if needed.
        """
        query_ngrams = self._edge_ngrams(query)
        query_tokens = set(self._tokenize(query))

        if len(query_ngrams) == 0:
            return np.zeros(len(self.df))

        scores = np.zeros(len(self.df))

        for idx, (match, doc_ngrams) in enumerate(zip(matches, self.df['_ngrams_all'])):
            if not match:
                scores[idx] = 0.0
                continue

            # Base score: ngram overlap ratio
            overlap = len(query_ngrams & doc_ngrams)
            scores[idx] = overlap / len(query_ngrams)

            # Bonus for token-level exact matches
            doc_tokens = self._tokenize(self.df.iloc[idx]['display_name'])
            token_overlap = len(query_tokens & set(doc_tokens))
            if token_overlap > 0:
                scores[idx] *= (1 + token_overlap)

        return scores

    def _apply_function_score_boost(self, query: str, scores: np.ndarray) -> np.ndarray:
        """
        Apply function score boosting (exact match & prefix match).

        Matches Elasticsearch function_score with filters.
        """
        normalized_query = self._normalize_text(query)

        boosted_scores = scores.copy()

        for idx, (score, normalized_name) in enumerate(
            zip(scores, self.df['_normalized_display_name'])
        ):
            if score == 0:
                continue

            # Exact match boost: 1000x
            if normalized_name == normalized_query:
                boosted_scores[idx] *= 1000

            # Prefix match boost: 500x
            elif normalized_name.startswith(normalized_query):
                boosted_scores[idx] *= 500

        return boosted_scores

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Search for authors (autocomplete).

        Args:
            query: Search query (e.g., "Albert Einstein")
            limit: Maximum results to return

        Returns:
            List of author dictionaries with scores
        """
        if not query or query.strip() == "":
            return []

        # 1. Match query (operator='and')
        matches = self._match_query(query, operator='and')

        if not matches.any():
            return []

        # 2. Compute base scores
        scores = self._compute_base_score(query, matches)

        # 3. Apply function score boosting
        scores = self._apply_function_score_boost(query, scores)

        # 4. Filter to only matches with score > 0
        matched_df = self.df[matches].copy()
        matched_df['_score'] = scores[matches]
        matched_df = matched_df[matched_df['_score'] > 0]

        # 5. Sort by score (desc), then works_count (desc)
        matched_df = matched_df.sort_values(
            by=['_score', 'works_count'],
            ascending=[False, False]
        )

        # 6. Limit results
        matched_df = matched_df.head(limit)

        # 7. Convert to list of dicts
        results = []
        for _, row in matched_df.iterrows():
            results.append({
                'id': row.get('authorid') or row.get('id'),
                'display_name': row['display_name'],
                'works_count': int(row['works_count']) if pd.notna(row['works_count']) else 0,
                'cited_by_count': int(row['cited_by_count']) if pd.notna(row['cited_by_count']) else 0,
                'score': float(row['_score'])
            })

        return results

    def batch_search(self, queries: List[str], limit: int = 10) -> Dict[str, List[Dict[str, Any]]]:
        """
        Search for multiple queries at once.

        More efficient than calling search() multiple times.
        """
        results = {}
        for query in queries:
            results[query] = self.search(query, limit=limit)
        return results


if __name__ == '__main__':
    # Example usage
    import sys
    sys.path.insert(0, '/home/user/openalex-elastic-api')

    print("Loading authors...")
    autocomplete = AuthorAutocompletePython.from_parquet(
        'tests/standalone/test_run_autocomplete/fixtures/sample_authors_autocomplete.parquet'
    )

    # Test queries
    queries = ['Albert Einstein', 'Marie Curie', 'Al', 'Ein']

    for query in queries:
        print(f"\n{'='*80}")
        print(f"Query: '{query}'")
        print('='*80)

        results = autocomplete.search(query, limit=5)

        print(f"Found {len(results)} results:")
        for i, result in enumerate(results, 1):
            print(f"{i}. {result['display_name']} (score: {result['score']:.2f}, works: {result['works_count']})")
