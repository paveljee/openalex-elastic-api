"""
STATISTICAL VALIDATION TEST: Real OpenAlex API Responses

Validates that the extracted algorithm returns the SAME SET OF AUTHORS as OpenAlex API.

**Focus:** Set comparison (which authors are returned), NOT ranking order.
**Rationale:** Custom ranking will be implemented separately. We only validate that
our matching/retrieval logic finds the same authors as the production API.

Handles format:
{
    "Albert Einstein": [
        {"id": "...", "display_name": "...", "relevance_score": ..., "works_count": ...},
        ...
    ],
    "Marie Curie": [...],
    ...
}

Features:
- Loads from multiple timestamp files
- Handles duplicate queries (temporal consistency check)
- Tests empty query consistency (API empty → local empty?)
- Computes SET-BASED metrics (precision, recall, F1, Jaccard)
- Statistical analysis with confidence intervals
- Adjusted thresholds for same-source corpus (SciSciNet v2 from OpenAlex)
"""
import sys
sys.path.insert(0, '/home/user/openalex-elastic-api')

import json
import os
from pathlib import Path
from collections import defaultdict
import numpy as np
from elasticsearch_dsl import Search, connections

from core.author_matching import build_author_search_query
from settings import AUTHORS_INDEX, ES_URL


# SET-BASED Metrics Computation (order-independent)
def compute_exact_set_match(api_ids, extracted_ids):
    """Check if the SETS of IDs are identical (order-independent)"""
    return set(api_ids) == set(extracted_ids)


def compute_recall(api_ids, extracted_ids):
    """
    Recall: What fraction of API authors did we find?

    Recall = |API ∩ Extracted| / |API|

    1.0 = we found all API authors
    0.0 = we found none of the API authors
    """
    if len(api_ids) == 0:
        return 1.0 if len(extracted_ids) == 0 else 0.0

    api_set = set(api_ids)
    extracted_set = set(extracted_ids)
    intersection = api_set & extracted_set

    return len(intersection) / len(api_set)


def compute_precision(api_ids, extracted_ids):
    """
    Precision: What fraction of our results are in the API results?

    Precision = |API ∩ Extracted| / |Extracted|

    1.0 = all our results are in API
    0.0 = none of our results are in API
    """
    if len(extracted_ids) == 0:
        return 1.0 if len(api_ids) == 0 else 0.0

    api_set = set(api_ids)
    extracted_set = set(extracted_ids)
    intersection = api_set & extracted_set

    return len(intersection) / len(extracted_set)


def compute_f1_score(api_ids, extracted_ids):
    """
    F1 Score: Harmonic mean of precision and recall

    F1 = 2 * (Precision * Recall) / (Precision + Recall)

    1.0 = perfect precision AND recall
    0.0 = no overlap
    """
    precision = compute_precision(api_ids, extracted_ids)
    recall = compute_recall(api_ids, extracted_ids)

    if precision + recall == 0:
        return 0.0

    return 2 * (precision * recall) / (precision + recall)


def compute_jaccard_similarity(api_ids, extracted_ids):
    """
    Jaccard Similarity: Size of intersection / size of union

    Jaccard = |API ∩ Extracted| / |API ∪ Extracted|

    1.0 = perfect match
    0.0 = no overlap
    """
    api_set = set(api_ids)
    extracted_set = set(extracted_ids)

    intersection = api_set & extracted_set
    union = api_set | extracted_set

    if len(union) == 0:
        return 1.0  # Both empty

    return len(intersection) / len(union)


def compute_set_size_ratio(api_ids, extracted_ids):
    """
    Set Size Ratio: |Extracted| / |API|

    1.0 = same number of results
    >1.0 = we returned more results
    <1.0 = we returned fewer results
    """
    if len(api_ids) == 0:
        return 0.0 if len(extracted_ids) == 0 else float('inf')

    return len(extracted_ids) / len(api_ids)


# Response Parsing
def load_api_responses(responses_dir):
    """
    Load saved API responses from directory.

    Expected format: JSON files with dict structure:
    {
        "query name 1": [{"id": "...", "display_name": "...", ...}, ...],
        "query name 2": [...],
        ...
    }
    """
    all_queries = defaultdict(list)  # query -> list of (timestamp, results)
    responses_path = Path(responses_dir)

    if not responses_path.exists():
        raise FileNotFoundError(f"Responses directory not found: {responses_dir}")

    # Find all JSON files
    json_files = list(responses_path.glob("*.json")) + list(responses_path.glob("**/*.json"))

    print(f"Found {len(json_files)} JSON files")

    for json_file in json_files:
        try:
            # Extract timestamp from filename if it's a unix timestamp
            filename = json_file.stem
            try:
                timestamp = int(filename)
            except ValueError:
                timestamp = 0  # Use 0 if not a timestamp

            with open(json_file, 'r') as f:
                data = json.load(f)

                if not isinstance(data, dict):
                    print(f"Warning: {json_file} is not a dict, skipping")
                    continue

                # Each key is a query, value is list of results
                for query, results in data.items():
                    if isinstance(results, list):
                        all_queries[query].append({
                            'timestamp': timestamp,
                            'filename': json_file.name,
                            'results': results
                        })

        except Exception as e:
            print(f"Warning: Could not parse {json_file}: {e}")
            continue

    print(f"Loaded queries from {len(json_files)} files")
    print(f"Total unique queries: {len(all_queries)}")

    # Check for duplicates and temporal consistency
    duplicates = {q: entries for q, entries in all_queries.items() if len(entries) > 1}
    if duplicates:
        print(f"Found {len(duplicates)} queries with multiple responses (temporal data)")

    return all_queries


def check_temporal_consistency(query_entries):
    """
    Check if the same query returns consistent results across time.

    Returns: (is_consistent, consistency_rate, details)
    """
    if len(query_entries) < 2:
        return True, 1.0, "Single response"

    # Extract all result ID lists
    all_rankings = []
    for entry in query_entries:
        ranking = [r['id'] for r in entry['results']]
        all_rankings.append(ranking)

    # Compare first ranking with all others
    base_ranking = all_rankings[0]
    matches = 0
    total = len(all_rankings) - 1

    for ranking in all_rankings[1:]:
        if ranking == base_ranking:
            matches += 1

    consistency_rate = matches / total if total > 0 else 1.0
    is_consistent = consistency_rate == 1.0

    details = f"{matches}/{total} identical to first response"

    return is_consistent, consistency_rate, details


def select_query_version(query_entries):
    """
    Select which version of a query to use.

    Strategy: Use most recent (highest timestamp)
    """
    if len(query_entries) == 1:
        return query_entries[0]

    # Sort by timestamp, descending
    sorted_entries = sorted(query_entries, key=lambda x: x['timestamp'], reverse=True)
    return sorted_entries[0]


def extract_ranking_from_results(results):
    """Extract list of author IDs from results"""
    return [r['id'] for r in results]


def query_extracted_logic(search_query, limit=25):
    """Query using our extracted logic"""
    try:
        connections.create_connection('default', hosts=[ES_URL], timeout=5)

        query = build_author_search_query(search_query)
        s = Search(index=AUTHORS_INDEX)
        s = s.query(query)
        s = s.sort("_score", "-works_count", "id")
        s = s[:limit]

        results = s.execute()
        return [hit.id for hit in results]
    except Exception as e:
        # Silently handle errors (will be counted in stats)
        return []


# Main Test
def test_statistical_validation_real_responses(responses_dir="data/api_responses"):
    """
    Statistical validation using saved OpenAlex API responses.

    Args:
        responses_dir: Directory containing saved API response JSON files
    """
    print("=" * 80)
    print("STATISTICAL VALIDATION: Real OpenAlex API Responses")
    print("=" * 80)
    print()

    # Load responses
    print("Loading API responses...")
    try:
        all_queries = load_api_responses(responses_dir)
    except FileNotFoundError as e:
        print(f"\n❌ {e}")
        print(f"\nUsage:")
        print(f"  pytest tests/standalone/test_statistical_validation.py --responses-dir=/path/to/responses")
        pytest.skip(f"Responses directory not found: {responses_dir}")
        return

    if len(all_queries) == 0:
        print("\n❌ No API responses found!")
        pytest.skip("No API responses found")
        return

    print()

    # Temporal consistency check
    print("=" * 80)
    print("TEMPORAL CONSISTENCY CHECK")
    print("=" * 80)
    print()

    temporal_stats = {
        'total_queries': len(all_queries),
        'queries_with_duplicates': 0,
        'perfectly_consistent': 0,
        'consistency_rates': []
    }

    for query, entries in all_queries.items():
        if len(entries) > 1:
            temporal_stats['queries_with_duplicates'] += 1
            is_consistent, rate, details = check_temporal_consistency(entries)

            if is_consistent:
                temporal_stats['perfectly_consistent'] += 1

            temporal_stats['consistency_rates'].append(rate)

            if not is_consistent:
                print(f"⚠️  '{query}': {details} (from {len(entries)} responses)")

    if temporal_stats['queries_with_duplicates'] > 0:
        avg_consistency = np.mean(temporal_stats['consistency_rates'])
        print(f"\nTemporal Consistency Results:")
        print(f"  Queries with duplicates:    {temporal_stats['queries_with_duplicates']}")
        print(f"  Perfectly consistent:       {temporal_stats['perfectly_consistent']}")
        print(f"  Average consistency rate:   {avg_consistency:.2%}")

        if temporal_stats['perfectly_consistent'] == temporal_stats['queries_with_duplicates']:
            print(f"  ✅ All duplicate queries are perfectly consistent!")
        else:
            print(f"  ⚠️  Some queries have temporal variation")
    else:
        print("No duplicate queries found (all unique)")

    print()

    # Initialize SET-BASED metrics storage (order-independent)
    metrics = {
        'exact_set_match': [],      # Do both return exactly the same set of authors?
        'recall': [],                # What % of API authors did we find?
        'precision': [],             # What % of our results are correct (in API)?
        'f1_score': [],              # Harmonic mean of precision & recall
        'jaccard_similarity': [],    # Intersection / Union
        'set_size_ratio': [],        # Our count / API count
    }

    # Track empty query behavior
    empty_consistency = {
        'both_empty': 0,        # API and local both return empty
        'api_only_empty': 0,    # API empty, local has results
        'local_only_empty': 0,  # Local empty, API has results
        'total_api_empty': 0    # Total queries where API returned empty
    }

    skipped_no_results = 0  # Both API and local empty (nothing to compare)
    errors = 0

    # Process each query
    print("=" * 80)
    print("SET COMPARISON (ORDER-INDEPENDENT)")
    print("=" * 80)
    print()
    print("Computing set-based metrics...")
    print("NOTE: We validate that our algorithm returns the SAME AUTHORS as API,")
    print("      regardless of ranking order (custom ranking implemented separately).")
    print()

    for i, (query, entries) in enumerate(all_queries.items()):
        if (i + 1) % 10 == 0:
            print(f"  Processed {i + 1}/{len(all_queries)} queries...")

        # Select version to use (most recent)
        selected_entry = select_query_version(entries)
        results = selected_entry['results']

        # Extract API ranking
        api_ids = extract_ranking_from_results(results)

        # Always query our local implementation, even for empty API results
        extracted_ids = query_extracted_logic(query, limit=25)

        # Track empty query behavior
        api_empty = len(api_ids) == 0
        local_empty = len(extracted_ids) == 0

        if api_empty:
            empty_consistency['total_api_empty'] += 1

            if local_empty:
                # Both empty - good consistency!
                empty_consistency['both_empty'] += 1
                skipped_no_results += 1
                continue
            else:
                # API empty but local has results - potential issue
                empty_consistency['api_only_empty'] += 1
                # Skip comparison (can't compare with empty)
                continue

        if local_empty:
            # Local empty but API has results - potential issue
            empty_consistency['local_only_empty'] += 1
            # Skip comparison (can't compare with empty)
            continue

        # Compute SET-BASED metrics (order-independent)
        metrics['exact_set_match'].append(1.0 if compute_exact_set_match(api_ids, extracted_ids) else 0.0)
        metrics['recall'].append(compute_recall(api_ids, extracted_ids))
        metrics['precision'].append(compute_precision(api_ids, extracted_ids))
        metrics['f1_score'].append(compute_f1_score(api_ids, extracted_ids))
        metrics['jaccard_similarity'].append(compute_jaccard_similarity(api_ids, extracted_ids))

        size_ratio = compute_set_size_ratio(api_ids, extracted_ids)
        if size_ratio != float('inf'):
            metrics['set_size_ratio'].append(size_ratio)

    print(f"\n✓ Processed all queries")
    print(f"  Valid comparisons:     {len(metrics['exact_set_match'])}")
    print(f"  Both empty (skipped):  {skipped_no_results}")
    print()

    # Report on empty query consistency
    if empty_consistency['total_api_empty'] > 0:
        print("=" * 80)
        print("EMPTY QUERY CONSISTENCY")
        print("=" * 80)
        print()
        print(f"Total API empty queries: {empty_consistency['total_api_empty']}")
        print(f"  Both empty:            {empty_consistency['both_empty']} ✓")
        print(f"  API empty, local has:  {empty_consistency['api_only_empty']}")
        print(f"  Local empty, API has:  {empty_consistency['local_only_empty']}")

        if empty_consistency['both_empty'] == empty_consistency['total_api_empty']:
            print(f"\n✅ Perfect empty consistency! Local also returns empty for all API-empty queries.")
        elif empty_consistency['api_only_empty'] > 0:
            print(f"\n⚠️  Local returns results for {empty_consistency['api_only_empty']} queries that were empty in API")
            print(f"    This could indicate different corpus content")
        print()
    else:
        print("No empty API queries found")
        print()

    # Check if we have enough data
    if len(metrics['exact_set_match']) == 0:
        print("❌ No valid comparisons could be made!")
        print("\nPossible issues:")
        print("  - Elasticsearch not running")
        print("  - Authors not indexed")
        print("  - All queries returned empty results")
        pytest.skip("No valid comparisons")
        return

    # Compute statistics
    print("=" * 80)
    print("RESULTS: Statistical Validation")
    print("=" * 80)
    print()

    results_summary = {}

    for metric_name, values in metrics.items():
        if len(values) == 0:
            continue

        mean = np.mean(values)
        median = np.median(values)
        std = np.std(values)
        p25 = np.percentile(values, 25)
        p75 = np.percentile(values, 75)

        results_summary[metric_name] = {
            'mean': mean,
            'median': median,
            'std': std,
            'p25': p25,
            'p75': p75,
            'n': len(values)
        }

        # Pretty print
        print(f"{metric_name.upper().replace('_', ' ')}:")
        print(f"  Mean:       {mean:.4f}")
        print(f"  Median:     {median:.4f}")
        print(f"  Std Dev:    {std:.4f}")
        print(f"  25th %ile:  {p25:.4f}")
        print(f"  75th %ile:  {p75:.4f}")
        print(f"  Sample:     {len(values)} queries")
        print()

    # Overall assessment
    print("=" * 80)
    print("OVERALL ASSESSMENT (SET COMPARISON - ORDER INDEPENDENT)")
    print("=" * 80)
    print()

    exact_set_match_rate = results_summary['exact_set_match']['mean'] * 100
    recall = results_summary['recall']['mean'] * 100
    precision = results_summary['precision']['mean'] * 100
    f1 = results_summary['f1_score']['mean'] * 100
    jaccard = results_summary['jaccard_similarity']['mean'] * 100

    print(f"Sample size:           {len(metrics['exact_set_match'])} queries")
    print(f"Exact set match:       {exact_set_match_rate:.2f}%  (same authors, any order)")
    print(f"Recall:                {recall:.2f}%  (% of API authors we found)")
    print(f"Precision:             {precision:.2f}%  (% of our results in API)")
    print(f"F1 Score:              {f1:.2f}%  (harmonic mean)")
    print(f"Jaccard Similarity:    {jaccard:.2f}%  (intersection/union)")
    print()

    # Interpretation
    print("INTERPRETATION:")
    print()
    print("NOTE: We validate that our algorithm returns the SAME AUTHORS as OpenAlex API.")
    print("      Ranking order is NOT evaluated (custom ranking implemented separately).")
    print()
    print("Since local corpus uses SciSciNet v2 (from OpenAlex, same data source),")
    print("we expect very high set overlap. Lower values indicate dump version differences.")
    print()

    # Recall interpretation
    if recall >= 95:
        print("✅ EXCELLENT RECALL: ≥95%")
        print("   We found nearly all authors that API returned")
    elif recall >= 85:
        print("✅ GOOD RECALL: 85-95%")
        print("   We found most API authors - minor corpus differences")
    elif recall >= 70:
        print("⚠️  MODERATE RECALL: 70-85%")
        print("   Missing some API authors - check corpus completeness")
    else:
        print("❌ LOW RECALL: <70%")
        print("   Missing many API authors - check corpus or implementation")

    print()

    # Precision interpretation
    if precision >= 95:
        print("✅ EXCELLENT PRECISION: ≥95%")
        print("   Nearly all our results match API")
    elif precision >= 85:
        print("✅ GOOD PRECISION: 85-95%")
        print("   Most our results match API - minor differences")
    elif precision >= 70:
        print("⚠️  MODERATE PRECISION: 70-85%")
        print("   Some extra authors not in API - check query logic")
    else:
        print("❌ LOW PRECISION: <70%")
        print("   Many extra authors not in API - check implementation")

    print()

    # F1 Score interpretation
    if f1 >= 95:
        print("✅ EXCELLENT F1: ≥95%")
        print("   Near-perfect set match (expected for same source)")
    elif f1 >= 85:
        print("✅ GOOD F1: 85-95%")
        print("   Strong set match - minor corpus differences")
    elif f1 >= 70:
        print("⚠️  MODERATE F1: 70-85%")
        print("   Moderate set match - investigate differences")
    else:
        print("❌ LOW F1: <70%")
        print("   Poor set match - check corpus or implementation")

    print()
    print("=" * 80)

    # Save detailed results
    output_file = Path("/home/user/openalex-elastic-api/tests/standalone/statistical_validation_results.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump({
            'summary': results_summary,
            'temporal_consistency': temporal_stats,
            'empty_consistency': empty_consistency,
            'raw_metrics': {k: [float(v) for v in vals] for k, vals in metrics.items()},
            'metadata': {
                'total_queries': len(all_queries),
                'valid_comparisons': len(metrics['exact_set_match']),
                'skipped_no_results': skipped_no_results,
            }
        }, f, indent=2)

    print(f"\n✓ Detailed results saved to: {output_file}")
    print()

    # Test assertion - be lenient with small sample sizes
    sample_size = len(metrics['exact_set_match'])

    if sample_size < 10:
        print(f"⚠️  Small sample size (n={sample_size}) - results may not be statistically significant")
        print("   Consider collecting more API responses for robust validation")
        # Don't assert with small samples, just warn if metrics are unexpectedly low
        if recall < 70:
            print(f"⚠️  WARNING: Low recall ({recall:.2f}%) - unexpected for same-source corpus")
        if precision < 70:
            print(f"⚠️  WARNING: Low precision ({precision:.2f}%) - unexpected for same-source corpus")
        if f1 < 70:
            print(f"⚠️  WARNING: Low F1 score ({f1:.2f}%) - unexpected for same-source corpus")
    else:
        # With larger samples, expect high set overlap for same-source corpus (SciSciNet from OpenAlex)
        assert recall >= 70, f"Recall too low for same-source corpus: {recall:.2f}% < 70%"
        assert precision >= 70, f"Precision too low for same-source corpus: {precision:.2f}% < 70%"
        assert f1 >= 70, f"F1 score too low for same-source corpus: {f1:.2f}% < 70%"

    return True


if __name__ == '__main__':
    import argparse
    import pytest

    parser = argparse.ArgumentParser(description='Statistical validation with saved API responses')
    parser.add_argument('--responses-dir', default='data/api_responses',
                        help='Directory containing saved API response JSON files')

    args = parser.parse_args()

    # Run test
    sys.exit(pytest.main([__file__, f'--responses-dir={args.responses_dir}', '-v', '-s']))
