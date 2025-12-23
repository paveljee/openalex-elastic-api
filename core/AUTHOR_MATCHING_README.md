# Author Display Name Matching & Ranking Module

## Overview

The `author_matching.py` module provides reusable, isolated logic for matching and ranking authors based on their display names and citation metrics. This module extracts and consolidates the author matching logic from across the codebase for easy reuse.

## Features

### 1. **Multi-Field Name Matching**
- Searches across `display_name` and `display_name_alternatives`
- Handles diacritics using `.folded` field variants
- Uses Elasticsearch `multi_match` with `most_fields` type
- Phrase query boosting (2x) for exact matches

### 2. **Citation-Based Ranking**
- Boosts authors with higher citation counts
- Two scaling options: square root (default) or logarithmic
- Scoring formula:
  - No citations: score × 0.5
  - With citations: score × (1 + √cited_by_count)

### 3. **Autocomplete Support**
- Phrase prefix matching on autocomplete fields
- Exact match boosting (1000x weight)
- Prefix match boosting (500x weight)

## Usage Examples

### Basic Author Name Search

```python
from core.author_matching import build_author_search_query
from elasticsearch_dsl import Search

# Build a complete author search query
query = build_author_search_query("Albert Einstein")

# Use with elasticsearch-dsl
s = Search(index="authors")
s = s.query(query)
results = s.execute()
```

### Advanced: Custom Matching with Classes

```python
from core.author_matching import AuthorNameMatcher, AuthorRanker

# Create a matcher
matcher = AuthorNameMatcher(
    search_terms="Marie Curie",
    primary_field="display_name",
    secondary_field="display_name_alternatives"
)

# Build the matching query
matching_query = matcher.build_query()

# Apply citation boosting
ranker = AuthorRanker()
boosted_query = ranker.apply_citation_boost(matching_query, scaling_type="sqrt")

# Use in search
s = Search(index="authors").query(boosted_query)
```

### Autocomplete Queries

```python
from core.author_matching import build_author_autocomplete_query

# Build autocomplete query with boosting
query = build_author_autocomplete_query("Einst")

s = Search(index="authors").query(query)
results = s.execute()
```

### Without Citation Boost

```python
from core.author_matching import build_author_search_query

# Search without citation-based ranking
query = build_author_search_query(
    "Richard Feynman",
    apply_citation_boost=False
)
```

### Logarithmic Citation Scaling

```python
from core.author_matching import build_author_search_query

# Use logarithmic scaling instead of square root
query = build_author_search_query(
    "Isaac Newton",
    citation_scaling="log"
)
```

## API Reference

### Classes

#### `AuthorNameMatcher`

Handles multi-field author name matching.

**Constructor:**
```python
AuthorNameMatcher(
    search_terms: str,
    primary_field: str = "display_name",
    secondary_field: str = "display_name_alternatives"
)
```

**Methods:**
- `build_query()` → `elasticsearch_dsl.Q`: Build the matching query

#### `AuthorRanker`

Handles citation-based ranking.

**Static Methods:**
- `apply_citation_boost(query, scaling_type="sqrt")` → `elasticsearch_dsl.Q`: Apply citation boosting

#### `AuthorAutocompleteMatcher`

Handles autocomplete matching with boosting.

**Static Methods:**
- `build_autocomplete_query(query_string, primary_field="display_name", secondary_field="display_name_alternatives")` → `elasticsearch_dsl.Q`
- `apply_exact_prefix_boost(autocomplete_query, query_string, primary_field="display_name", exact_match_weight=1000, prefix_match_weight=500)` → `elasticsearch_dsl.Q`

### Convenience Functions

#### `build_author_search_query()`

Build a complete author search query with matching and optional ranking.

```python
build_author_search_query(
    search_terms: str,
    apply_citation_boost: bool = True,
    citation_scaling: str = "sqrt"
) → elasticsearch_dsl.Q
```

**Parameters:**
- `search_terms`: The search query terms
- `apply_citation_boost`: Whether to apply citation-based ranking (default: True)
- `citation_scaling`: Scaling type - "sqrt" or "log" (default: "sqrt")

#### `build_author_autocomplete_query()`

Build a complete autocomplete query with optional exact/prefix boosting.

```python
build_author_autocomplete_query(
    query_string: str,
    apply_exact_prefix_boost: bool = True
) → elasticsearch_dsl.Q
```

## Constants

### `DEFAULT_AUTHOR_SORT_ORDER`

Default sorting order for author search results:
```python
["_score", "-works_count", "id"]
```

### `AUTHOR_NAME_FIELDS`

Field configuration dictionary:
```python
{
    "primary": "display_name",
    "secondary": "display_name_alternatives",
    "primary_folded": "display_name.folded",
    "secondary_folded": "display_name_alternatives.folded",
}
```

## Integration with Existing Code

This module is designed to be a drop-in replacement for the author matching logic scattered across:
- `core/search.py` - `author_name_query()` and `citation_boost_query()` methods
- `autocomplete/shared.py` - Author autocomplete logic

### Migrating Existing Code

**Before (in core/search.py):**
```python
class SearchOpenAlex:
    def author_name_query(self):
        fields = [self.primary_field, self.primary_field + ".folded"]
        # ... complex logic
```

**After (using new module):**
```python
from core.author_matching import AuthorNameMatcher

matcher = AuthorNameMatcher(search_terms, primary_field, secondary_field)
query = matcher.build_query()
```

## Field Mapping

The module expects the following Elasticsearch field structure:

```
display_name (text)
  ├── display_name.folded (text with ASCII folding)
  └── display_name__autocomplete (text with edge_ngram)
  └── display_name__keyword (keyword for exact matching)

display_name_alternatives (array of text)
  ├── display_name_alternatives.folded
  └── display_name_alternatives__autocomplete
```

## Ranking Formula Details

### Square Root Scaling (Default)
```
if cited_by_count == 0:
    score_multiplier = 0.5
else:
    score_multiplier = 1 + sqrt(cited_by_count)
```

**Examples:**
- 0 citations → 0.5x multiplier
- 100 citations → 11x multiplier (1 + √100)
- 10,000 citations → 101x multiplier (1 + √10000)

### Logarithmic Scaling
```
if cited_by_count == 0:
    score_multiplier = 0.5
else:
    score_multiplier = 1 + log10(cited_by_count + 1)
```

**Examples:**
- 0 citations → 0.5x multiplier
- 100 citations → 3.0x multiplier (1 + log10(101))
- 10,000 citations → 5.0x multiplier (1 + log10(10001))

## Testing

See `tests/functional/test_authors.py` for examples of how author searches are tested:

```python
def test_authors_search(client):
    res = client.get("/authors?search=jones")
    # Verify "jones" appears in results

def test_authors_search_display_name(client):
    res = client.get("/authors?filter=display_name.search:jones")
    # Verify filtered results
```

## Performance Considerations

1. **Field Count**: Searching 4 fields (display_name, display_name.folded, display_name_alternatives, display_name_alternatives.folded) increases query complexity
2. **Citation Boost**: The `function_score` query with script adds computational overhead
3. **Phrase Queries**: Phrase matching is more expensive than term matching

## Future Enhancements

Potential improvements:
- Fuzzy matching support for typos
- Configurable boost values
- Support for additional ranking signals (h-index, works_count)
- Name disambiguation logic integration
- Configurable field weights
