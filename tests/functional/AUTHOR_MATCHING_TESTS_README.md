# Author Matching Validation Tests

## Overview

This directory contains comprehensive validation tests for the extracted author display_name matching and ranking logic. The tests ensure that the extracted logic in `core/author_matching.py` produces correct and consistent results.

## Test Files

### 1. `test_author_matching_validation.py`

**Full Integration Tests** - Compares extracted logic against real OpenAlex API

This test suite makes real HTTP requests to the OpenAlex API (`https://api.openalex.org`) and compares the ranking/ordering with our extracted matching logic running against local Elasticsearch.

**Test Coverage:**

#### Common English Names
- `test_common_name_john_smith` - Very common name
- `test_famous_scientist_einstein` - Well-known scientist
- `test_author_marie_curie` - Historical figure

#### Names with Diacritics
- `test_diacritic_german_umlaut` - German umlaut (Müller)
- `test_diacritic_ascii_folding_muller` - Folding test (Muller → Müller)
- `test_diacritic_spanish_accent` - Spanish accents (José García)
- `test_diacritic_without_accent` - ASCII folding (Jose Garcia → José García)
- `test_diacritic_french_accents` - French accents (François Lévy)

#### Asian Names
- `test_chinese_name_pinyin` - Chinese Pinyin (Wei Wang)
- `test_japanese_name` - Japanese name (Takeshi Yamamoto)
- `test_korean_name` - Korean name (Kim Seung)

#### Arabic Names
- `test_arabic_name_transliterated` - Transliterated Arabic (Mohamed Ahmed)

#### Edge Cases
- `test_single_name` - Single word name (Einstein)
- `test_three_part_name` - Hyphenated name (Jean-Luc Picard)
- `test_name_with_apostrophe` - Apostrophe (O'Brien)
- `test_very_common_surname_only` - Common surname only (Smith)
- `test_initials_with_periods` - Initials (J. K. Rowling)
- `test_name_with_suffix` - Name suffix (Martin Luther King Jr)

#### Ranking Validation
- `test_highly_cited_author_ranks_first` - Citation-based ranking
- `test_exact_match_vs_partial_match` - Phrase boost validation

#### Special Characters
- `test_non_latin_characters_arabic` - Arabic script (محمد)
- `test_non_latin_characters_chinese` - Chinese characters (王伟)
- `test_empty_string_search` - Empty query handling
- `test_very_long_name` - Unusually long names

#### Multilingual
- `test_mixed_latin_cyrillic` - Cyrillic transliteration (Vladimir Putin)
- `test_nordic_characters` - Nordic characters (Søren Kierkegaard)
- `test_turkish_characters` - Turkish characters (Erdoğan)

**Requirements:**
- Elasticsearch running locally
- OpenAlex API access (internet connection)
- Flask app with test client

**Usage:**
```bash
pytest tests/functional/test_author_matching_validation.py -v
```

**Rate Limiting:**
Tests include 100ms delays between API requests to respect OpenAlex rate limits.

### 2. `test_author_matching_validation_simple.py`

**Unit Tests** - Tests extracted logic components without external dependencies

These tests validate the query structure and logic without requiring Elasticsearch or the OpenAlex API. They can run standalone with only `elasticsearch-dsl` installed.

**Test Coverage:**

#### Query Structure Tests
- `test_author_name_matcher_query_structure` - Verifies correct multi_match query with 4 fields
- `test_author_name_matcher_without_secondary_field` - Tests with only primary field
- `test_author_ranker_sqrt_scaling` - Validates square root citation scaling
- `test_author_ranker_log_scaling` - Validates logarithmic citation scaling
- `test_author_ranker_invalid_scaling_type` - Error handling for invalid scaling

#### Integration Tests
- `test_build_author_search_query_with_boost` - Complete query with citation boost
- `test_build_author_search_query_without_boost` - Query without citation boost
- `test_build_author_search_query_log_scaling` - Complete query with log scaling

#### Edge Case Tests
- `test_query_with_diacritics` - Diacritic preservation in queries
- `test_query_with_special_characters` - Apostrophes and special chars
- `test_empty_search_terms` - Empty string handling
- `test_very_long_search_terms` - Long name handling
- `test_query_serialization` - JSON serialization of queries

#### Configuration Tests
- `test_default_sort_order` - Validates default sort configuration

**Requirements:**
- `elasticsearch-dsl==8.9.0` (only)

**Usage:**
```bash
# As pytest tests
pytest tests/functional/test_author_matching_validation_simple.py -v

# Or standalone
PYTHONPATH=/home/user/openalex-elastic-api python tests/functional/test_author_matching_validation_simple.py
```

**Output:**
```
================================================================================
Running 14 author matching validation tests
================================================================================
✓ test_author_name_matcher_query_structure
✓ test_author_name_matcher_without_secondary_field
✓ test_author_ranker_invalid_scaling_type
✓ test_author_ranker_log_scaling
✓ test_author_ranker_sqrt_scaling
...
================================================================================
Results: 14 passed, 0 failed
================================================================================
```

## Running the Tests

### Quick Validation (Simple Tests)

Test the extracted logic without external dependencies:

```bash
# Install minimal dependency
pip install elasticsearch-dsl==8.9.0

# Run standalone
PYTHONPATH=/home/user/openalex-elastic-api python \
  tests/functional/test_author_matching_validation_simple.py
```

### Full Validation (Integration Tests)

Compare against real OpenAlex API:

```bash
# Install dev dependencies
pip install -r requirements/dev.txt

# Run with pytest
pytest tests/functional/test_author_matching_validation.py -v

# Run specific test
pytest tests/functional/test_author_matching_validation.py::TestAuthorMatchingValidation::test_famous_scientist_einstein -v
```

### Run All Tests

```bash
pytest tests/functional/test_author_matching_validation*.py -v
```

## Test Assertions

### Integration Tests (test_author_matching_validation.py)

For each test case comparing against the OpenAlex API:

1. **Results Existence**: Both API and local search return results
2. **Overlap Percentage**: Top N results have significant overlap (typically 40-80%)
3. **Name Matching**: Top results contain expected name components
4. **Ranking Quality**: Citation-based ranking is applied correctly

**Example Assertion:**
```python
comparison = self.compare_rankings(api_results, local_results, top_n=5)

# At least 80% of top 5 results should match for famous authors
assert comparison["overlap_percentage"] >= 80, \
    f"Famous scientist should have high overlap. Got {comparison['overlap_percentage']}%"
```

### Unit Tests (test_author_matching_validation_simple.py)

For each component test:

1. **Query Structure**: Correct Elasticsearch DSL structure
2. **Field Coverage**: All expected fields (primary, primary.folded, secondary, secondary.folded)
3. **Boost Values**: Phrase query has 2x boost
4. **Operators**: AND operator for multi_match
5. **Scaling Functions**: Correct sqrt or log10 in citation boost script

**Example Assertion:**
```python
assert len(most_fields_query["fields"]) == 4, \
    "Should search 4 fields: primary, primary.folded, secondary, secondary.folded"

assert phrase_query["boost"] == 2, \
    "Phrase query should have 2x boost"
```

## Comparison Metrics

The `compare_rankings()` method in integration tests returns:

```python
{
    "api_ids": [...],           # Ordered list of IDs from API
    "local_ids": [...],         # Ordered list of IDs from local search
    "overlap": 4,               # Number of matching IDs in top N
    "overlap_percentage": 80.0, # Percentage of top N that match
    "top_3_exact_match": True,  # Whether top 3 are in exact same order
    "api_top_name": "...",      # Display name of API's top result
    "local_top_name": "...",    # Display name of local top result
}
```

## Expected Test Results

### Unit Tests
- **All 14 tests should pass**
- No external dependencies required
- Runs in < 1 second

### Integration Tests
- **High overlap for famous/unique names**: 80%+ (Einstein, Marie Curie)
- **Moderate overlap for common names**: 40-60% (John Smith, Wei Wang)
- **Lower overlap for very common surnames**: 20%+ (Smith)

Variations are expected due to:
- Tie-breaking differences
- Timing of data updates between API and local
- Elasticsearch scoring variations

## Test Maintenance

### When to Update Tests

1. **After modifying `core/author_matching.py`**: Run all tests to ensure no regression
2. **When OpenAlex API changes**: Update integration tests if API behavior changes
3. **When Elasticsearch version updates**: Validate query DSL compatibility

### Adding New Tests

To add a new validation test case:

```python
def test_new_edge_case(self):
    """Test description"""
    search_query = "Your Test Name"

    api_results = self.fetch_openalex_api_results(search_query, per_page=10)
    local_results = self.fetch_local_results(search_query, per_page=10)

    assert len(local_results) > 0, "Should return results"

    comparison = self.compare_rankings(api_results, local_results, top_n=5)
    assert comparison["overlap_percentage"] >= 40, "Should have reasonable overlap"
```

## Troubleshooting

### Integration Tests Fail with Network Errors

- Check internet connection
- Verify OpenAlex API is accessible: `curl https://api.openalex.org/authors?search=test`
- Check for rate limiting (tests include delays)

### Integration Tests Show Low Overlap

- Expected for very common names (< 40% overlap is acceptable)
- Data may differ between API and local Elasticsearch
- Check that local Elasticsearch has recent data

### Unit Tests Fail

- Verify `elasticsearch-dsl==8.9.0` is installed
- Check that `core/author_matching.py` hasn't been modified
- Run with `PYTHONPATH` set correctly

### Import Errors

```bash
# Ensure proper Python path
export PYTHONPATH=/home/user/openalex-elastic-api:$PYTHONPATH

# Or run from project root
cd /home/user/openalex-elastic-api
python tests/functional/test_author_matching_validation_simple.py
```

## Performance

### Unit Tests
- **Runtime**: < 1 second
- **No network I/O**
- **No Elasticsearch required**

### Integration Tests
- **Runtime**: ~30-60 seconds (depends on test count)
- **Network I/O**: ~40 API requests with 100ms delays
- **Elasticsearch required**: Yes

## Continuous Integration

To add these tests to CI:

```yaml
# .github/workflows/test.yml
- name: Run Author Matching Unit Tests
  run: |
    pip install elasticsearch-dsl==8.9.0
    PYTHONPATH=. python tests/functional/test_author_matching_validation_simple.py

- name: Run Author Matching Integration Tests
  run: |
    pytest tests/functional/test_author_matching_validation.py -v
  # Only if Elasticsearch is available in CI
```

## References

- **Extracted Module**: `core/author_matching.py`
- **Documentation**: `core/AUTHOR_MATCHING_README.md`
- **Examples**: `core/author_matching_examples.py`
- **OpenAlex API**: https://api.openalex.org
- **OpenAlex Docs**: https://docs.openalex.org
