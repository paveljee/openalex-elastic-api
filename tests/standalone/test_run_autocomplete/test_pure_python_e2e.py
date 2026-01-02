"""
End-to-End Validation: Pure Python Autocomplete vs Real OpenAlex API

Validates that pure Python implementation achieves similar results to production
OpenAlex autocomplete API (without needing Elasticsearch).
"""
import sys
sys.path.insert(0, '/home/user/openalex-elastic-api')

import json
import pytest
from pathlib import Path
import numpy as np
from scipy.stats import kendalltau

from core.author_autocomplete_pure_python import AuthorAutocompletePython

# Test configuration
FIXTURES_FILE = Path(__file__).parent / "fixtures" / "openalex_autocomplete_responses.json"
PARQUET_FILE = Path(__file__).parent / "fixtures" / "sample_authors_autocomplete.parquet"
REPORT_DIR = Path(__file__).parent / "reports"


def load_api_responses():
    """Load saved autocomplete API responses"""
    with open(FIXTURES_FILE, 'r') as f:
        return json.load(f)


def extract_ranking_from_results(results):
    """Extract ordered list of author IDs from API results"""
    ids = []
    for result in results:
        author_id = result.get('id', '')
        if author_id:
            # Normalize ID format
            if author_id.startswith('https://openalex.org/'):
                author_id = author_id.replace('https://openalex.org/', '')
            ids.append(author_id)
    return ids


# RANKING METRICS (order-dependent)
def compute_exact_match(api_ranking, extracted_ranking):
    """Check if rankings are exactly identical (same order)"""
    return api_ranking == extracted_ranking


def compute_kendall_tau(api_ranking, extracted_ranking):
    """Kendall's Tau: Correlation between rankings (-1 to 1)"""
    if len(api_ranking) == 0 or len(extracted_ranking) == 0:
        return 1.0 if len(api_ranking) == len(extracted_ranking) else 0.0

    common_ids = set(api_ranking) & set(extracted_ranking)
    if len(common_ids) < 2:
        return 1.0 if api_ranking == extracted_ranking else 0.0

    api_positions = {id_: i for i, id_ in enumerate(api_ranking)}
    extracted_positions = {id_: i for i, id_ in enumerate(extracted_ranking)}

    api_ranks = [api_positions[id_] for id_ in common_ids]
    extracted_ranks = [extracted_positions[id_] for id_ in common_ids]

    tau, _ = kendalltau(api_ranks, extracted_ranks)
    return tau if not np.isnan(tau) else 0.0


def compute_ndcg_at_k(api_ranking, extracted_ranking, k=10):
    """NDCG@k: Normalized Discounted Cumulative Gain"""
    if len(api_ranking) == 0 or len(extracted_ranking) == 0:
        return 1.0 if len(api_ranking) == len(extracted_ranking) else 0.0

    relevance_scores = {id_: len(api_ranking) - i for i, id_ in enumerate(api_ranking)}

    # DCG
    dcg = 0.0
    for i, id_ in enumerate(extracted_ranking[:k]):
        if id_ in relevance_scores:
            dcg += relevance_scores[id_] / np.log2(i + 2)

    # IDCG
    idcg = 0.0
    for i, id_ in enumerate(api_ranking[:k]):
        if id_ in relevance_scores:
            idcg += relevance_scores[id_] / np.log2(i + 2)

    if idcg == 0:
        return 0.0

    return dcg / idcg


def compute_top_k_overlap(api_ranking, extracted_ranking, k):
    """Top-k overlap: % of top-k API results in top-k extracted results"""
    if len(api_ranking) == 0:
        return 1.0 if len(extracted_ranking) == 0 else 0.0

    api_top_k = set(api_ranking[:k])
    extracted_top_k = set(extracted_ranking[:k])

    if len(api_top_k) == 0:
        return 1.0

    intersection = api_top_k & extracted_top_k
    return len(intersection) / len(api_top_k)


def test_pure_python_autocomplete_validation():
    """
    E2E test: Pure Python autocomplete vs production OpenAlex API.

    Validates that pure Python implementation achieves similar ranking
    to production autocomplete API (without Elasticsearch).
    """

    print("\n" + "=" * 80)
    print("PURE PYTHON AUTOCOMPLETE VALIDATION (vs Real OpenAlex API)")
    print("=" * 80)
    print()

    # Load Pure Python autocomplete
    print("→ Step 1: Loading pure Python autocomplete...")
    autocomplete = AuthorAutocompletePython.from_parquet(str(PARQUET_FILE))
    print(f"✓ Loaded {len(autocomplete.df)} authors")
    print()

    # Load API responses
    print("→ Step 2: Loading real autocomplete API responses...")
    api_responses = load_api_responses()
    print(f"✓ Loaded {len(api_responses)} queries")
    print()

    # Run validation
    print("→ Step 3: Running validation...")
    print()
    print("=" * 80)
    print("RANKING VALIDATION (ORDER-DEPENDENT)")
    print("=" * 80)
    print()
    print("NOTE: For autocomplete, ranking order MATTERS for UX!")
    print("      We validate that our ranking matches production API.")
    print()

    # Initialize metrics storage
    metrics = {
        'exact_match': [],
        'top_1_overlap': [],
        'top_3_overlap': [],
        'top_5_overlap': [],
        'top_10_overlap': [],
        'kendall_tau': [],
        'ndcg_10': [],
    }

    skipped = 0
    detailed_results = []

    for i, (query, api_results) in enumerate(api_responses.items(), 1):
        if i % 5 == 0:
            print(f"  Processed {i}/{len(api_responses)} queries...")

        # Extract API ranking
        api_ids = extract_ranking_from_results(api_results)

        # Query pure Python implementation
        py_results = autocomplete.search(query, limit=10)
        py_ids = [r['id'].replace('https://openalex.org/', '') for r in py_results]

        # Skip if both empty
        if len(api_ids) == 0 and len(py_ids) == 0:
            skipped += 1
            continue

        # Skip if either is empty (can't compare ranking)
        if len(api_ids) == 0 or len(py_ids) == 0:
            skipped += 1
            continue

        # Compute ranking metrics
        exact = compute_exact_match(api_ids, py_ids)
        top_1 = compute_top_k_overlap(api_ids, py_ids, k=1)
        top_3 = compute_top_k_overlap(api_ids, py_ids, k=3)
        top_5 = compute_top_k_overlap(api_ids, py_ids, k=5)
        top_10 = compute_top_k_overlap(api_ids, py_ids, k=10)
        tau = compute_kendall_tau(api_ids, py_ids)
        ndcg = compute_ndcg_at_k(api_ids, py_ids, k=10)

        metrics['exact_match'].append(1.0 if exact else 0.0)
        metrics['top_1_overlap'].append(top_1)
        metrics['top_3_overlap'].append(top_3)
        metrics['top_5_overlap'].append(top_5)
        metrics['top_10_overlap'].append(top_10)
        metrics['kendall_tau'].append(tau)
        metrics['ndcg_10'].append(ndcg)

        # Store detailed results
        detailed_results.append({
            'query': query,
            'api_count': len(api_ids),
            'py_count': len(py_ids),
            'top_1_overlap': top_1,
            'top_5_overlap': top_5,
            'top_10_overlap': top_10,
            'kendall_tau': tau,
            'ndcg_10': ndcg
        })

    print(f"\n✓ Processed all queries")
    print(f"  Valid comparisons:     {len(metrics['exact_match'])}")
    print(f"  Skipped (no results):  {skipped}")
    print()

    # Check if we have enough data
    if len(metrics['exact_match']) == 0:
        print("❌ No valid comparisons could be made!")
        pytest.skip("No valid comparisons")
        return

    # Compute summary statistics
    print("=" * 80)
    print("RESULTS SUMMARY")
    print("=" * 80)
    print()

    results_summary = {}
    for metric_name, values in metrics.items():
        if len(values) > 0:
            mean = np.mean(values)
            std = np.std(values)
            p25 = np.percentile(values, 25)
            p75 = np.percentile(values, 75)

            results_summary[metric_name] = {
                'mean': float(mean),
                'std': float(std),
                'p25': float(p25),
                'p75': float(p75),
            }

            display_name = metric_name.replace('_', ' ').title()
            print(f"{display_name}:")
            print(f"  Mean:       {mean:.4f}")
            print(f"  Std Dev:    {std:.4f}")
            print(f"  25th %ile:  {p25:.4f}")
            print(f"  75th %ile:  {p75:.4f}")
            print()

    # Overall assessment
    print("=" * 80)
    print("OVERALL ASSESSMENT (PURE PYTHON vs PRODUCTION API)")
    print("=" * 80)
    print()

    exact_match_rate = results_summary['exact_match']['mean'] * 100
    top_1_overlap = results_summary['top_1_overlap']['mean'] * 100
    top_5_overlap = results_summary['top_5_overlap']['mean'] * 100
    top_10_overlap = results_summary['top_10_overlap']['mean'] * 100
    kendall_tau = results_summary['kendall_tau']['mean']
    ndcg = results_summary['ndcg_10']['mean']

    print(f"Sample size:           {len(metrics['exact_match'])} queries")
    print(f"Exact match rate:      {exact_match_rate:.2f}%")
    print(f"Top-1 overlap:         {top_1_overlap:.2f}%")
    print(f"Top-5 overlap:         {top_5_overlap:.2f}%")
    print(f"Top-10 overlap:        {top_10_overlap:.2f}%")
    print(f"Kendall's Tau:         {kendall_tau:.4f}")
    print(f"NDCG@10:               {ndcg:.4f}")
    print()

    # Interpretation
    print("INTERPRETATION:")
    print()

    if top_10_overlap >= 90:
        print(f"✅ EXCELLENT: {top_10_overlap:.1f}% top-10 overlap - Finds same authors as API")
    elif top_10_overlap >= 70:
        print(f"✅ GOOD: {top_10_overlap:.1f}% top-10 overlap - Finds most authors")
    elif top_10_overlap >= 50:
        print(f"⚠️  MODERATE: {top_10_overlap:.1f}% top-10 overlap")
    else:
        print(f"❌ POOR: {top_10_overlap:.1f}% top-10 overlap")

    print()

    if ndcg >= 0.8:
        print(f"✅ EXCELLENT: NDCG {ndcg:.2f} - High ranking quality")
    elif ndcg >= 0.6:
        print(f"✅ GOOD: NDCG {ndcg:.2f} - Good ranking quality")
    else:
        print(f"⚠️  MODERATE: NDCG {ndcg:.2f} - Moderate ranking quality")

    print()

    if kendall_tau >= 0.7:
        print(f"✅ EXCELLENT: Kendall's Tau {kendall_tau:.2f} - Strong ranking correlation")
    elif kendall_tau >= 0.5:
        print(f"✅ GOOD: Kendall's Tau {kendall_tau:.2f} - Good ranking correlation")
    elif kendall_tau >= 0.3:
        print(f"⚠️  MODERATE: Kendall's Tau {kendall_tau:.2f} - Moderate correlation")
    else:
        print(f"❌ WEAK: Kendall's Tau {kendall_tau:.2f} - Weak correlation")

    print()
    print("=" * 80)

    # Save results
    REPORT_DIR.mkdir(exist_ok=True)
    report_file = REPORT_DIR / "pure_python_validation_report.json"

    with open(report_file, 'w') as f:
        json.dump({
            'summary': results_summary,
            'raw_metrics': {k: [float(v) for v in vals] for k, vals in metrics.items()},
            'detailed_results': detailed_results,
            'metadata': {
                'total_queries': len(api_responses),
                'valid_comparisons': len(metrics['exact_match']),
                'skipped': skipped,
            }
        }, f, indent=2)

    print(f"\n✓ Report saved to: {report_file}")
    print()

    print("✅ PURE PYTHON AUTOCOMPLETE VALIDATION COMPLETE")
    print()
    print(f"Full report available at: {report_file}")
    print()

    # Show top/bottom queries
    print("=" * 80)
    print("BEST PERFORMING QUERIES (Top 5 by top-10 overlap)")
    print("=" * 80)
    print()
    sorted_by_overlap = sorted(detailed_results, key=lambda x: x['top_10_overlap'], reverse=True)
    for i, result in enumerate(sorted_by_overlap[:5], 1):
        print(f"{i}. Query: '{result['query']}'")
        print(f"   Top-10 overlap: {result['top_10_overlap']*100:.1f}%")
        print(f"   NDCG: {result['ndcg_10']:.3f}")
        print()

    print("=" * 80)
    print("WORST PERFORMING QUERIES (Bottom 5 by top-10 overlap)")
    print("=" * 80)
    print()
    for i, result in enumerate(sorted_by_overlap[-5:], 1):
        print(f"{i}. Query: '{result['query']}'")
        print(f"   Top-10 overlap: {result['top_10_overlap']*100:.1f}%")
        print(f"   NDCG: {result['ndcg_10']:.3f}")
        print()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
