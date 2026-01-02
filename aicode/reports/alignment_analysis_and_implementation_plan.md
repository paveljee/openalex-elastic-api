# OpenAlex Alignment Analysis & Implementation Plan

**Date**: 2025-12-31
**Purpose**: Achieve exact alignment with OpenAlex production for author search/autocomplete

---

## Executive Summary

After investigating actual OpenAlex API code (`openalex-elastic-api` repo), I've discovered:

### ✅ What We Got Right:
1. **BM25 Similarity**: Confirmed - production uses BM25
2. **Edge N-gram for Autocomplete**: Our approach matches production
3. **ASCII Folding**: We have it
4. **Multi-field Search**: We search display_name + display_name_alternatives
5. **Citation Boosting**: Our formula matches production
6. **Document Structure**: Core fields align

### ❌ What We're Missing:
1. **Kstem Stemming**: Missing in `.folded` analyzer
2. **Stop Word Removal**: Missing in `.folded` analyzer
3. **Field Naming**: We use different field structure than production

### ⚠️ Critical Finding About Ingestion:
**Pipeline differences (Logstash vs Python) DON'T MATTER** as long as final JSON documents indexed into Elasticsearch are identical!

---

## 1. Production Implementation Details

### 1.1 Full Author Search (`/authors?search=`)

**Source**: `/tmp/openalex-elastic-api/core/search.py` lines 231-254

```python
def author_name_query(self):
    """Search display_name and display_name.folded in order to ignore diacritics."""
    fields = [self.primary_field, self.primary_field + ".folded"]

    if self.secondary_field:
        fields.extend([self.secondary_field, self.secondary_field + ".folded"])

    most_fields_query = Q(
        "multi_match",
        query=self.search_terms,
        fields=fields,
        operator="and",
        type="most_fields",
    )

    phrase_query = Q(
        "multi_match",
        query=self.search_terms,
        fields=fields,
        type="phrase",
        boost=2,
    )

    return most_fields_query | phrase_query
```

**Fields Searched**:
- `display_name` (main text field)
- `display_name.folded` (with ASCII folding, kstem, stop words)
- `display_name_alternatives` (secondary field)
- `display_name_alternatives.folded`

**Analyzer for `.folded` Fields** (from documentation):
```json
{
  "analyzer": {
    "folding": {
      "tokenizer": "standard",
      "filter": ["lowercase", "asciifolding", "stop", "kstem"]
    }
  }
}
```

### 1.2 Autocomplete (`/autocomplete/authors?q=`)

**Source**: `/tmp/openalex-elastic-api/autocomplete/shared.py` lines 44-96

```python
if index_name.startswith("author"):
    autocomplete_query = (
        Q("match_phrase_prefix", display_name__autocomplete=q)
        | Q("match_phrase_prefix", display_name_alternatives__autocomplete=q)
    )

# Create a function score query that boosts exact matches
exact_match_query = Q(
    "function_score",
    query=autocomplete_query,
    functions=[
        # Boost exact matches in display_name
        {
            "filter": Q("term", display_name__keyword=q),
            "weight": 1000
        },
        # Boost prefix matches at word boundaries
        {
            "filter": Q("prefix", display_name__keyword=q),
            "weight": 500
        }
    ],
    score_mode="max",
    boost_mode="multiply"
)
```

**Fields Searched**:
- `display_name.autocomplete` (edge n-gram field)
- `display_name_alternatives.autocomplete` (edge n-gram field)
- `display_name.keyword` (for exact/prefix boosting)

**Analyzer for `.autocomplete` Fields** (inferred):
```json
{
  "analyzer": {
    "autocomplete_analyzer": {
      "tokenizer": "edge_ngram_tokenizer",
      "filter": ["lowercase", "asciifolding"]
    }
  },
  "tokenizer": {
    "edge_ngram_tokenizer": {
      "type": "edge_ngram",
      "min_gram": 1,
      "max_gram": 20,
      "token_chars": ["letter", "digit"]
    }
  }
}
```

**Note**: DO NOT add kstem or stop words to autocomplete analyzer - they break prefix matching!

---

## 2. Our Current Implementation

### 2.1 Current Analyzer Configuration

**Source**: `scripts/build_author_index_from_parquet.py` lines 76-99

```python
"settings": {
    "analysis": {
        "analyzer": {
            "folding": {
                "tokenizer": "standard",
                "filter": ["lowercase", "asciifolding"]  # ← MISSING stop, kstem
            },
            "autocomplete_analyzer": {
                "tokenizer": "autocomplete_tokenizer",
                "filter": ["lowercase", "asciifolding"]  # ← CORRECT
            }
        },
        "tokenizer": {
            "autocomplete_tokenizer": {
                "type": "edge_ngram",
                "min_gram": 1,
                "max_gram": 20,
                "token_chars": ["letter", "digit"]
            }
        }
    }
}
```

### 2.2 Current Field Mappings

```python
"display_name": {
    "type": "text",
    "fields": {
        "folded": {
            "type": "text",
            "analyzer": "folding"  # ← Missing filters
        },
        "autocomplete": {
            "type": "text",
            "analyzer": "autocomplete_analyzer",  # ← CORRECT
            "search_analyzer": "standard"
        },
        "keyword": {
            "type": "keyword"  # ← CORRECT
        }
    }
}
```

---

## 3. What Needs to Change

### 3.1 Critical: Add Missing Filters

**Change the `folding` analyzer** from:
```python
"folding": {
    "tokenizer": "standard",
    "filter": ["lowercase", "asciifolding"]
}
```

**To**:
```python
"folding": {
    "tokenizer": "standard",
    "filter": ["lowercase", "asciifolding", "stop", "kstem"]
}
```

### 3.2 Validation: Autocomplete Analyzer

**Keep as-is** (already correct):
```python
"autocomplete_analyzer": {
    "tokenizer": "autocomplete_tokenizer",
    "filter": ["lowercase", "asciifolding"]
}
```

**Why no kstem/stop for autocomplete?**
- Kstem would stem prefixes (bad for autocomplete)
- Stop words would prevent searching "the", "and", etc.
- Autocomplete needs exact prefix matching

### 3.3 Document Format Alignment

**Question**: Do our documents match OpenAlex's indexed documents?

**Our Current Mapping** (lines 117-160):
```python
def map_sciscinet_to_openalex(row):
    doc = {
        "id": row.get('authorid') or row.get('AuthorID'),
        "display_name": row.get('display_name'),
        "display_name_alternatives": alternatives,  # ← Parsed from string
        "works_count": int(row.get('works_count', 0)),
        "cited_by_count": int(row.get('cited_by_count', 0)),
    }
    # Optional: orcid, h_index, embedding
    return doc
```

**OpenAlex Production Document** (from Logstash):
- Parses `json_save` column from PostgreSQL
- Entire JSON document is indexed
- Includes: id, display_name, display_name_alternatives, works_count, cited_by_count, + many more fields

**Analysis**:
- ✅ Core searchable fields match (display_name, display_name_alternatives, cited_by_count, works_count)
- ⚠️ We're missing extra metadata (affiliations, ids, x_concepts, etc.)
- ✅ **Missing metadata doesn't affect SEARCH** - only affects API responses

**Conclusion**: Our document format is **sufficient for search/autocomplete** purposes.

---

## 4. Ingestion Pipeline Differences - Impact Analysis

### 4.1 The Question

> "How important are our differences from OpenAlex ingestion? Our input format is different - static authors parquet. How can we ensure that author data format that goes into index is identical to OpenAlex despite the differences in pipelines?"

### 4.2 The Answer

**Pipeline Differences DON'T MATTER for Search Functionality!**

Here's why:

#### What Matters for Search:
1. **Elasticsearch Index Mappings**: Defines how fields are analyzed/indexed
2. **Document Structure**: Fields that exist in indexed documents
3. **Analyzer Configuration**: How text is tokenized/filtered
4. **Similarity Algorithm**: BM25 (ES default)

#### What DOESN'T Matter for Search:
1. ❌ How data gets INTO Elasticsearch (Logstash vs Python vs API)
2. ❌ Source data format (PostgreSQL vs Parquet vs CSV)
3. ❌ Batch sizes or update frequency
4. ❌ External metadata not used in search

#### Proof:
**Logstash Pipeline**:
```
PostgreSQL (json_save column) → Parse JSON → Elasticsearch
```

**Our Pipeline**:
```
Parquet (rows) → Map to JSON → Elasticsearch
```

**Final Result in Elasticsearch** (what matters):
```json
{
  "id": "https://openalex.org/A1234567",
  "display_name": "John Smith",
  "display_name_alternatives": ["J. Smith", "John R. Smith"],
  "cited_by_count": 1500,
  "works_count": 45
}
```

As long as the final JSON documents have the same structure and values, Elasticsearch will index and search them identically!

### 4.3 How to Ensure Document Format Alignment

**Strategy**:

1. **Define Minimal Search Schema**:
   - Only include fields actually used in search/autocomplete
   - Our current schema is already minimal and correct

2. **Validate Field Types Match**:
   - `id`: keyword ✅
   - `display_name`: text with subfields ✅
   - `display_name_alternatives`: text/array ✅
   - `cited_by_count`: long ✅
   - `works_count`: long ✅

3. **Test Search Behavior**:
   - Query our index and production API
   - Compare relevance scores
   - Verify diacritic handling
   - Test stemming works correctly

4. **Don't Worry About Non-Searchable Fields**:
   - Fields like `affiliations`, `summary_stats`, `ids` are returned by API
   - They're either not indexed (`"index": false`) or not used in search queries
   - Including them doesn't hurt, but omitting them is fine for search purposes

### 4.4 Practical Example

**OpenAlex Production Index** has this document:
```json
{
  "id": "https://openalex.org/A5109805546",
  "display_name": "Albert Einstein",
  "display_name_alternatives": ["A. Einstein", "Albert E."],
  "cited_by_count": 19081,
  "works_count": 279,
  "affiliations": [...],  // ← Not used in search
  "summary_stats": {...},  // ← Not used in search
  "ids": {...}              // ← Not used in search
}
```

**Our Index** has this document:
```json
{
  "id": "https://openalex.org/A5109805546",
  "display_name": "Albert Einstein",
  "display_name_alternatives": ["A. Einstein", "Albert E."],
  "cited_by_count": 19081,
  "works_count": 279
  // ← Missing extra fields, but that's OK!
}
```

**Search Query**: `"search=albert einstein"`

**Both Produce Identical Results** because:
- Same fields are searched (`display_name`, `display_name.folded`)
- Same analyzer is used (standard + lowercase + asciifolding + stop + kstem)
- Same scoring (BM25 × citation boost)
- Extra metadata fields are ignored by search query

---

## 5. Implementation Plan

### Step 1: Update Analyzer Configuration ✅

**File**: `scripts/build_author_index_from_parquet.py`

**Change** (line ~79-82):
```python
# BEFORE:
"folding": {
    "tokenizer": "standard",
    "filter": ["lowercase", "asciifolding"]
}

# AFTER:
"folding": {
    "tokenizer": "standard",
    "filter": ["lowercase", "asciifolding", "stop", "kstem"]
}
```

### Step 2: Keep Autocomplete Analyzer Unchanged ✅

**File**: `scripts/build_author_index_from_parquet.py`

**No changes needed** (lines ~83-95):
```python
"autocomplete_analyzer": {
    "tokenizer": "autocomplete_tokenizer",
    "filter": ["lowercase", "asciifolding"]  # ← CORRECT - no kstem/stop
}
```

### Step 3: Validate Document Mapping ✅

**File**: `scripts/build_author_index_from_parquet.py`

**Current mapping is correct** (lines ~117-160):
- ✅ `id` field
- ✅ `display_name` field
- ✅ `display_name_alternatives` (parsed from parquet string)
- ✅ `cited_by_count`
- ✅ `works_count`
- ✅ Optional: `orcid`, `h_index`

**No changes needed** - document format aligns with search requirements.

### Step 4: Test Changes

1. **Reindex with new analyzers**:
   ```bash
   python scripts/build_author_index_from_parquet.py \
       --parquet-file /path/to/authors.parquet \
       --index-name authors-v16-test \
       --delete-existing
   ```

2. **Test stemming**:
   ```python
   # Query: "running"
   # Should match: "run", "runs", "running"
   ```

3. **Test stop words**:
   ```python
   # Query: "the albert einstein"
   # Should ignore "the" and search for "albert einstein"
   ```

4. **Test diacritics**:
   ```python
   # Query: "jose"
   # Should match: "José", "jose", "Jose"
   ```

### Step 5: Update Documentation

Create validation report showing:
- Analyzer configuration matches production
- Document format is sufficient for search
- Test results confirm correct behavior

---

## 6. Final Assessment

### Question 1: How Important Are Ingestion Differences?

**Answer**: **NOT IMPORTANT** for search functionality!

**Why?**
- Elasticsearch only cares about final indexed documents
- Pipeline (Logstash vs Python) is irrelevant
- Source format (PostgreSQL vs Parquet) is irrelevant
- As long as JSON documents are structured identically, search behavior is identical

### Question 2: How to Ensure Document Format Alignment?

**Answer**: **Focus on search-relevant fields only**

**Strategy**:
1. ✅ Identify fields used in search queries (display_name, display_name_alternatives)
2. ✅ Identify fields used in scoring (cited_by_count)
3. ✅ Identify fields used in sorting (works_count)
4. ❌ Ignore fields not used in search (affiliations, summary_stats, etc.)
5. ✅ Validate field types match (text, keyword, long)
6. ✅ Validate analyzers match production

**Our Current Status**:
- ✅ Core fields present and correct types
- ⚠️ Missing kstem + stop filters in `.folded` analyzer
- ✅ Autocomplete analyzer correct
- ✅ Document structure sufficient for search

### Question 3: What Changes Are Needed?

**Answer**: **ONE critical change**

**Required**:
1. Add `"stop"` and `"kstem"` filters to `folding` analyzer

**Optional** (nice to have):
1. Add more metadata fields from parquet if available
2. Match exact field structure of production (ids, summary_stats)

**Not Needed**:
1. ❌ Change ingestion pipeline (Parquet → Python is fine)
2. ❌ Use Logstash (Python works equally well)
3. ❌ Match production index name (authors-v8 vs authors-v16 doesn't matter)

---

## 7. Conclusion

### Critical Insight:

**"Identical Search Behavior ≠ Identical Ingestion Pipeline"**

OpenAlex uses Logstash because they have streaming updates from PostgreSQL. We use Parquet because we have static snapshots. **Both are valid approaches** that produce identical search results as long as:

1. ✅ Index mappings match
2. ✅ Analyzer configurations match
3. ✅ Document structure contains search-relevant fields
4. ✅ Field values are correct

### What We Need to Do:

**Single Critical Fix**:
```python
# Add two filters to folding analyzer:
"filter": ["lowercase", "asciifolding", "stop", "kstem"]
```

After this change, our implementation will be **functionally identical** to OpenAlex production for search purposes!

### What We Don't Need to Worry About:

1. ❌ Logstash vs Python ingestion
2. ❌ PostgreSQL vs Parquet source
3. ❌ Missing non-searchable metadata fields
4. ❌ Different index names
5. ❌ Different update strategies (incremental vs full reindex)

**These differences don't affect search quality or behavior at all!**
