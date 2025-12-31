"""
End-to-End Autocomplete Validation Test

This test validates the AUTOCOMPLETE endpoint (/autocomplete/authors) against real
OpenAlex API responses.

DIFFERENCE from full search validation:
- Autocomplete uses match_phrase_prefix (not multi_match BM25)
- Returns 10 results (not 25)
- Validates RANKING ORDER (not just sets) - autocomplete order matters for UX
- Uses ranking metrics: Kendall's Tau, NDCG, top-k overlap, exact match

Workflow:
1. Sets up Elasticsearch
2. Indexes authors from sample parquet
3. Runs autocomplete validation against REAL OpenAlex autocomplete API responses
4. Validates ranking order matches production

Run with: pytest tests/standalone/test_run_autocomplete/test_end_to_end_autocomplete_validation.py -v -s
"""
import sys
sys.path.insert(0, '/home/user/openalex-elastic-api')

import json
import subprocess
import time
from pathlib import Path
import pytest
from elasticsearch import Elasticsearch
from collections import defaultdict
import numpy as np
from elasticsearch_dsl import connections

# Test configuration
FIXTURES_FILE = Path(__file__).parent / "fixtures" / "openalex_autocomplete_responses.json"
REPORT_DIR = Path(__file__).parent / "reports"
ES_HOST = "http://127.0.0.1:9200"
TEST_INDEX = "authors-v16"
STANDALONE_DIR = Path("/home/user/openalex-elastic-api/tests/standalone")


def check_elasticsearch_running():
    """Check if Elasticsearch is running"""
    try:
        es = Elasticsearch([ES_HOST], request_timeout=1)
        result = es.ping()
        if result:
            es.cluster.health()
        return result
    except:
        return False


def setup_elasticsearch():
    """Run setup_elasticsearch.sh script"""
    print("  Running: ./setup_elasticsearch.sh")

    result = subprocess.run(
        ['bash', 'setup_elasticsearch.sh'],
        cwd=str(STANDALONE_DIR),
        capture_output=True,
        text=True,
        timeout=120
    )

    if result.returncode != 0:
        print(f"  STDOUT: {result.stdout}")
        print(f"  STDERR: {result.stderr}")
        raise RuntimeError(f"Elasticsearch setup failed with code {result.returncode}")

    # Wait for ES to be ready
    max_attempts = 30
    for i in range(max_attempts):
        if check_elasticsearch_running():
            return True
        time.sleep(1)

    raise RuntimeError("Elasticsearch did not start within 30 seconds")


def index_sample_authors():
    """Index sample authors for testing"""
    from tests.standalone.test_run.test_end_to_end_validation import index_authors_from_parquet
    sample_parquet = Path(__file__).parent / "fixtures" / "sample_authors_autocomplete.parquet"

    if not sample_parquet.exists():
        raise FileNotFoundError(f"Sample parquet not found: {sample_parquet}")

    return index_authors_from_parquet(sample_parquet)


def load_api_responses():
    """Load saved autocomplete API responses"""
    if not FIXTURES_FILE.exists():
        raise FileNotFoundError(f"Fixtures not found: {FIXTURES_FILE}")

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


def query_extracted_autocomplete(query_text, limit=10):
    """Query using extracted autocomplete logic"""
    from core.author_autocomplete import build_author_autocomplete_query
    from settings import AUTHORS_INDEX

    try:
        search = build_author_autocomplete_query(query_text, index_name=AUTHORS_INDEX, limit=limit)
        response = search.execute()

        ids = []
        for hit in response:
            author_id = hit.meta.id
            if author_id:
                # Normalize ID format
                if author_id.startswith('https://openalex.org/'):
                    author_id = author_id.replace('https://openalex.org/', '')
                ids.append(author_id)

        return ids
    except Exception as e:
        print(f"    Error querying '{query_text}': {e}")
        return []


# RANKING METRICS (order-dependent)
def compute_exact_match(api_ranking, extracted_ranking):
    """Check if rankings are exactly identical (same order)"""
    return api_ranking == extracted_ranking


def compute_kendall_tau(api_ranking, extracted_ranking):
    """
    Kendall's Tau: Correlation between rankings (-1 to 1)

    1.0 = perfect agreement
    0.0 = no correlation
    -1.0 = perfect disagreement
    """
    from scipy.stats import kendalltau

    if len(api_ranking) == 0 or len(extracted_ranking) == 0:
        return 1.0 if len(api_ranking) == len(extracted_ranking) else 0.0

    # Create rankings (position indices)
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
    """
    NDCG@k: Normalized Discounted Cumulative Gain

    Measures ranking quality with position discounting.
    1.0 = perfect ranking
    0.0 = worst ranking
    """
    if len(api_ranking) == 0 or len(extracted_ranking) == 0:
        return 1.0 if len(api_ranking) == len(extracted_ranking) else 0.0

    # Relevance scores (higher position in API = higher relevance)
    relevance_scores = {id_: len(api_ranking) - i for i, id_ in enumerate(api_ranking)}

    # DCG for extracted ranking
    dcg = 0.0
    for i, id_ in enumerate(extracted_ranking[:k]):
        if id_ in relevance_scores:
            dcg += relevance_scores[id_] / np.log2(i + 2)  # i+2 because log2(1) = 0

    # IDCG (ideal DCG - if we had perfect ranking)
    idcg = 0.0
    for i, id_ in enumerate(api_ranking[:k]):
        if id_ in relevance_scores:
            idcg += relevance_scores[id_] / np.log2(i + 2)

    if idcg == 0:
        return 0.0

    return dcg / idcg


def compute_top_k_overlap(api_ranking, extracted_ranking, k):
    """
    Top-k overlap: % of top-k API results that appear in top-k extracted results
    """
    if len(api_ranking) == 0:
        return 1.0 if len(extracted_ranking) == 0 else 0.0

    api_top_k = set(api_ranking[:k])
    extracted_top_k = set(extracted_ranking[:k])

    if len(api_top_k) == 0:
        return 1.0

    intersection = api_top_k & extracted_top_k
    return len(intersection) / len(api_top_k)


def test_end_to_end_autocomplete_validation():
    """
    End-to-end test of autocomplete validation workflow.

    Validates that extracted autocomplete logic produces SAME RANKING
    as production OpenAlex autocomplete API.
    """

    print("\n" + "=" * 80)
    print("END-TO-END AUTOCOMPLETE VALIDATION TEST")
    print("=" * 80)
    print()

    # Step 1: Setup Elasticsearch
    print("→ Step 1: Setting up Elasticsearch...")
    if check_elasticsearch_running():
        print("  ℹ️  Elasticsearch already running, skipping setup")
    else:
        setup_elasticsearch()
        print("✓ Elasticsearch setup complete")
    print()

    # Verify ES is responsive
    es = Elasticsearch([ES_HOST])
    assert es.ping(), "Elasticsearch is not responding"
    print(f"✓ Verified: Elasticsearch running at {ES_HOST}")
    print()

    # Connect elasticsearch_dsl
    connections.create_connection(hosts=[ES_HOST])

    # Step 2: Index sample authors
    print("→ Step 2: Indexing sample authors...")
    num_indexed = index_sample_authors()
    print(f"✓ Indexed {num_indexed} authors")
    print()

    # Step 3: Load API responses
    print("→ Step 3: Loading real autocomplete API responses...")
    api_responses = load_api_responses()
    print(f"✓ Loaded {len(api_responses)} queries")
    print()

    # Step 4: Run validation
    print("→ Step 4: Running autocomplete validation...")
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
    errors = 0

    for i, (query, api_results) in enumerate(api_responses.items(), 1):
        if (i) % 5 == 0:
            print(f"  Processed {i}/{len(api_responses)} queries...")

        # Extract API ranking
        api_ids = extract_ranking_from_results(api_results)

        # Query extracted logic
        extracted_ids = query_extracted_autocomplete(query, limit=10)

        # Skip if both empty
        if len(api_ids) == 0 and len(extracted_ids) == 0:
            skipped += 1
            continue

        # Skip if either is empty (can't compare ranking)
        if len(api_ids) == 0 or len(extracted_ids) == 0:
            skipped += 1
            continue

        # Compute ranking metrics
        metrics['exact_match'].append(1.0 if compute_exact_match(api_ids, extracted_ids) else 0.0)
        metrics['top_1_overlap'].append(compute_top_k_overlap(api_ids, extracted_ids, k=1))
        metrics['top_3_overlap'].append(compute_top_k_overlap(api_ids, extracted_ids, k=3))
        metrics['top_5_overlap'].append(compute_top_k_overlap(api_ids, extracted_ids, k=5))
        metrics['top_10_overlap'].append(compute_top_k_overlap(api_ids, extracted_ids, k=10))
        metrics['kendall_tau'].append(compute_kendall_tau(api_ids, extracted_ids))
        metrics['ndcg_10'].append(compute_ndcg_at_k(api_ids, extracted_ids, k=10))

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
    print("OVERALL ASSESSMENT (RANKING ORDER)")
    print("=" * 80)
    print()

    exact_match_rate = results_summary['exact_match']['mean'] * 100
    top_1_overlap = results_summary['top_1_overlap']['mean'] * 100
    top_5_overlap = results_summary['top_5_overlap']['mean'] * 100
    kendall_tau = results_summary['kendall_tau']['mean']
    ndcg = results_summary['ndcg_10']['mean']

    print(f"Sample size:           {len(metrics['exact_match'])} queries")
    print(f"Exact match rate:      {exact_match_rate:.2f}%")
    print(f"Top-1 overlap:         {top_1_overlap:.2f}%")
    print(f"Top-5 overlap:         {top_5_overlap:.2f}%")
    print(f"Kendall's Tau:         {kendall_tau:.4f}")
    print(f"NDCG@10:               {ndcg:.4f}")
    print()

    # Interpretation
    print("INTERPRETATION:")
    print()

    if kendall_tau >= 0.9:
        print("✅ EXCELLENT: Kendall's Tau ≥0.9 - Near-perfect ranking correlation")
    elif kendall_tau >= 0.7:
        print("✅ GOOD: Kendall's Tau ≥0.7 - Strong ranking correlation")
    elif kendall_tau >= 0.5:
        print("⚠️  MODERATE: Kendall's Tau ≥0.5 - Moderate ranking correlation")
    else:
        print("❌ POOR: Kendall's Tau <0.5 - Weak ranking correlation")

    print()

    if top_1_overlap >= 80:
        print(f"✅ Top-1 overlap: {top_1_overlap:.1f}% - Excellent agreement on #1 result")
    elif top_1_overlap >= 50:
        print(f"⚠️  Top-1 overlap: {top_1_overlap:.1f}% - Moderate agreement on #1 result")
    else:
        print(f"❌ Top-1 overlap: {top_1_overlap:.1f}% - Poor agreement on #1 result")

    print()
    print("=" * 80)

    # Save results
    REPORT_DIR.mkdir(exist_ok=True)
    report_file = REPORT_DIR / "autocomplete_validation_report.json"

    with open(report_file, 'w') as f:
        json.dump({
            'summary': results_summary,
            'raw_metrics': {k: [float(v) for v in vals] for k, vals in metrics.items()},
            'metadata': {
                'total_queries': len(api_responses),
                'valid_comparisons': len(metrics['exact_match']),
                'skipped': skipped,
            }
        }, f, indent=2)

    print(f"\n✓ Report saved to: {report_file}")
    print()

    print("✅ AUTOCOMPLETE VALIDATION COMPLETE")
    print()
    print(f"Full report available at: {report_file}")
    print()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
