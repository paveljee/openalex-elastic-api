"""
Create sample authors parquet directly from autocomplete responses.

Uses the data already in the autocomplete JSON (id, display_name, works_count, etc.)
without making additional API calls.
"""
import json
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path

FIXTURES_FILE = Path(__file__).parent / "fixtures" / "openalex_autocomplete_responses.json"
OUTPUT_FILE = Path(__file__).parent / "fixtures" / "sample_authors_autocomplete.parquet"


def main():
    print("=" * 80)
    print("CREATING PARQUET FROM AUTOCOMPLETE RESPONSES")
    print("=" * 80)
    print()

    # Load responses
    with open(FIXTURES_FILE, 'r') as f:
        responses = json.load(f)

    print(f"✓ Loaded {len(responses)} queries")
    print()

    # Extract unique authors with their data
    authors_dict = {}  # Use dict to deduplicate by ID

    for query, results in responses.items():
        for result in results:
            author_id = result.get('id', '')
            if author_id and author_id not in authors_dict:
                authors_dict[author_id] = result

    print(f"✓ Found {len(authors_dict)} unique authors")
    print()

    # Build parquet data
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

    for author_id, author in authors_dict.items():
        # Extract fields
        orcid = author.get('orcid')
        display_name = author.get('display_name', '')

        # Some autocomplete responses have hint or other non-standard fields
        # Try to get display_name_alternatives, default to empty list
        alts = []
        alts_json = '[]'

        works_count = author.get('works_count', 0)
        cited_by_count = author.get('cited_by_count', 0)

        # Last known institution (autocomplete usually doesn't have this)
        last_inst = 'Unknown'

        # Works API URL
        if author_id.startswith('https://openalex.org/'):
            short_id = author_id.replace('https://openalex.org/', '')
            works_api_url = f"https://api.openalex.org/works?filter=author.id:{short_id}"
        else:
            works_api_url = ''

        updated_date = '2025-12-31'

        # Append
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

    # Save
    OUTPUT_FILE.parent.mkdir(exist_ok=True, parents=True)
    pq.write_table(table, OUTPUT_FILE)

    print(f"✓ Created parquet with {len(table)} authors")
    print(f"  File: {OUTPUT_FILE}")
    print()

    # Show sample
    print("Sample authors:")
    for i in range(min(5, len(data['display_name']))):
        print(f"  - {data['display_name'][i]} (works: {data['works_count'][i]}, citations: {data['cited_by_count'][i]})")
    print()

    print("=" * 80)
    print("✅ COMPLETE")
    print("=" * 80)


if __name__ == '__main__':
    main()
