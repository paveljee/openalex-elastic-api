# Standalone Author Matching Tests

## Purpose

These tests validate the **EXTRACTED** author matching logic against the **ORIGINAL** implementation.

**NO fuzzy matching. NO approximations. Either EQUAL or FAIL.**

## Test Types

### 1. Exact Equality Tests (No Elasticsearch Required)

Tests that prove query structures are mathematically identical.

```bash
cd tests/standalone
python -m pytest test_exact_equality.py -v
```

### 2. Real Ranking Comparison Tests (Requires Elasticsearch)

Tests that compare actual ranking results against OpenAlex API using real data.

```bash
# Setup Elasticsearch (one-time setup)
./setup_elasticsearch.sh

# Populate with test data
python populate_es.py

# Run ranking comparison tests
python -m pytest test_real_ranking_comparison.py -v
```

### 3. Statistical Validation with Real API Responses (Requires Elasticsearch)

Validates against your saved production OpenAlex API responses.

**Prerequisites:**
1. Elasticsearch running (use `./setup_elasticsearch.sh`)
2. Authors indexed from SciSciNet v2:
   ```bash
   python scripts/build_author_index_from_parquet.py /path/to/sciscinet/authors_details.parquet
   ```
3. Your saved API response JSON files in a directory

**Running the validation:**
```bash
# Put your API response files (unix timestamp filenames) in data/api_responses/
mkdir -p data/api_responses
# Copy your 30+ JSON files there

# Run statistical validation
python tests/standalone/test_statistical_validation.py --responses-dir=data/api_responses
```

**What you get:**
- Temporal consistency check (for duplicate queries across time)
- Empty query consistency (API empty → local also empty?)
- Comprehensive ranking metrics:
  - Exact match rate (% of identical rankings)
  - Kendall's Tau (rank correlation: -1 to 1)
  - Top-10 overlap (% of shared top-10 results)
  - NDCG@10 (ranking quality metric)
- Statistical analysis with confidence intervals
- Results saved to `tests/standalone/statistical_validation_results.json`

**Expected format** for API response files:
```json
{
  "Albert Einstein": [
    {"id": "A123", "display_name": "Albert Einstein", ...},
    ...
  ],
  "Marie Curie": [...],
  ...
}
```

### 4. End-to-End Reproducible Test (Fully Self-Contained)

**Purpose:** Validates the complete workflow from scratch using sample data. Proves the system works without manual intervention.

**Location:** `tests/standalone/test_run/test_end_to_end_validation.py`

**What it does:**
```bash
pytest tests/standalone/test_run/test_end_to_end_validation.py -v -s
```

This test is **fully self-contained** and executes the complete workflow:

1. **Detects if Elasticsearch is running**
   - If not running: Automatically calls `./setup_elasticsearch.sh`
   - If running: Skips setup and continues
   - Creates authors-v16 index with proper mappings

2. **Indexes sample authors from parquet**
   - Uses `scripts/build_author_index_from_parquet.py --parquet-file`
   - Indexes 8 real OpenAlex authors from `fixtures/sample_authors_details.parquet`
   - Real data fetched from OpenAlex API (2024-12-24)

3. **Runs statistical validation**
   - Imports and executes `test_statistical_validation.py` (same code you'll use!)
   - Uses sample fixtures from `test_run/fixtures/1640000000.json`
   - 4 queries: Albert Einstein, Marie Curie, Richard Feynman, empty query

4. **Generates comprehensive reports**
   - `test_run/reports/end_to_end_validation_report.json`
   - `tests/standalone/statistical_validation_results.json`

**Expected Results (with sample data):**
```
Total queries tested:    4
Valid comparisons:       3

Exact match rate:        0.00%  (expected - corpus timing differences)
Kendall's Tau:           1.0000 (perfect rank correlation!)
Top-10 overlap:          47.78% (partial overlap)
NDCG@10:                 0.5533

Empty Query Consistency:
  Both empty:            1 ✓ (perfect)

Temporal Consistency:
  Duplicate queries:     4
  Perfectly consistent:  4 ✓
```

**What this proves:**
✅ Setup scripts work from scratch
✅ Parquet indexing works correctly
✅ Statistical validation code runs successfully
✅ All components integrate properly
✅ Zero manual setup required

**What this does NOT prove:**
❌ Your full SciSciNet dataset will index successfully (only tested with 8 authors)
❌ Your specific 30+ API fixtures will work (uses sample fixtures)
❌ Performance with large datasets (millions of authors)
❌ Edge cases in your specific data

**Recommendation:** After the e2e test passes, validate with YOUR data:
1. Index your full `authors_details.parquet` (may take time with 100M+ authors)
2. Put your 30+ fixtures in `data/api_responses/`
3. Run: `python tests/standalone/test_statistical_validation.py --responses-dir=data/api_responses`

**Critical Assessment:**

The e2e test uses **sample data** to prove the workflow works, but your production data may have:
- Different schema edge cases
- Queries for authors not in your dataset
- Performance issues at scale
- Unexpected JSON formats

**Trust level:** The e2e test validates that all scripts integrate correctly and the validation logic works. However, the metrics you get with YOUR data will likely differ significantly from the sample results. The test proves the *system works*, not that *your specific results will be good*.

## Expected Output

```
============================= test session starts ==============================
platform linux -- Python 3.11.14, pytest-9.0.2, pluggy-1.6.0 -- /usr/local/bin/python
collecting ... collected 8 items

test_exact_equality.py::TestExactEquality::test_name_query_structure_exact_match PASSED [ 12%]
test_exact_equality.py::TestExactEquality::test_citation_boost_sqrt_exact_match PASSED [ 25%]
test_exact_equality.py::TestExactEquality::test_citation_boost_log_exact_match PASSED [ 37%]
test_exact_equality.py::TestExactEquality::test_complete_query_exact_match PASSED [ 50%]
test_exact_equality.py::TestExactEquality::test_diacritic_query_exact_match PASSED [ 62%]
test_exact_equality.py::TestExactEquality::test_special_chars_query_exact_match PASSED [ 75%]
test_exact_equality.py::TestExactEquality::test_batch_queries_all_exact_match PASSED [ 87%]
test_exact_equality.py::TestExactEquality::test_without_citation_boost_exact_match PASSED [100%]

============================== 8 passed in 0.56s
```

## What These Tests Prove

### Test Coverage

1. **test_name_query_structure_exact_match** - Name matching query structure
2. **test_citation_boost_sqrt_exact_match** - Square root citation boosting
3. **test_citation_boost_log_exact_match** - Natural log citation boosting
4. **test_complete_query_exact_match** - Full query integration
5. **test_diacritic_query_exact_match** - Diacritic handling (José García)
6. **test_special_chars_query_exact_match** - Special characters (O'Brien)
7. **test_batch_queries_all_exact_match** - Multiple queries batch validation
8. **test_without_citation_boost_exact_match** - Queries without boost

### Assertion Style

```python
# WHAT WE DO (CORRECT):
assert original.to_dict() == extracted.to_dict()

# WHAT WE DON'T DO (WRONG):
assert overlap_percentage >= 60%  # This is bullshit
```

### Mathematical Proof

```
Original Query Dict == Extracted Query Dict  (VERIFIED ✅)
         ↓
SAME Elasticsearch query
         ↓
SAME scores for each document
         ↓
SAME ranking order
```

## Test Independence

These tests:
- ✅ Run standalone without full Flask app
- ✅ Don't require Elasticsearch connection
- ✅ Don't depend on conftest.py
- ✅ Only need: elasticsearch-dsl package

## Requirements

```bash
pip install elasticsearch-dsl==8.9.0
```

## Proof of Exact Equality

Every test asserts that:
- The ORIGINAL query structure (from `core/search.py`)
- The EXTRACTED query structure (from `core/author_matching.py`)

Are **MATHEMATICALLY IDENTICAL**.

If they weren't, the tests would **FAIL**.

They **PASS** because the code is **IDENTICAL**.

## Available Scripts

### `setup_elasticsearch.sh`
Automated setup script that:
- Downloads Elasticsearch 8.9.0
- Configures single-node cluster
- Creates `authors-v16` index with proper mappings
- Handles root user setup (creates elasticsearch user)

### `populate_es.py`
Populates Elasticsearch with real author data from OpenAlex API:
- Fetches 192 diverse authors (Einstein, Curie, common names, etc.)
- Creates realistic test dataset
- Required for running ranking comparison tests

### `test_exact_equality.py`
8 tests proving query structure equality (no ES required)

### `test_real_ranking_comparison.py`
Real-world ranking validation against OpenAlex API (requires ES)

### `test_statistical_validation.py`
Statistical validation against saved production OpenAlex API responses:
- Validates with YOUR real API artifacts (30+ queries)
- Tests empty query consistency
- Computes Kendall's Tau, NDCG, exact match rate, top-k overlap
- Adjusted thresholds for same-source corpus (SciSciNet v2 from OpenAlex)

### `test_run/test_end_to_end_validation.py`
Fully self-contained end-to-end test:
- Automatically sets up Elasticsearch from scratch
- Indexes 8 real OpenAlex authors from sample parquet
- Runs statistical validation with sample fixtures
- Proves complete workflow works without manual intervention
- **NOTE:** Uses sample data (8 authors, 4 queries) - your production data may behave differently
- Run with: `pytest tests/standalone/test_run/test_end_to_end_validation.py -v -s`

## Quick Start

```bash
cd tests/standalone

# One-time setup
./setup_elasticsearch.sh
python populate_es.py

# Run all tests
python -m pytest -v

# Stop Elasticsearch when done
kill $(cat elasticsearch.pid)
```
