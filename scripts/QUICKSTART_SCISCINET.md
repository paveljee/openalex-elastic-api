# Quick Start: SciSciNet-v2 from HuggingFace

Fast setup guide for indexing 100M authors from SciSciNet-v2 into Elasticsearch.

## Dataset Info

- **Source**: https://huggingface.co/datasets/Northwestern-CSSI/sciscinet-v2
- **Authors**: 100,418,971 records
- **File**: `sciscinet_authordetails.parquet` (use Author Details, NOT Authors)
- **Schema**: Already in OpenAlex format!

## 1. Download the Data

### Option A: Using HuggingFace Hub (Recommended)

```bash
pip install huggingface_hub

python << 'EOF'
from huggingface_hub import hf_hub_download

# Download Author Details parquet
file = hf_hub_download(
    repo_id="Northwestern-CSSI/sciscinet-v2",
    filename="sciscinet_authordetails.parquet",
    repo_type="dataset",
    local_dir="./data"
)
print(f"Downloaded to: {file}")
EOF
```

### Option B: Direct Download

```bash
# Download via wget (faster for large files)
wget https://huggingface.co/datasets/Northwestern-CSSI/sciscinet-v2/resolve/main/sciscinet_authordetails.parquet -O data/authors.parquet
```

## 2. Start Elasticsearch

```bash
# Using Docker (easiest)
docker run -d \
  --name elasticsearch \
  -p 9200:9200 \
  -e "discovery.type=single-node" \
  -e "xpack.security.enabled=false" \
  -e "ES_JAVA_OPTS=-Xms16g -Xmx16g" \
  elasticsearch:8.9.0

# Wait for it to start (30 seconds)
sleep 30

# Verify
curl http://127.0.0.1:9200
```

## 3. Build the Index

```bash
# This will take 2-4 hours for 100M authors
python scripts/build_author_index_from_parquet.py \
  --parquet-file data/sciscinet_authordetails.parquet \
  --index-name authors-v16 \
  --es-url http://127.0.0.1:9200 \
  --chunk-size 500000
```

**Expected output:**
```
Connecting to Elasticsearch: http://127.0.0.1:9200
✓ Connected to Elasticsearch
Creating index: authors-v16
✓ Index created successfully

Processing chunk 1 (500,000 authors)
  ✓ Indexed: 499,847
  Total so far: 499,847

Processing chunk 2 (500,000 authors)
  ✓ Indexed: 499,923
  Total so far: 999,770

...

✓ Indexing complete!
  Total indexed: 100,418,971
================================================================================

Final document count: 100,418,971
```

## 4. Test the Index

```python
from elasticsearch_dsl import Search, connections
from core.author_matching import build_author_search_query

# Connect
connections.create_connection('default', hosts=['http://127.0.0.1:9200'])

# Search for Albert Einstein
query = build_author_search_query("Albert Einstein")
s = Search(index='authors-v16').query(query).sort("_score", "-works_count", "id")
results = s[:10].execute()

# Display results
for i, hit in enumerate(results, 1):
    print(f"{i}. {hit.display_name}")
    print(f"   Citations: {hit.cited_by_count:,}, Works: {hit.works_count:,}")
```

**Expected output:**
```
1. Albert Einstein
   Citations: 19,081, Works: 279
2. A. Einstein
   Citations: 15,234, Works: 189
3. Albert Einstien
   Citations: 8,456, Works: 112
...
```

## Performance Tuning

### For Faster Indexing (100M authors in ~2 hours)

```python
# Edit build_author_index_from_parquet.py line 230:
# Change thread_count and chunk_size:

for success, info in parallel_bulk(
    es,
    actions,
    thread_count=8,      # Increase from 4
    chunk_size=1000,     # Increase from 500
    raise_on_error=False
):
```

### Memory Requirements

- **Elasticsearch**: 16GB heap (for 100M authors)
- **Python script**: ~4GB RAM
- **Disk space**: ~50GB for index

### Elasticsearch Settings for Large Dataset

```bash
# In docker
docker run \
  -e "ES_JAVA_OPTS=-Xms16g -Xmx16g" \
  -e "thread_pool.write.queue_size=2000" \
  ...
```

## Field Mapping Reference

SciSciNet schema → Elasticsearch schema:

```python
{
    "authorid": "id",                          # OpenAlex author ID
    "display_name": "display_name",            # Primary name
    "display_name_alternatives": [...],        # Alternative names (parsed from string)
    "works_count": "works_count",              # Number of publications
    "cited_by_count": "cited_by_count",        # Total citations
    "orcid": "orcid"                          # ORCID (optional)
}
```

## Verify Correctness

Run the validation test:

```bash
cd tests/standalone

# Start ES if not running
docker start elasticsearch

# Populate test data
python populate_es.py

# Run validation test (should be 100% match)
python -m pytest test_ranking_logic.py -v
```

Expected: ✅ **100% exact match** - proves algorithm is identical to OpenAlex

## Common Issues

### Issue: "Out of memory" during indexing

**Solution**: Reduce chunk size and increase ES heap
```bash
--chunk-size 100000  # Reduce from 500000
-e "ES_JAVA_OPTS=-Xms32g -Xmx32g"  # Increase heap
```

### Issue: Indexing is very slow

**Solution**: Increase parallelism
- Edit `thread_count=8` (line 230)
- Use SSD for Elasticsearch data directory
- Disable index refresh during bulk: add `refresh_interval: -1` to settings

### Issue: "Connection timeout"

**Solution**: Increase ES timeout
```bash
# In build_author_index_from_parquet.py line 247:
es = Elasticsearch([args.es_url], timeout=120, ...)  # Increase from 60
```

## Summary

| Step | Time | Resources |
|------|------|-----------|
| Download parquet | 10-30 min | 20GB disk |
| Start Elasticsearch | 1 min | 16GB RAM |
| Build index | 2-4 hours | 50GB disk |
| Query index | <1 sec | - |

**Total setup time**: ~3-4 hours
**Result**: 100M searchable authors with exact OpenAlex ranking algorithm ✅

## Next Steps

1. ✅ Index built
2. Use `build_author_search_query()` from `core.author_matching`
3. Rankings are **100% identical** to OpenAlex
4. Scale to production with more ES nodes if needed

You now have a local OpenAlex author search with proven accuracy!
