"""
Create sample authors parquet for autocomplete testing.

Extracts unique author IDs from real autocomplete API responses and fetches
their full details to create a test parquet file.

This ensures our test database contains exactly the authors that appear in
the API responses, allowing for valid comparisons.
"""
import json
import time
import requests
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path

FIXTURES_FILE = Path(__file__).parent / "fixtures" / "openalex_autocomplete_responses.json"
OUTPUT_FILE = Path(__file__).parent / "fixtures" / "sample_authors_autocomplete.parquet"
API_BASE = "https://api.openalex.org"


def load_api_responses():
    """Load saved autocomplete responses"""
    with open(FIXTURES_FILE, 'r') as f:
        return json.load(f)


def extract_unique_author_ids(responses):
    """Extract all unique author IDs from API responses"""
    author_ids = set()

    for query, results in responses.items():
        for result in results:
            author_id = result.get('id', '')
            if author_id:
                author_ids.add(author_id)

    return sorted(author_ids)


def fetch_author_details(author_id, polite_email="test@example.com"):
    """Fetch full author details from OpenAlex API"""
    url = author_id  # author_id is already full URL
    headers = {
        "User-Agent": f"OpenAlexValidation/1.0 (mailto:{polite_email})"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"  ❌ Error fetching {author_id}: {e}")
        return None


def create_parquet_from_authors(authors, output_file):
    """Create parquet file with SciSciNet v2 schema"""
    data = {
        'authorid': [],
        'orcid': [],
        'display_name': [],
        'display_name_alternatives': [],
        'works_count': [],
        'cited_by_count': [],
        'last_known_institution': [],
        'works_api_url': [],
        'updated_date': [],
    }

    for author in authors:
        # Extract data
        author_id = author.get('id', '')
        orcid = author.get('orcid')
        display_name = author.get('display_name', '')

        # display_name_alternatives as JSON string
        alts = author.get('display_name_alternatives', [])
        alts_json = json.dumps(alts) if alts else '[]'

        works_count = author.get('works_count', 0)
        cited_by_count = author.get('cited_by_count', 0)

        # Last known institution
        affiliations = author.get('last_known_institutions', [])
        if affiliations and len(affiliations) > 0:
            last_inst = affiliations[0].get('display_name', 'Unknown')
        else:
            last_inst = 'Unknown'

        works_api_url = author.get('works_api_url', '')
        updated_date = author.get('updated_date', '2025-12-31')

        # Append to data
        data['authorid'].append(author_id)
        data['orcid'].append(orcid)
        data['display_name'].append(display_name)
        data['display_name_alternatives'].append(alts_json)
        data['works_count'].append(works_count)
        data['cited_by_count'].append(cited_by_count)
        data['last_known_institution'].append(last_inst)
        data['works_api_url'].append(works_api_url)
        data['updated_date'].append(updated_date)

    # Create PyArrow table
    schema = pa.schema([
        ('authorid', pa.large_string()),
        ('orcid', pa.large_string()),
        ('display_name', pa.large_string()),
        ('display_name_alternatives', pa.large_string()),
        ('works_count', pa.int64()),
        ('cited_by_count', pa.int64()),
        ('last_known_institution', pa.large_string()),
        ('works_api_url', pa.large_string()),
        ('updated_date', pa.large_string()),
    ])

    table = pa.table(data, schema=schema)

    # Save to parquet
    output_file.parent.mkdir(exist_ok=True, parents=True)
    pq.write_table(table, output_file)

    return len(table)


def main():
    print("=" * 80)
    print("CREATING SAMPLE PARQUET FROM AUTOCOMPLETE RESPONSES")
    print("=" * 80)
    print()

    # Load responses
    print("→ Loading autocomplete responses...")
    responses = load_api_responses()
    print(f"✓ Loaded {len(responses)} queries")
    print()

    # Extract unique author IDs
    print("→ Extracting unique author IDs...")
    author_ids = extract_unique_author_ids(responses)
    print(f"✓ Found {len(author_ids)} unique authors")
    print()

    # Fetch author details
    print("→ Fetching author details from API...")
    authors = []

    for i, author_id in enumerate(author_ids, 1):
        print(f"  [{i}/{len(author_ids)}] {author_id}...", end=" ")

        author = fetch_author_details(author_id)
        if author:
            authors.append(author)
            print("✓")
        else:
            print("✗ (skipped)")

        # Be polite
        if i < len(author_ids):
            time.sleep(0.1)

    print(f"\n✓ Fetched {len(authors)} author records")
    print()

    # Create parquet
    print("→ Creating parquet file...")
    num_rows = create_parquet_from_authors(authors, OUTPUT_FILE)
    print(f"✓ Created parquet with {num_rows} authors")
    print(f"  File: {OUTPUT_FILE}")
    print()

    print("=" * 80)
    print("✅ COMPLETE")
    print("=" * 80)


if __name__ == '__main__':
    main()
