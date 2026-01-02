"""
Create sample authors_details.parquet with SciSciNet v2 schema for testing

Uses REAL author IDs and data from OpenAlex API (fetched 2024-12-24)

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

# REAL data from OpenAlex API (fetched 2024-12-24)
data = {
    'authorid': [
        'https://openalex.org/A5109805546',
        'https://openalex.org/A5083138872',
        'https://openalex.org/A5111921673',
        'https://openalex.org/A5038745913',
        'https://openalex.org/A5068951558',
        'https://openalex.org/A5112581527',
        'https://openalex.org/A5037710835',
        'https://openalex.org/A5072318964',
    ],
    'orcid': [
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    ],
    'display_name': [
        'Albert Einstein',
        'Albert Einstein',
        'Albert Einstein',
        'Marie Curie',
        'Assunta Pelosi',
        'Marie Curie',
        'Richard P. Feynman',
        'Richard Feynman',
    ],
    'display_name_alternatives': [
        '["Albert Einstein", "Albert Einſtein", "ALBERT EINSTEIN", "Albert. Einstein"]',
        '["Albert Einstein", "A. EINSTEIN", "Einstein Albert", "A. Einstein"]',
        '["Albert Einstein", "A. Einstein", "Einstein, Albert", "ALBERT EINSTEIN", "A. EINSTEIN"]',
        '["Marie Curie", "M. Curie", "M. M. E. Curie", "M Curie"]',
        '["Assunta Pelosi", "A. Pelosi", "Assunta PELOSI", "A Pelosi"]',
        '["Marie Curie", "Marie Sklodovska Curie"]',
        '["Richard P. Feynman", "Richard Phillips Feynman", "Richard Feynman", "R.P. Feynman", "R. P. FEYNMAN", "R. P. Feynman"]',
        '["Richard Feynman", "Richard P Feynman", "R. Feynman", "R.P. Feynman", "R. P. Feynman"]',
    ],
    'works_count': [
        279,
        48,
        291,
        85,
        55,
        6,
        455,
        25,
    ],
    'cited_by_count': [
        19081,
        20097,
        4154,
        283,
        914,
        98,
        74165,
        489,
    ],
    'last_known_institution': [
        'Unknown',
        'Unknown',
        'Unknown',
        'Unknown',
        'Université Pierre et Marie Curie',
        'Unknown',
        'California Institute of Technology',
        'Unknown',
    ],
    'works_api_url': [
        'https://api.openalex.org/works?filter=author.id:A5109805546',
        'https://api.openalex.org/works?filter=author.id:A5083138872',
        'https://api.openalex.org/works?filter=author.id:A5111921673',
        'https://api.openalex.org/works?filter=author.id:A5038745913',
        'https://api.openalex.org/works?filter=author.id:A5068951558',
        'https://api.openalex.org/works?filter=author.id:A5112581527',
        'https://api.openalex.org/works?filter=author.id:A5037710835',
        'https://api.openalex.org/works?filter=author.id:A5072318964',
    ],
    'updated_date': [
        '2024-12-24',
        '2024-12-24',
        '2024-12-24',
        '2024-12-24',
        '2024-12-24',
        '2024-12-24',
        '2024-12-24',
        '2024-12-24',
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

print(f"✓ Created sample parquet with REAL OpenAlex data: {output_file}")
print(f"  Rows: {len(table)}")
print(f"  Columns: {len(table.column_names)}")
print(f"  Data fetched from OpenAlex API: 2024-12-24")
print(f"  Schema:")
for field in schema:
    print(f"    {field.name}: {field.type}")
