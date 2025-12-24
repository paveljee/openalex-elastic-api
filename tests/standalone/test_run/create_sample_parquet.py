"""
Create sample authors_details.parquet with SciSciNet v2 schema for testing

Schema:
- authorid: large_string
- orcid: large_string
- display_name: large_string
- display_name_alternatives: large_string
- works_count: int64
- cited_by_count: int64
- last_known_institution: large_string
- works_api_url: large_string
- updated_date: large_string
"""
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path

# Sample data matching our test fixture
data = {
    'authorid': [
        'https://openalex.org/A5023888391',
        'https://openalex.org/A5067890123',
        'https://openalex.org/A5020671929',
        'https://openalex.org/A5089234567',
        'https://openalex.org/A5034567890',
        'https://openalex.org/A5045678901',
        'https://openalex.org/A5023456789',
    ],
    'orcid': [
        None,
        'https://orcid.org/0000-0002-1234-5678',
        None,
        'https://orcid.org/0000-0003-9876-5432',
        'https://orcid.org/0000-0001-2345-6789',
        None,
        None,
    ],
    'display_name': [
        'Albert Einstein',
        'Albert Einstein',
        'Marie Curie',
        'Marie Curie',
        'John Smith',
        'John R. Smith',
        'Richard P. Feynman',
    ],
    'display_name_alternatives': [
        '["A. Einstein", "Einstein A."]',
        '["Einstein Albert"]',
        '["Maria Skłodowska-Curie", "M. Curie"]',
        '[]',
        '["J. Smith", "Smith John"]',
        '["John Robert Smith"]',
        '["Richard Feynman", "R. Feynman", "R. P. Feynman"]',
    ],
    'works_count': [
        1035,
        45,
        892,
        67,
        234,
        156,
        567,
    ],
    'cited_by_count': [
        175494,
        523,
        145678,
        1234,
        8976,
        4532,
        98765,
    ],
    'last_known_institution': [
        'Institute for Advanced Study',
        'University of California, Berkeley',
        'Sorbonne University',
        'Harvard University',
        'Stanford University',
        'Massachusetts Institute of Technology',
        'California Institute of Technology',
    ],
    'works_api_url': [
        'https://api.openalex.org/works?filter=author.id:A5023888391',
        'https://api.openalex.org/works?filter=author.id:A5067890123',
        'https://api.openalex.org/works?filter=author.id:A5020671929',
        'https://api.openalex.org/works?filter=author.id:A5089234567',
        'https://api.openalex.org/works?filter=author.id:A5034567890',
        'https://api.openalex.org/works?filter=author.id:A5045678901',
        'https://api.openalex.org/works?filter=author.id:A5023456789',
    ],
    'updated_date': [
        '2024-01-15',
        '2024-01-10',
        '2024-01-12',
        '2024-01-14',
        '2024-01-11',
        '2024-01-13',
        '2024-01-09',
    ],
}

# Create PyArrow table with correct schema (large_string for strings, int64 for counts)
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
output_file = Path(__file__).parent / "fixtures" / "sample_authors_details.parquet"
output_file.parent.mkdir(exist_ok=True)

pq.write_table(table, output_file)

print(f"✓ Created sample parquet: {output_file}")
print(f"  Rows: {len(table)}")
print(f"  Columns: {len(table.column_names)}")
print(f"  Schema:")
for field in schema:
    print(f"    {field.name}: {field.type}")
