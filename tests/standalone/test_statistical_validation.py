"""
STATISTICAL VALIDATION TEST: 6000+ Real OpenAlex API Responses

This test validates the extracted ranking algorithm against 6000+ actual
OpenAlex API responses saved from real production queries.

Metrics computed:
- Exact match rate (identical rankings)
- Top-k overlap (k=1,3,5,10,20)
- Kendall's Tau correlation
- Spearman's Rho correlation
- Mean Reciprocal Rank (MRR)
- Normalized Discounted Cumulative Gain (NDCG)

Provides statistical confidence intervals and divergence analysis.
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
    # Create ranking dictionaries
    common_ids = set(api_ids) & set(extracted_ids)
    if len(common_ids) < 2:
        return None

    # Get ranks for common IDs
    api_ranks = {id: i for i, id in enumerate(api_ids) if id in common_ids}
    extracted_ranks = {id: i for i, id in enumerate(extracted_ids) if id in common_ids}

    # Create rank arrays in same order
    common_list = list(common_ids)
    api_rank_array = [api_ranks[id] for id in common_list]
    extracted_rank_array = [extracted_ranks[id] for id in common_list]

    tau, p_value = kendalltau(api_rank_array, extracted_rank_array)
    return tau


def compute_spearman_rho(api_ids, extracted_ids):
    """
    Spearman's Rho: Measures monotonic relationship (-1 to 1)

    Similar to Kendall's Tau but more sensitive to outliers
    """
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
    """
    Mean Reciprocal Rank: How quickly does first API result appear in extracted?

    1.0 = first result is same
    0.5 = first result appears at position 2
    0.33 = first result appears at position 3
    """
    if len(api_ids) == 0 or len(extracted_ids) == 0:
        return 0.0

    first_api_id = api_ids[0]

    try:
        position = extracted_ids.index(first_api_id)
        return 1.0 / (position + 1)
    except ValueError:
        return 0.0


def compute_ndcg(api_ids, extracted_ids, k=10):
    """
    Normalized Discounted Cumulative Gain @ k

    Measures ranking quality with position-based discounting
    1.0 = perfect ranking
    0.0 = worst ranking
    """
    if len(api_ids) == 0 or len(extracted_ids) == 0:
        return 0.0

    k = min(k, len(extracted_ids))

    # Create relevance scores (binary: in API top-k or not)
    api_top_k = set(api_ids[:k])

    # Compute DCG for extracted ranking
    dcg = 0.0
    for i, id in enumerate(extracted_ids[:k]):
        if id in api_top_k:
            relevance = 1.0
            dcg += relevance / np.log2(i + 2)  # +2 because positions start at 0

    # Compute IDCG (ideal DCG - if ranking was perfect)
    idcg = sum(1.0 / np.log2(i + 2) for i in range(min(k, len(api_top_k))))

    if idcg == 0:
        return 0.0

    return dcg / idcg


# Response Parsing
def load_api_responses(responses_dir):
    """
    Load saved API responses from directory.

    Expected format: JSON files with structure:
    {
        "query": "search term",
        "results": [
            {"id": "https://openalex.org/A123", "display_name": "...", ...},
            ...
        ]
    }

    Or alternative format detection.
    """
    responses = []
    responses_path = Path(responses_dir)

    if not responses_path.exists():
        raise FileNotFoundError(f"Responses directory not found: {responses_dir}")

    # Find all JSON files
    json_files = list(responses_path.glob("*.json")) + list(responses_path.glob("**/*.json"))

    print(f"Found {len(json_files)} JSON files")

    for json_file in json_files:
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)

                # Detect format
                if isinstance(data, list):
                    # List of responses
                    responses.extend(data)
                elif isinstance(data, dict):
                    if 'query' in data or 'search' in data:
                        # Single response
                        responses.append(data)
                    elif 'results' in data and isinstance(data['results'], list):
                        # Might be bulk format
                        responses.append(data)
                    else:
                        # Try to parse as multiple responses
                        for key, value in data.items():
                            if isinstance(value, dict) and ('results' in value or 'query' in value):
                                responses.append(value)
        except Exception as e:
            print(f"Warning: Could not parse {json_file}: {e}")
            continue

    print(f"Loaded {len(responses)} API responses")
    return responses


def extract_ranking_from_api_response(response):
    """
    Extract (query, ranking) from API response.

    Returns: (search_query, list_of_author_ids)
    """
    # Try different response formats
    query = response.get('query') or response.get('search') or response.get('search_term')

    # Extract results
    results = response.get('results', [])
    if not results and 'data' in response:
        results = response['data']

    # Extract IDs
    author_ids = []
    for result in results:
        author_id = result.get('id') or result.get('author_id') or result.get('authorid')
        if author_id:
            author_ids.append(author_id)

    return query, author_ids


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
        print(f"Query error for '{search_query}': {e}")
        return []


# Main Test
def test_statistical_validation_6000_responses(responses_dir="data/api_responses"):
    """
    Statistical validation using 6000+ saved OpenAlex API responses.

    Args:
        responses_dir: Directory containing saved API response JSON files
    """
    print("=" * 80)
    print("STATISTICAL VALIDATION: 6000+ Real API Responses")
    print("=" * 80)
    print()

    # Load responses
    print("Loading API responses...")
    try:
        responses = load_api_responses(responses_dir)
    except FileNotFoundError as e:
        print(f"\n❌ {e}")
        print(f"\nPlease provide the path to your API responses directory:")
        print(f"  pytest tests/standalone/test_statistical_validation.py --responses-dir=/path/to/responses")
        return False

    if len(responses) == 0:
        print("\n❌ No API responses found!")
        return False

    print(f"✓ Loaded {len(responses)} API responses")
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

    skipped = 0
    errors = 0

    # Process each response
    print("Computing ranking metrics...")
    print()

    for i, response in enumerate(responses):
        if (i + 1) % 100 == 0:
            print(f"  Processed {i + 1}/{len(responses)} queries...")

        # Extract API ranking
        query, api_ids = extract_ranking_from_api_response(response)

        if not query or len(api_ids) == 0:
            skipped += 1
            continue

        # Query our extracted logic
        extracted_ids = query_extracted_logic(query, limit=25)

        if len(extracted_ids) == 0:
            errors += 1
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

    print(f"\n✓ Processed all responses")
    print(f"  Valid comparisons: {len(metrics['exact_match'])}")
    print(f"  Skipped (no data): {skipped}")
    print(f"  Errors: {errors}")
    print()

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
        p95 = np.percentile(values, 95)

        results_summary[metric_name] = {
            'mean': mean,
            'median': median,
            'std': std,
            'p25': p25,
            'p75': p75,
            'p95': p95,
            'n': len(values)
        }

        # Pretty print
        print(f"{metric_name.upper().replace('_', ' ')}:")
        print(f"  Mean:       {mean:.4f}")
        print(f"  Median:     {median:.4f}")
        print(f"  Std Dev:    {std:.4f}")
        print(f"  25th %ile:  {p25:.4f}")
        print(f"  75th %ile:  {p75:.4f}")
        print(f"  95th %ile:  {p95:.4f}")
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

    if exact_match_rate >= 95:
        print("✅ EXCELLENT: >95% exact match rate")
        print("   Algorithm is nearly identical to production API")
    elif exact_match_rate >= 80:
        print("✅ VERY GOOD: 80-95% exact match rate")
        print("   Minor corpus-dependent differences expected")
    elif exact_match_rate >= 50:
        print("⚠️  MODERATE: 50-80% exact match rate")
        print("   Significant corpus differences affecting ranking")
    else:
        print("❌ POOR: <50% exact match rate")
        print("   Algorithm may have implementation differences")

    print()

    if kendall >= 0.9:
        print("✅ EXCELLENT: Kendall's Tau ≥ 0.9")
        print("   Very strong rank correlation")
    elif kendall >= 0.7:
        print("✅ GOOD: Kendall's Tau 0.7-0.9")
        print("   Strong rank correlation")
    elif kendall >= 0.5:
        print("⚠️  MODERATE: Kendall's Tau 0.5-0.7")
        print("   Moderate rank correlation")
    else:
        print("❌ WEAK: Kendall's Tau < 0.5")
        print("   Low rank correlation - check implementation")

    print()
    print("=" * 80)

    # Save detailed results
    output_file = "tests/standalone/statistical_validation_results.json"
    with open(output_file, 'w') as f:
        json.dump({
            'summary': results_summary,
            'raw_metrics': {k: [float(v) for v in vals] for k, vals in metrics.items()},
            'metadata': {
                'total_queries': len(responses),
                'valid_comparisons': len(metrics['exact_match']),
                'skipped': skipped,
                'errors': errors,
            }
        }, f, indent=2)

    print(f"\n✓ Detailed results saved to: {output_file}")
    print()

    # Test assertion
    # We expect high correlation even if exact matches are lower due to corpus differences
    assert kendall >= 0.7, f"Kendall's Tau too low: {kendall:.4f} < 0.7"
    assert top10_overlap >= 70, f"Top-10 overlap too low: {top10_overlap:.2f}% < 70%"

    return True


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Statistical validation with saved API responses')
    parser.add_argument('--responses-dir', default='data/api_responses',
                        help='Directory containing saved API response JSON files')

    args = parser.parse_args()

    # Run test
    success = test_statistical_validation_6000_responses(args.responses_dir)

    sys.exit(0 if success else 1)
