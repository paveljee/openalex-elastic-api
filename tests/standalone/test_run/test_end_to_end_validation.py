"""
End-to-End Reproducible Statistical Validation Test

This test demonstrates the COMPLETE workflow from README:
1. Sets up Elasticsearch (using setup_elasticsearch.sh)
2. Indexes authors from sample parquet (using build_author_index_from_parquet.py)
3. Uses real OpenAlex API response fixtures (saved in repo)
4. Runs statistical validation
5. Saves metrics report

Run with: pytest tests/standalone/test_run/test_end_to_end_validation.py -v -s
"""
import sys
sys.path.insert(0, '/home/user/openalex-elastic-api')

import json
import subprocess
import time
import os
from pathlib import Path
import pytest
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ConnectionError

# Test configuration
FIXTURES_DIR = Path(__file__).parent / "fixtures"
REPORT_DIR = Path(__file__).parent / "reports"
SAMPLE_PARQUET = FIXTURES_DIR / "sample_authors_details.parquet"
ES_HOST = "http://127.0.0.1:9200"
TEST_INDEX = "authors-v16"
STANDALONE_DIR = Path("/home/user/openalex-elastic-api/tests/standalone")


def check_elasticsearch_running():
    """Check if Elasticsearch is running"""
    try:
        es = Elasticsearch([ES_HOST], request_timeout=1)
        result = es.ping()
        # Double-check with cluster health
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


def index_authors_from_parquet(parquet_file):
    """Index authors from parquet using build_author_index_from_parquet.py"""
    print(f"  Running: python scripts/build_author_index_from_parquet.py --parquet-file {parquet_file}")

    result = subprocess.run(
        [
            sys.executable,
            'scripts/build_author_index_from_parquet.py',
            '--parquet-file', str(parquet_file)
        ],
        cwd='/home/user/openalex-elastic-api',
        capture_output=True,
        text=True,
        timeout=60
    )

    if result.returncode != 0:
        print(f"  STDOUT: {result.stdout}")
        print(f"  STDERR: {result.stderr}")
        raise RuntimeError(f"Indexing failed with code {result.returncode}")

    print(result.stdout)

    # Extract number of indexed authors from output
    import re
    match = re.search(r'Indexed (\d+) authors', result.stdout)
    if match:
        return int(match.group(1))
    return 0


def run_statistical_validation(fixtures_dir):
    """Run the statistical validation script using subprocess"""

    # Import and run the test
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "test_statistical_validation",
        "/home/user/openalex-elastic-api/tests/standalone/test_statistical_validation.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Run the validation function
    result = module.test_statistical_validation_real_responses(
        responses_dir=str(fixtures_dir)
    )

    return result


def load_validation_results():
    """Load the validation results JSON"""
    results_file = Path("/home/user/openalex-elastic-api/tests/standalone/statistical_validation_results.json")

    if not results_file.exists():
        return None

    with open(results_file, 'r') as f:
        return json.load(f)


def test_end_to_end_statistical_validation():
    """
    End-to-end test of statistical validation workflow (ALL STEPS from README).

    This test executes the complete workflow:
    1. Sets up Elasticsearch using setup_elasticsearch.sh
    2. Indexes authors from sample parquet using build_author_index_from_parquet.py
    3. Runs statistical validation against real API fixtures
    4. Saves and validates metrics report
    """

    print("\n" + "=" * 80)
    print("END-TO-END STATISTICAL VALIDATION TEST (ALL README STEPS)")
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

    # Step 2: Index authors from parquet
    print("→ Step 2: Indexing authors from sample parquet...")
    assert SAMPLE_PARQUET.exists(), f"Sample parquet not found: {SAMPLE_PARQUET}"
    num_indexed = index_authors_from_parquet(SAMPLE_PARQUET)
    print(f"✓ Indexed {num_indexed} authors from {SAMPLE_PARQUET.name}")
    print()

    # Step 3: Verify fixtures exist
    print("→ Step 3: Checking API response fixtures...")
    assert FIXTURES_DIR.exists(), f"Fixtures directory not found: {FIXTURES_DIR}"
    fixtures = list(FIXTURES_DIR.glob("*.json"))
    assert len(fixtures) > 0, "No fixture files found"
    print(f"✓ Found {len(fixtures)} fixture file(s):")
    for fixture in fixtures:
        print(f"  - {fixture.name}")
    print()

    # Step 4: Run statistical validation
    print("→ Step 4: Running statistical validation...")
    print()

    try:
        result = run_statistical_validation(FIXTURES_DIR)
        assert result is True, "Statistical validation failed"
    except Exception as e:
        print(f"\n❌ Validation encountered error: {e}")
        raise

    print()
    print("✓ Statistical validation completed")
    print()

    # Step 5: Load and validate results
    print("→ Step 5: Loading validation results...")
    results = load_validation_results()
    assert results is not None, "Results file not found"
    print(f"✓ Results loaded from statistical_validation_results.json")
    print()

    # Step 6: Save report to test_run/reports/
    print("→ Step 6: Saving report to test_run/reports/...")
    REPORT_DIR.mkdir(exist_ok=True)

    report_file = REPORT_DIR / "end_to_end_validation_report.json"
    with open(report_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"✓ Report saved to: {report_file}")
    print()

    # Step 7: Display key metrics
    print("=" * 80)
    print("KEY METRICS SUMMARY")
    print("=" * 80)
    print()

    metadata = results.get('metadata', {})
    summary = results.get('summary', {})

    print(f"Total queries tested:    {metadata.get('total_queries', 0)}")
    print(f"Valid comparisons:       {metadata.get('valid_comparisons', 0)}")
    print()

    if 'exact_match' in summary:
        em_mean = summary['exact_match']['mean']
        print(f"Exact match rate:        {em_mean * 100:.2f}%")

    if 'kendall_tau' in summary:
        kt_mean = summary['kendall_tau']['mean']
        print(f"Kendall's Tau:           {kt_mean:.4f}")

    if 'top_10_overlap' in summary:
        t10_mean = summary['top_10_overlap']['mean']
        print(f"Top-10 overlap:          {t10_mean * 100:.2f}%")

    if 'ndcg_10' in summary:
        ndcg_mean = summary['ndcg_10']['mean']
        print(f"NDCG@10:                 {ndcg_mean:.4f}")

    print()

    # Empty consistency
    if 'empty_consistency' in results:
        ec = results['empty_consistency']
        if ec.get('total_api_empty', 0) > 0:
            print("Empty Query Consistency:")
            print(f"  API empty queries:     {ec['total_api_empty']}")
            print(f"  Both empty:            {ec['both_empty']}")
            print(f"  API empty, local has:  {ec['api_only_empty']}")
            print(f"  Local empty, API has:  {ec['local_only_empty']}")
            print()

    # Temporal consistency
    if 'temporal_consistency' in results:
        tc = results['temporal_consistency']
        if tc.get('queries_with_duplicates', 0) > 0:
            print("Temporal Consistency:")
            print(f"  Duplicate queries:     {tc['queries_with_duplicates']}")
            print(f"  Perfectly consistent:  {tc['perfectly_consistent']}")
            print()

    print("=" * 80)
    print()

    print("✅ END-TO-END TEST PASSED")
    print()
    print(f"Full report available at: {report_file}")
    print()


if __name__ == '__main__':
    # Run the test
    pytest.main([__file__, '-v', '-s'])
