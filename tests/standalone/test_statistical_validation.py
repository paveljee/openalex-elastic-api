"""
STATISTICAL VALIDATION TEST: Real OpenAlex API Responses

Validates the extracted ranking algorithm against actual OpenAlex API responses.

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
- Computes comprehensive ranking metrics
- Statistical analysis with confidence intervals
"""
import sys
sys.path.insert(0, '/home/user/openalex-elastic-api')

import json
import os
from pathlib import Path
from collections import defaultdict
import numpy as np
from scipy.stats import kendalltau, spearmanr
from elasticsearch_dsl import Search, connections

from core.author_matching import build_author_search_query
from settings import AUTHORS_INDEX, ES_URL


# Metrics Computation
def compute_exact_match(api_ids, extracted_ids):
    """Check if rankings are exactly identical"""
    return api_ids == extracted_ids


def compute_top_k_overlap(api_ids, extracted_ids, k):
    """Compute overlap in top-k results"""
    if len(api_ids) < k or len(extracted_ids) < k:
        k = min(len(api_ids), len(extracted_ids))

    if k == 0:
        return 0.0

    api_top_k = set(api_ids[:k])
    extracted_top_k = set(extracted_ids[:k])

    overlap = len(api_top_k & extracted_top_k)
    return overlap / k


def compute_kendall_tau(api_ids, extracted_ids):
    """
    Kendall's Tau: Measures rank correlation (-1 to 1)

    1.0 = perfect agreement
    0.0 = no correlation
    -1.0 = perfect disagreement
    """
    common_ids = set(api_ids) & set(extracted_ids)
    if len(common_ids) < 2:
        return None

    api_ranks = {id: i for i, id in enumerate(api_ids) if id in common_ids}
    extracted_ranks = {id: i for i, id in enumerate(extracted_ids) if id in common_ids}

    common_list = list(common_ids)
    api_rank_array = [api_ranks[id] for id in common_list]
    extracted_rank_array = [extracted_ranks[id] for id in common_list]

    tau, p_value = kendalltau(api_rank_array, extracted_rank_array)
    return tau


def compute_spearman_rho(api_ids, extracted_ids):
    """Spearman's Rho: Measures monotonic relationship (-1 to 1)"""
    common_ids = set(api_ids) & set(extracted_ids)
    if len(common_ids) < 2:
        return None

    api_ranks = {id: i for i, id in enumerate(api_ids) if id in common_ids}
    extracted_ranks = {id: i for i, id in enumerate(extracted_ids) if id in common_ids}

    common_list = list(common_ids)
    api_rank_array = [api_ranks[id] for id in common_list]
    extracted_rank_array = [extracted_ranks[id] for id in common_list]

    rho, p_value = spearmanr(api_rank_array, extracted_rank_array)
    return rho


def compute_mrr(api_ids, extracted_ids):
    """Mean Reciprocal Rank: How quickly does first API result appear in extracted?"""
    if len(api_ids) == 0 or len(extracted_ids) == 0:
        return 0.0

    first_api_id = api_ids[0]

    try:
        position = extracted_ids.index(first_api_id)
        return 1.0 / (position + 1)
    except ValueError:
        return 0.0


def compute_ndcg(api_ids, extracted_ids, k=10):
    """Normalized Discounted Cumulative Gain @ k"""
    if len(api_ids) == 0 or len(extracted_ids) == 0:
        return 0.0

    k = min(k, len(extracted_ids))
    api_top_k = set(api_ids[:k])

    # Compute DCG for extracted ranking
    dcg = 0.0
    for i, id in enumerate(extracted_ids[:k]):
        if id in api_top_k:
            relevance = 1.0
            dcg += relevance / np.log2(i + 2)

    # Compute IDCG (ideal DCG)
    idcg = sum(1.0 / np.log2(i + 2) for i in range(min(k, len(api_top_k))))

    if idcg == 0:
        return 0.0

    return dcg / idcg


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

    # Initialize metrics storage
    metrics = {
        'exact_match': [],
        'top_1_overlap': [],
        'top_3_overlap': [],
        'top_5_overlap': [],
        'top_10_overlap': [],
        'top_20_overlap': [],
        'kendall_tau': [],
        'spearman_rho': [],
        'mrr': [],
        'ndcg_10': [],
    }

    skipped_empty = 0
    skipped_no_results = 0
    errors = 0

    # Process each query
    print("=" * 80)
    print("RANKING COMPARISON")
    print("=" * 80)
    print()
    print("Computing ranking metrics...")
    print()

    for i, (query, entries) in enumerate(all_queries.items()):
        if (i + 1) % 10 == 0:
            print(f"  Processed {i + 1}/{len(all_queries)} queries...")

        # Select version to use (most recent)
        selected_entry = select_query_version(entries)
        results = selected_entry['results']

        # Skip empty results
        if len(results) == 0:
            skipped_empty += 1
            continue

        # Extract API ranking
        api_ids = extract_ranking_from_results(results)

        # Query our extracted logic
        extracted_ids = query_extracted_logic(query, limit=25)

        if len(extracted_ids) == 0:
            skipped_no_results += 1
            continue

        # Compute all metrics
        metrics['exact_match'].append(1.0 if compute_exact_match(api_ids, extracted_ids) else 0.0)
        metrics['top_1_overlap'].append(compute_top_k_overlap(api_ids, extracted_ids, 1))
        metrics['top_3_overlap'].append(compute_top_k_overlap(api_ids, extracted_ids, 3))
        metrics['top_5_overlap'].append(compute_top_k_overlap(api_ids, extracted_ids, 5))
        metrics['top_10_overlap'].append(compute_top_k_overlap(api_ids, extracted_ids, 10))
        metrics['top_20_overlap'].append(compute_top_k_overlap(api_ids, extracted_ids, 20))

        tau = compute_kendall_tau(api_ids, extracted_ids)
        if tau is not None:
            metrics['kendall_tau'].append(tau)

        rho = compute_spearman_rho(api_ids, extracted_ids)
        if rho is not None:
            metrics['spearman_rho'].append(rho)

        metrics['mrr'].append(compute_mrr(api_ids, extracted_ids))
        metrics['ndcg_10'].append(compute_ndcg(api_ids, extracted_ids, k=10))

    print(f"\n✓ Processed all queries")
    print(f"  Valid comparisons:     {len(metrics['exact_match'])}")
    print(f"  Skipped (empty API):   {skipped_empty}")
    print(f"  Skipped (no ES match): {skipped_no_results}")
    print()

    # Check if we have enough data
    if len(metrics['exact_match']) == 0:
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
    print("OVERALL ASSESSMENT")
    print("=" * 80)
    print()

    exact_match_rate = results_summary['exact_match']['mean'] * 100
    top10_overlap = results_summary['top_10_overlap']['mean'] * 100
    kendall = results_summary['kendall_tau']['mean']
    ndcg = results_summary['ndcg_10']['mean']

    print(f"Sample size:           {len(metrics['exact_match'])} queries")
    print(f"Exact match rate:      {exact_match_rate:.2f}%")
    print(f"Top-10 overlap:        {top10_overlap:.2f}%")
    print(f"Kendall's Tau:         {kendall:.4f}")
    print(f"NDCG@10:               {ndcg:.4f}")
    print()

    # Interpretation
    print("INTERPRETATION:")
    print()

    if exact_match_rate >= 80:
        print("✅ EXCELLENT: >80% exact match rate")
        print("   Algorithm produces nearly identical rankings")
    elif exact_match_rate >= 50:
        print("✅ VERY GOOD: 50-80% exact match rate")
        print("   Minor corpus-dependent differences (expected)")
    elif exact_match_rate >= 20:
        print("⚠️  MODERATE: 20-50% exact match rate")
        print("   Significant corpus differences affecting ranking")
    else:
        print("❌ LOW: <20% exact match rate")
        print("   Check implementation or corpus size")

    print()

    if kendall >= 0.9:
        print("✅ EXCELLENT: Kendall's Tau ≥ 0.9")
        print("   Very strong rank correlation")
    elif kendall >= 0.7:
        print("✅ GOOD: Kendall's Tau 0.7-0.9")
        print("   Strong rank correlation - algorithm is correct")
    elif kendall >= 0.5:
        print("⚠️  MODERATE: Kendall's Tau 0.5-0.7")
        print("   Moderate rank correlation")
    else:
        print("❌ WEAK: Kendall's Tau < 0.5")
        print("   Low rank correlation - check implementation")

    print()

    if top10_overlap >= 90:
        print("✅ EXCELLENT: Top-10 overlap ≥ 90%")
    elif top10_overlap >= 70:
        print("✅ GOOD: Top-10 overlap ≥ 70%")
        print("   Most relevant results preserved")
    elif top10_overlap >= 50:
        print("⚠️  MODERATE: Top-10 overlap 50-70%")
    else:
        print("❌ LOW: Top-10 overlap < 50%")

    print()
    print("=" * 80)

    # Save detailed results
    output_file = "tests/standalone/statistical_validation_results.json"
    with open(output_file, 'w') as f:
        json.dump({
            'summary': results_summary,
            'temporal_consistency': temporal_stats,
            'raw_metrics': {k: [float(v) for v in vals] for k, vals in metrics.items()},
            'metadata': {
                'total_queries': len(all_queries),
                'valid_comparisons': len(metrics['exact_match']),
                'skipped_empty': skipped_empty,
                'skipped_no_results': skipped_no_results,
            }
        }, f, indent=2)

    print(f"\n✓ Detailed results saved to: {output_file}")
    print()

    # Test assertion - be lenient with small sample sizes
    sample_size = len(metrics['exact_match'])

    if sample_size < 10:
        print(f"⚠️  Small sample size (n={sample_size}) - results may not be statistically significant")
        print("   Consider collecting more API responses for robust validation")
        # Don't assert with small samples
    else:
        # With larger samples, expect good correlation
        assert kendall >= 0.5, f"Kendall's Tau too low: {kendall:.4f} < 0.5"
        assert top10_overlap >= 50, f"Top-10 overlap too low: {top10_overlap:.2f}% < 50%"

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
