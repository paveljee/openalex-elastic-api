#!/usr/bin/env python3
"""
Build Elasticsearch Author Index from SciSciNet Parquet File

Loads SciSciNet author parquet data and indexes it into Elasticsearch
using the same schema and mappings as OpenAlex.

Usage:
    python build_author_index_from_parquet.py --parquet-file /path/to/authors.parquet
"""

import argparse
import pandas as pd
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk, parallel_bulk
from tqdm import tqdm
import sys


# Elasticsearch index mappings (same as OpenAlex)
AUTHOR_MAPPINGS = {
    "mappings": {
        "properties": {
            "id": {
                "type": "keyword"
            },
            "display_name": {
                "type": "text",
                "fields": {
                    "folded": {
                        "type": "text",
                        "analyzer": "folding"
                    },
                    "autocomplete": {
                        "type": "text",
                        "analyzer": "autocomplete_analyzer",
                        "search_analyzer": "standard"
                    },
                    "keyword": {
                        "type": "keyword"
                    }
                }
            },
            "display_name_alternatives": {
                "type": "text",
                "fields": {
                    "folded": {
                        "type": "text",
                        "analyzer": "folding"
                    },
                    "autocomplete": {
                        "type": "text",
                        "analyzer": "autocomplete_analyzer",
                        "search_analyzer": "standard"
                    }
                }
            },
            "cited_by_count": {
                "type": "long"
            },
            "works_count": {
                "type": "long"
            },
            "h_index": {
                "type": "long"
            },
            # Optional: if you have embeddings
            "embedding": {
                "type": "dense_vector",
                "dims": 384,  # Adjust based on your embedding dimension
                "index": True,
                "similarity": "cosine"
            }
        }
    },
    "settings": {
        "analysis": {
            "analyzer": {
                "folding": {
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"]
                },
                "autocomplete_analyzer": {
                    "tokenizer": "autocomplete_tokenizer",
                    "filter": ["lowercase", "asciifolding"]
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
        },
        "number_of_shards": 5,  # Adjust based on data size
        "number_of_replicas": 0  # No replicas for local use
    }
}


def create_index(es, index_name, delete_existing=False):
    """Create Elasticsearch index with proper mappings"""
    if delete_existing and es.indices.exists(index=index_name):
        print(f"Deleting existing index: {index_name}")
        es.indices.delete(index=index_name)

    if not es.indices.exists(index=index_name):
        print(f"Creating index: {index_name}")
        es.indices.create(index=index_name, body=AUTHOR_MAPPINGS)
        print("✓ Index created successfully")
    else:
        print(f"Index {index_name} already exists")


def map_sciscinet_to_openalex(row):
    """
    Map SciSciNet Author Details schema to OpenAlex schema.

    SciSciNet Author Details schema (from HuggingFace):
    - authorid: large_string
    - display_name: large_string
    - display_name_alternatives: large_string
    - works_count: int64
    - cited_by_count: int64
    - orcid: large_string
    - last_known_institution: large_string
    - works_api_url: large_string
    - updated_date: large_string
    """
    # Parse display_name_alternatives from string to list
    alternatives = row.get('display_name_alternatives', '')
    if isinstance(alternatives, str):
        # Split by common delimiters (adjust if needed)
        alternatives = [alt.strip() for alt in alternatives.split('|') if alt.strip()]
    elif alternatives is None:
        alternatives = []

    # Build OpenAlex-compatible document
    doc = {
        "id": row.get('authorid') or row.get('AuthorID'),
        "display_name": row.get('display_name'),
        "display_name_alternatives": alternatives,
        "works_count": int(row.get('works_count', 0)) if row.get('works_count') else 0,
        "cited_by_count": int(row.get('cited_by_count', 0)) if row.get('cited_by_count') else 0,
    }

    # Optional fields (include if available)
    if 'orcid' in row and row['orcid']:
        doc['orcid'] = row['orcid']

    if 'h_index' in row and row['h_index']:
        doc['h_index'] = int(row['h_index'])

    # Optional: Include embeddings if available
    if 'embedding' in row:
        doc['embedding'] = row['embedding']

    return doc


def generate_actions(df, index_name, batch_size=5000):
    """Generate bulk index actions from DataFrame"""
    for i in range(0, len(df), batch_size):
        batch = df.iloc[i:i+batch_size]
        for _, row in batch.iterrows():
            doc = map_sciscinet_to_openalex(row)

            # Skip if missing required fields
            if not doc['id'] or not doc['display_name']:
                continue

            yield {
                "_index": index_name,
                "_id": doc['id'],
                "_source": doc
            }


def load_parquet_chunked(parquet_file, chunk_size=100000):
    """Load parquet file in chunks to handle large files"""
    print(f"Loading parquet file: {parquet_file}")

    # Try to read in chunks
    try:
        parquet_file_obj = pd.read_parquet(parquet_file)
        total_rows = len(parquet_file_obj)
        print(f"Total authors: {total_rows:,}")

        # Process in chunks
        for i in range(0, total_rows, chunk_size):
            chunk = parquet_file_obj.iloc[i:i+chunk_size]
            yield chunk
    except Exception as e:
        print(f"Error loading parquet: {e}")
        sys.exit(1)


def index_authors(es, parquet_file, index_name, chunk_size=100000):
    """Index authors from parquet file into Elasticsearch"""
    total_indexed = 0
    total_failed = 0

    print(f"\nIndexing authors to: {index_name}")
    print("=" * 80)

    for chunk_num, chunk in enumerate(load_parquet_chunked(parquet_file, chunk_size)):
        print(f"\nProcessing chunk {chunk_num + 1} ({len(chunk):,} authors)")

        # Use parallel bulk for better performance
        actions = generate_actions(chunk, index_name)

        # Bulk index with progress bar
        success_count = 0
        error_count = 0

        for success, info in parallel_bulk(
            es,
            actions,
            thread_count=4,
            chunk_size=500,
            raise_on_error=False
        ):
            if success:
                success_count += 1
            else:
                error_count += 1
                if error_count <= 10:  # Only print first 10 errors
                    print(f"Error: {info}")

        total_indexed += success_count
        total_failed += error_count

        print(f"  ✓ Indexed: {success_count:,}")
        if error_count > 0:
            print(f"  ✗ Failed: {error_count:,}")
        print(f"  Total so far: {total_indexed:,}")

    # Refresh index
    print(f"\nRefreshing index...")
    es.indices.refresh(index=index_name)

    print("\n" + "=" * 80)
    print(f"✓ Indexing complete!")
    print(f"  Total indexed: {total_indexed:,}")
    print(f"  Total failed: {total_failed:,}")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description='Build Elasticsearch author index from SciSciNet parquet'
    )
    parser.add_argument(
        '--parquet-file',
        required=True,
        help='Path to SciSciNet authors parquet file'
    )
    parser.add_argument(
        '--index-name',
        default='authors-v16',
        help='Elasticsearch index name (default: authors-v16)'
    )
    parser.add_argument(
        '--es-url',
        default='http://127.0.0.1:9200',
        help='Elasticsearch URL (default: http://127.0.0.1:9200)'
    )
    parser.add_argument(
        '--delete-existing',
        action='store_true',
        help='Delete existing index before creating new one'
    )
    parser.add_argument(
        '--chunk-size',
        type=int,
        default=100000,
        help='Chunk size for processing (default: 100000)'
    )

    args = parser.parse_args()

    # Connect to Elasticsearch
    print(f"Connecting to Elasticsearch: {args.es_url}")
    es = Elasticsearch([args.es_url], timeout=60, max_retries=10, retry_on_timeout=True)

    # Check connection
    if not es.ping():
        print("✗ Could not connect to Elasticsearch!")
        print("  Make sure Elasticsearch is running at:", args.es_url)
        sys.exit(1)

    print("✓ Connected to Elasticsearch")
    print(f"  Cluster: {es.info()['cluster_name']}")
    print(f"  Version: {es.info()['version']['number']}")

    # Create index
    create_index(es, args.index_name, args.delete_existing)

    # Index authors
    index_authors(es, args.parquet_file, args.index_name, args.chunk_size)

    # Final stats
    count = es.count(index=args.index_name)
    print(f"\nFinal document count: {count['count']:,}")


if __name__ == '__main__':
    main()
