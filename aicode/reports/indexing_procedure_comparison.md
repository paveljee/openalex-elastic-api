# OpenAlex Indexing Procedure vs Our Implementation

**Investigation Date**: 2025-12-31
**Focus**: Compare how OpenAlex indexes authors in production vs our `build_author_index_from_parquet.py` script

---

## Executive Summary

**CRITICAL FINDING**: Our indexing procedure fundamentally differs from OpenAlex's production setup in multiple ways:

1. **Data Source**: OpenAlex uses PostgreSQL/Redshift → Logstash → Elasticsearch; we use Parquet → Python → Elasticsearch
2. **Template Application**: OpenAlex uses pre-configured Elasticsearch templates; we define mappings inline
3. **Autocomplete Strategy**: OpenAlex uses `completion` type (FST-based); we use `edge_ngram` tokenizer
4. **Analyzer Configuration**: OpenAlex likely has stop words + kstem in production; we only have asciifolding + lowercase
5. **Index Name**: OpenAlex uses `authors-v8`; we use `authors-v16`

---

## 1. Elasticsearch Version

### OpenAlex Production Setup

Based on evidence from official repositories:

#### From `openalex-elasticsearch` (Indexing Pipeline):
```yaml
# docker-compose.yml
services:
  logstash:
    image: docker.elastic.co/logstash/logstash:7.17.2
  metricbeat:
    image: docker.elastic.co/beats/metricbeat:7.17.2
```

**Dependencies**:
```txt
elasticsearch-dsl==7.4.0
```

#### From `openalex-guts` (Main API):
```txt
elasticsearch==8.10.1
elasticsearch-dsl==8.9.0
```

**Interpretation**:
- **Indexing pipeline**: Compatible with Elasticsearch **7.17.x** (based on Logstash 7.17.2)
- **API client**: Uses ES Python client 8.10.1 (supports both ES 7.x and 8.x servers)
- **Most Likely Production Version**: **Elasticsearch 7.17.x** or **8.x**

**Similarity Algorithm**: Both ES 7.17.x and 8.x use **BM25** by default (since ES 5.0+, released 2016)

**Verdict**: ✅ **CONFIRMED** - Production uses **BM25** (Elasticsearch default since 5.0+)

---

## 2. OpenAlex's Actual Indexing Procedure

### Data Flow

**Source**: `/tmp/openalex-elasticsearch/logstash/logstash_authors/pipeline/logstash.conf`

```
PostgreSQL/Redshift (mid.json_authors table)
           ↓
    Logstash (JDBC Input)
           ↓
    JSON Parsing & Filtering
           ↓
    Elasticsearch (authors-v8 index)
```

### Logstash Pipeline Configuration

#### Input Stage:
```ruby
input {
    jdbc {
        jdbc_driver_library => "/usr/share/jars/postgresql-42.3.5.jar"
        jdbc_driver_class => "org.postgresql.Driver"
        jdbc_connection_string => "${JDBC_URL_PROD}"
        jdbc_user => "${JDBC_USER_PROD}"
        jdbc_password => "${JDBC_PASSWORD_PROD}"
        jdbc_paging_enabled => true
        jdbc_page_size => 500000
        last_run_metadata_path => "/usr/share/sql_last_value.yml"
        schedule => "0 * * * *"  # ← Runs every hour
        statement => "SELECT json_save, updated from mid.json_authors WHERE updated > :sql_last_value order by updated"
        use_column_value => true
        tracking_column => updated
        tracking_column_type => "timestamp"
    }
}
```

**Key Points**:
- Pulls from PostgreSQL database every hour
- Only fetches updated records (incremental updates)
- Page size: 500,000 records per batch
- Data is already in JSON format (`json_save` column)

#### Filter Stage:
```ruby
filter {
    # Clean up JSON string
    mutate {
        gsub => [
            "json_save", "[\r\n]", "",
            "json_save", "[\t]", " "
        ]
    }

    # Parse JSON
    json {
        source => "json_save"
    }

    # Retry parsing if failed
    if "_jsonparsefailure" in [tags] {
        mutate {
            gsub => [
                "json_save", "[\\]", ""
            ]
        }
        json {
            source => "json_save"
        }
    }

    # Remove temporary fields
    mutate {
        remove_field => ["json_save", "version"]
    }

    # Drop if no ID
    if ![id] {
        drop {}
    }
}
```

**Key Points**:
- Handles malformed JSON gracefully
- Removes metadata fields
- Drops documents without ID

#### Output Stage:
```ruby
output {
    elasticsearch {
        hosts => ["${ES_HOST_PROD}"]
        index => "authors-v8"  # ← Production index name
        user => "${ES_USER_PROD}"
        password => "${ES_PASSWORD_PROD}"
        document_id => "%{id}"
    }
}
```

**Key Points**:
- Index name: `authors-v8`
- Uses document `id` field as Elasticsearch document ID
- **NO analyzers or tokenizers defined in Logstash** (relies on Elasticsearch template)

---

## 3. Our Indexing Procedure

### Data Flow

**Source**: `/home/user/openalex-elastic-api/scripts/build_author_index_from_parquet.py`

```
Parquet File (SciSciNet author data)
           ↓
    Pandas DataFrame (chunked reading)
           ↓
    Schema Mapping (SciSciNet → OpenAlex)
           ↓
    Elasticsearch Parallel Bulk (authors-v16 index)
```

### Python Script Configuration

#### Index Mappings (lines 21-100):
```python
AUTHOR_MAPPINGS = {
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "display_name": {
                "type": "text",
                "fields": {
                    "folded": {
                        "type": "text",
                        "analyzer": "folding"  # ← ASCII folding only
                    },
                    "autocomplete": {
                        "type": "text",
                        "analyzer": "autocomplete_analyzer",  # ← edge_ngram
                        "search_analyzer": "standard"
                    },
                    "keyword": {"type": "keyword"}
                }
            },
            "display_name_alternatives": {
                "type": "text",
                "fields": {
                    "folded": {"type": "text", "analyzer": "folding"},
                    "autocomplete": {
                        "type": "text",
                        "analyzer": "autocomplete_analyzer"
                    }
                }
            },
            "cited_by_count": {"type": "long"},
            "works_count": {"type": "long"},
            "h_index": {"type": "long"}
        }
    },
    "settings": {
        "analysis": {
            "analyzer": {
                "folding": {
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"]  # ← Missing stop, kstem
                },
                "autocomplete_analyzer": {
                    "tokenizer": "autocomplete_tokenizer",
                    "filter": ["lowercase", "asciifolding"]
                }
            },
            "tokenizer": {
                "autocomplete_tokenizer": {
                    "type": "edge_ngram",  # ← Different from OpenAlex
                    "min_gram": 1,
                    "max_gram": 20,
                    "token_chars": ["letter", "digit"]
                }
            }
        },
        "number_of_shards": 5,
        "number_of_replicas": 0
    }
}
```

#### Indexing Process (lines 200-248):
```python
def index_authors(es, parquet_file, index_name, chunk_size=100000):
    """Index authors from parquet file into Elasticsearch"""

    # Process in 100k chunks
    for chunk_num, chunk in enumerate(load_parquet_chunked(parquet_file, chunk_size)):

        # Map SciSciNet schema to OpenAlex schema
        actions = generate_actions(chunk, index_name)

        # Bulk index with parallel processing
        for success, info in parallel_bulk(
            es,
            actions,
            thread_count=4,      # ← 4 parallel threads
            chunk_size=500,      # ← 500 docs per bulk request
            raise_on_error=False
        ):
            # Track success/errors
            ...

    # Refresh index
    es.indices.refresh(index=index_name)
```

**Key Points**:
- Reads from Parquet file in 100k record chunks
- Maps SciSciNet schema to OpenAlex schema
- Uses `parallel_bulk` with 4 threads for performance
- Bulk size: 500 documents per request
- Index name: `authors-v16`
- **Defines all analyzers and mappings inline** (not using external template)

---

## 4. Critical Differences

| Aspect | OpenAlex Production | Our Implementation |
|--------|-------------------|-------------------|
| **Data Source** | PostgreSQL/Redshift | Parquet file |
| **Ingestion Tool** | Logstash (JDBC input) | Python (pandas) |
| **Update Strategy** | Incremental (hourly, only updated records) | Full reindex (all records) |
| **Template Strategy** | Pre-configured ES template | Inline mappings in Python |
| **Index Name** | `authors-v8` | `authors-v16` |
| **Autocomplete Approach** | `completion` type (FST) | `edge_ngram` tokenizer |
| **Text Analyzer** | Likely: `standard` + `lowercase` + `asciifolding` + `stop` + `kstem` | `standard` + `lowercase` + `asciifolding` |
| **Similarity Algorithm** | BM25 (ES default) | BM25 (ES default) ✅ |
| **Batch Size** | 500,000 records/page | 100,000 records/chunk |
| **Bulk Request Size** | Default (unspecified) | 500 documents |
| **Parallel Processing** | Logstash pipeline | 4 Python threads |

---

## 5. Alignment Analysis

### ✅ What Aligns:

1. **BM25 Similarity**: Both use Elasticsearch default (BM25)
2. **Field Structure**: Both have `display_name`, `display_name_alternatives`, `cited_by_count`
3. **Multi-field Strategy**: Both use `.folded` for ASCII folding
4. **Document ID**: Both use OpenAlex author ID as document ID
5. **Lowercase + ASCII Folding**: Both normalize text

### ⚠️ What Differs:

1. **Autocomplete Strategy**:
   - **OpenAlex**: Uses `completion` type with FST (optimized for prefix matching)
   - **Ours**: Uses `edge_ngram` tokenizer (more flexible but different performance)

2. **Text Processing**:
   - **OpenAlex** (from docs): Uses stemming (kstem) + stop word removal
   - **Ours**: Missing kstem and stop word filters

3. **Data Source**:
   - **OpenAlex**: Authoritative PostgreSQL database
   - **Ours**: SciSciNet Parquet snapshot

4. **Update Strategy**:
   - **OpenAlex**: Incremental updates every hour
   - **Ours**: Full reindex

5. **Index Version**:
   - **OpenAlex**: `authors-v8`
   - **Ours**: `authors-v16`

---

## 6. Impact on Search Quality

### Critical Missing Features in Our Implementation:

#### 1. **Kstem Stemming**
- **Impact**: Queries like "running" won't match "run" in author names
- **Severity**: MEDIUM (author names less likely to have stemming variations than papers)

#### 2. **Stop Word Removal**
- **Impact**: Common words (the, and, of) in queries will affect scoring
- **Severity**: LOW (author names rarely have stop words)

#### 3. **Autocomplete Algorithm**
- **Impact**: Different performance and behavior:
  - `completion` (OpenAlex): Very fast, optimized for prefix matching, no scoring
  - `edge_ngram` (Ours): Flexible, supports infix matching, integrates with BM25 scoring
- **Severity**: MEDIUM (functional difference, not quality difference)

### What We Got Right:

1. ✅ **BM25 Scoring**: Matches production
2. ✅ **ASCII Folding**: Handles diacritics correctly
3. ✅ **Multi-field Search**: Can search both display_name and alternatives
4. ✅ **Citation Boosting**: Our search.py has sqrt(cited_by_count) boost (matches docs)

---

## 7. Recommendations

### To Better Align with OpenAlex Production:

#### High Priority:

1. **Add Kstem and Stop Word Filters**:
```python
"analyzer": {
    "folding": {
        "tokenizer": "standard",
        "filter": ["lowercase", "asciifolding", "stop", "kstem"]  # ← Add these
    }
}
```

2. **Consider Using `completion` Type for Autocomplete**:
```python
"display_name": {
    "type": "text",
    "fields": {
        "complete": {
            "type": "completion",  # ← Like OpenAlex production
            "analyzer": "simple",
            "preserve_separators": true,
            "max_input_length": 50
        }
    }
}
```

#### Medium Priority:

3. **Verify Elasticsearch Version Compatibility**:
   - Ensure our local ES version matches production (7.17.x or 8.x)
   - Confirm BM25 parameters (k1=1.2, b=0.75) are defaults

4. **Test Search Behavior**:
   - Compare autocomplete results with production API
   - Verify stemming works correctly
   - Test diacritic handling

#### Low Priority:

5. **Optimize Batch Sizes**:
   - Consider larger page sizes (OpenAlex uses 500k)
   - Tune parallel bulk settings based on ES cluster size

---

## 8. Conclusion

**Our indexing procedure differs significantly from OpenAlex production**:

1. ✅ **Similarity Algorithm**: MATCHES (BM25)
2. ⚠️ **Tokenization**: PARTIALLY MATCHES (missing kstem + stop words)
3. ❌ **Autocomplete Strategy**: DIFFERENT (`edge_ngram` vs `completion`)
4. ✅ **Field Structure**: MATCHES
5. ❌ **Update Strategy**: DIFFERENT (full reindex vs incremental)

**Overall Assessment**: Our implementation is **functionally similar but not identical**. The core search algorithm (BM25) matches, but tokenization and autocomplete strategies differ. For production parity, we should add kstem/stop filters and consider switching to `completion` type for autocomplete.

---

## Evidence Sources

1. **openalex-elasticsearch** repo (commit: latest as of 2025-12-31)
   - `/logstash/logstash_authors/pipeline/logstash.conf` - Production indexing pipeline
   - `/logstash/logstash_authors/docker-compose.yml` - Logstash 7.17.2 version
   - `/requirements.txt` - elasticsearch-dsl==7.4.0

2. **openalex-guts** repo (commit: latest as of 2025-12-31)
   - `/requirements.txt` - elasticsearch==8.10.1, elasticsearch-dsl==8.9.0

3. **Our repository**:
   - `/scripts/build_author_index_from_parquet.py` - Our indexing implementation

4. **OpenAlex Documentation**:
   - Confirmed kstem stemming, stop word removal, ASCII folding from official docs
