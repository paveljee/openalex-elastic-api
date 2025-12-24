# Building Author Index from SciSciNet Parquet

Complete guide to index your SciSciNet author data into Elasticsearch and query it using the extracted OpenAlex matching logic.

## Prerequisites

```bash
pip install pandas pyarrow elasticsearch tqdm
```

## Step 1: Download Your Author Data

Download the SciSciNet authors parquet file from:
- **GitHub**: https://github.com/kellogg-cssi/SciSciNet
- **Figshare**: https://figshare.com/collections/SciSciNet/6076908
- **Google Cloud**: gs://sciscinet (if using GCS)

Example filenames:
- `SciSciNet_Authors_Gender.parquet`
- `sciscinet_authors.parquet`

## Step 2: Start Elasticsearch

### Option A: Using Docker (Recommended)

```bash
docker run -d \
  --name elasticsearch \
  -p 9200:9200 \
  -e "discovery.type=single-node" \
  -e "xpack.security.enabled=false" \
  -e "ES_JAVA_OPTS=-Xms4g -Xmx4g" \
  elasticsearch:8.9.0
```

### Option B: Manual Installation

```bash
# Download and extract
wget https://artifacts.elastic.co/downloads/elasticsearch/elasticsearch-8.9.0-linux-x86_64.tar.gz
tar -xzf elasticsearch-8.9.0-linux-x86_64.tar.gz
cd elasticsearch-8.9.0

# Configure (edit config/elasticsearch.yml)
echo "xpack.security.enabled: false" >> config/elasticsearch.yml
echo "discovery.type: single-node" >> config/elasticsearch.yml

# Start
./bin/elasticsearch -d
```

Verify it's running:
```bash
curl http://127.0.0.1:9200
```

## Step 3: Inspect Your Parquet Schema

First, check what fields are in your parquet file:

```python
import pandas as pd

# Load first few rows
df = pd.read_parquet('your_authors.parquet', nrows=5)
print(df.columns.tolist())
print(df.head())
```

Common SciSciNet author fields:
- `AuthorID` or `author_id` → maps to `id`
- `Author_Name` or `display_name` → maps to `display_name`
- `Productivity` or `works_count` → maps to `works_count`
- `H-index` or `h_index` → maps to `h_index`
- `cited_by_count` → maps to `cited_by_count`

**IMPORTANT**: Edit `build_author_index_from_parquet.py` line 64-85 to match YOUR field names!

## Step 4: Build the Index

### For Small Files (<10M authors)

```bash
python scripts/build_author_index_from_parquet.py \
  --parquet-file /path/to/authors.parquet \
  --index-name authors-v16 \
  --es-url http://127.0.0.1:9200
```

### For Large Files (>10M authors)

```bash
# Delete existing index and use larger chunks
python scripts/build_author_index_from_parquet.py \
  --parquet-file /path/to/SciSciNet_Authors.parquet \
  --index-name authors-v16 \
  --es-url http://127.0.0.1:9200 \
  --delete-existing \
  --chunk-size 500000
```

Expected output:
```
Connecting to Elasticsearch: http://127.0.0.1:9200
✓ Connected to Elasticsearch
  Cluster: openalex-test
  Version: 8.9.0
Creating index: authors-v16
✓ Index created successfully

Indexing authors to: authors-v16
================================================================================

Processing chunk 1 (100,000 authors)
  ✓ Indexed: 99,847
  Total so far: 99,847

Processing chunk 2 (100,000 authors)
  ✓ Indexed: 99,923
  Total so far: 199,770

...

✓ Indexing complete!
  Total indexed: 100,400,000
  Total failed: 0
================================================================================

Final document count: 100,400,000
```

## Step 5: Query Your Index

Use the extracted matching logic:

```python
from elasticsearch_dsl import Search, connections
from core.author_matching import build_author_search_query

# Connect
connections.create_connection('default', hosts=['http://127.0.0.1:9200'])

# Build query using extracted OpenAlex logic
query = build_author_search_query("Albert Einstein")

# Execute
s = Search(index='authors-v16')
s = s.query(query)
s = s.sort("_score", "-works_count", "id")
results = s[:25].execute()

# Display results
for i, hit in enumerate(results, 1):
    print(f"{i}. {hit.display_name}")
    print(f"   Score: {hit.meta.score:.2f}")
    print(f"   Citations: {hit.cited_by_count:,}")
    print(f"   Works: {hit.works_count:,}")
    print()
```

## Performance Tips

### 1. Adjust Elasticsearch Memory

For large datasets (>50M authors), increase heap size:

```bash
# In docker
docker run -e "ES_JAVA_OPTS=-Xms16g -Xmx16g" ...

# Or in elasticsearch.yml
export ES_JAVA_OPTS="-Xms16g -Xmx16g"
```

### 2. Optimize Shards

For 100M authors, use more shards:

Edit line 33 in `build_author_index_from_parquet.py`:
```python
"number_of_shards": 10,  # Increase for large datasets
```

### 3. Disable Refresh During Indexing

For faster bulk indexing, temporarily disable refresh:

```python
es.indices.put_settings(
    index='authors-v16',
    body={'index': {'refresh_interval': '-1'}}
)

# ... do bulk indexing ...

# Re-enable after indexing
es.indices.put_settings(
    index='authors-v16',
    body={'index': {'refresh_interval': '1s'}}
)
es.indices.refresh(index='authors-v16')
```

## Troubleshooting

### "No such file or directory"
Check parquet file path is absolute, not relative.

### "Connection refused"
Elasticsearch isn't running. Check:
```bash
curl http://127.0.0.1:9200
```

### "Out of memory" during indexing
- Reduce `--chunk-size` (default 100000 → 50000)
- Increase ES heap: `-Xmx` parameter
- Process in multiple batches

### "Field name too long"
Some display names may be too long. Add validation:
```python
if len(doc['display_name']) > 32766:
    doc['display_name'] = doc['display_name'][:32766]
```

### Slow queries
Add `.source(includes=['id', 'display_name', 'cited_by_count', 'works_count'])` to limit returned fields.

## Validation

After indexing, validate the results match OpenAlex behavior:

```bash
# Run the ranking comparison test
cd tests/standalone
python -m pytest test_ranking_logic.py -v
```

Expected: 100% exact match between original and extracted logic.

## Next Steps

1. ✅ Index built successfully
2. ✅ Use `core.author_matching.build_author_search_query()` for queries
3. ✅ 100% identical to OpenAlex ranking algorithm
4. ✅ Proven with comprehensive tests

Your local author search is now ready with the exact same algorithm as OpenAlex!
