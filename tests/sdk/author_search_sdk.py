import json
import re
import math
from unicodedata import normalize

def normalize_string(text):
    """Normalize string by converting to lowercase, removing diacritics."""
    if not text:
        return ""
    return normalize('NFKD', text.lower()).encode('ascii', 'ignore').decode('utf-8')

def local_author_search(authors_data, search_term):
    """
    Performs a local search for authors based on a search term.
    Final refined scoring logic.
    """
    normalized_search_term = normalize_string(search_term)
    search_term_tokens = list(normalized_search_term.split())
    search_term_tokens_set = set(search_term_tokens)
    num_search_tokens = len(search_term_tokens_set)

    if not search_term.strip():
        return []

    results = []
    for author in authors_data:
        current_match_score = 0.0

        author_display_name = author.get('display_name', '')
        normalized_display_name = normalize_string(author_display_name)
        display_name_tokens = normalized_display_name.split()
        display_name_tokens_set = set(display_name_tokens)

        is_exact_display_name_match = (normalized_search_term == normalized_display_name)
        all_tokens_present_in_display_name = num_search_tokens > 0 and search_term_tokens_set.issubset(display_name_tokens_set)

        # --- Scoring for display_name ---
        if is_exact_display_name_match:
            current_match_score += 5000.0 # Strongest base score for perfect match
            if author.get('works_count', 0) > 20: # Identify more prominent authors
                current_match_score += 1000.0
        elif all_tokens_present_in_display_name:
            current_match_score += 1500.0
            if normalized_search_term in normalized_display_name: # Phrase match
                current_match_score += 700.0
                if normalized_display_name.startswith(normalized_search_term):
                    current_match_score += 300.0
        elif num_search_tokens > 0: # Partial token overlap
            common_tokens_display_name = search_term_tokens_set.intersection(display_name_tokens_set)
            if common_tokens_display_name:
                 current_match_score += (len(common_tokens_display_name) / num_search_tokens) * 300.0

        # Contiguous sequence bonus (if not already exact full phrase match)
        if not (is_exact_display_name_match and normalized_search_term in normalized_display_name) and num_search_tokens > 0:
            for i in range(len(display_name_tokens) - num_search_tokens + 1):
                if display_name_tokens[i:i+num_search_tokens] == search_term_tokens:
                    current_match_score += 400.0
                    break

        # --- Scoring for display_name_alternatives ---
        alternatives = author.get('display_name_alternatives', [])
        if not isinstance(alternatives, list): alternatives = []

        alt_score = 0.0
        for alt_name_raw in alternatives:
            alt_name = normalize_string(alt_name_raw)
            alt_name_tokens_set = set(alt_name.split())
            current_alt_contribution = 0.0

            if normalized_search_term == alt_name: # Exact alt name match
                current_alt_contribution = max(current_alt_contribution, 700.0)
            elif num_search_tokens > 0 and search_term_tokens_set.issubset(alt_name_tokens_set): # All tokens in alt
                current_alt_contribution = max(current_alt_contribution, 250.0)
                if normalized_search_term in alt_name: # Phrase match in alt
                    current_alt_contribution += 150.0
                    if alt_name.startswith(normalized_search_term):
                         current_alt_contribution += 75.0
            # Specific boost if the multi-word search term is a sub-phrase in an alternative.
            # This is to catch things like "Marie Curie Fellowship" when searching "Marie Curie".
            elif num_search_tokens > 1 and normalized_search_term in alt_name:
                 current_alt_contribution = max(current_alt_contribution, 400.0)
            elif num_search_tokens == 1 and normalized_search_term in alt_name: # Single token search
                 current_alt_contribution = max(current_alt_contribution, 50.0)
            elif num_search_tokens > 0: # Partial token overlap in alt
                common_tokens_alt = search_term_tokens_set.intersection(alt_name_tokens_set)
                if common_tokens_alt:
                    current_alt_contribution = max(current_alt_contribution, (len(common_tokens_alt) / num_search_tokens) * 50.0)
            alt_score = max(alt_score, current_alt_contribution)
        current_match_score += alt_score

        if current_match_score > 0:
            author_result = author.copy()
            works_count_bonus = 0.0
            wc = author.get('works_count', 0)
            if wc > 0:
                works_count_bonus = math.log10(wc + 1) * 20.0 # Slightly higher works_count factor

            author_result['local_relevance_score'] = current_match_score + works_count_bonus
            results.append(author_result)

    results.sort(key=lambda x: (
        x['local_relevance_score'],
        x.get('relevance_score', 0) or 0, # OpenAlex's score as primary tie-breaker
        x.get('works_count', 0)       # Works count as secondary tie-breaker
    ), reverse=True)

    return results

def load_all_author_data(data_path="tests/sdk/data"):
    all_authors = []
    seen_ids = set()
    filenames = [
        "santiago_ramon_y_cajal_results.json", "yoshua_bengio_results.json",
        "marie_curie_results.json", "fei_fei_li_results.json", "noam_chomsky_results.json",
    ]
    for filename in filenames:
        filepath = f"{data_path}/{filename}"
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for res in data.get('results', []):
                    if res.get('id') and res['id'] not in seen_ids:
                        rec = {
                            'id': res['id'], 'display_name': res.get('display_name'),
                            'relevance_score': res.get('relevance_score'),
                            'works_count': res.get('works_count', 0),
                            'display_name_alternatives': res.get('display_name_alternatives', []) or []
                        }
                        all_authors.append(rec)
                        seen_ids.add(res['id'])
        except FileNotFoundError: print(f"Warning: Data file {filepath} not found.")
        except json.JSONDecodeError: print(f"Warning: Could not decode JSON from {filepath}.")
    return all_authors

def compare_ordering(search_term, oa_results, local_results):
    print(f"\n--- Comparison for search term: '{search_term}' ---")
    oa_ids = [r['id'] for r in oa_results]
    local_ids = [r['id'] for r in local_results]
    print(f"OpenAlex returned {len(oa_ids)} ... Local search returned {len(local_ids)} ...")

    print("\nTop 5 OpenAlex results (ID, Name, API_Relevance, Works):")
    for i, r in enumerate(oa_results[:5]): print(f"  {i+1}. {r['id']}, {r['display_name']}, {r.get('relevance_score','N/A')}, {r.get('works_count','N/A')}")

    print("\nTop 5 Local search results (ID, Name, Local_Score, Works, API_Relevance):")
    for i, r in enumerate(local_results[:5]): print(f"  {i+1}. {r['id']}, {r['display_name']}, {r.get('local_relevance_score','N/A')}, {r.get('works_count','N/A')}, {r.get('relevance_score','N/A')}")

    comp_len = min(len(oa_ids), len(local_ids))
    disp_limit = min(comp_len, 10)
    if comp_len == 0:
        print("\nOrdering: No results to compare.")
        return not oa_ids and not local_ids

    match = True
    for i in range(comp_len):
        if oa_ids[i] != local_ids[i]:
            match = False
            if i < disp_limit:
                print(f"\nOrdering mismatch at position {i+1}:")
                print(f"  OpenAlex: ID {oa_ids[i]} ({oa_results[i]['display_name']}), API_Score: {oa_results[i]['relevance_score']}")
                print(f"  Local:    ID {local_ids[i]} ({local_results[i]['display_name']}), Local_Score: {local_results[i]['local_relevance_score']:.2f}, API_Score: {local_results[i]['relevance_score']}")
            elif i == disp_limit: print(f"\nFurther mismatches beyond top {disp_limit} exist...")

    if match and len(oa_ids) != len(local_ids): print(f"\nOrdering: Top {comp_len} match, but counts differ (OA: {len(oa_ids)}, Local: {len(local_ids)}). Acceptable.")
    elif match: print(f"\nOrdering: Top {comp_len} results MATCH perfectly.")
    else: print(f"\nOrdering: Orders DO NOT MATCH within top {comp_len}.")
    return match

if __name__ == '__main__':
    print("Loading author data...")
    all_data = load_all_author_data()
    if not all_data: print("No data loaded. Exiting."); exit()
    print(f"Loaded {len(all_data)} unique author records.")

    queries = {
        "Santiago Ramon y Cajal": "santiago_ramon_y_cajal_results.json",
        "Yoshua Bengio": "yoshua_bengio_results.json",
        "Marie Curie": "marie_curie_results.json",
        "Fei-Fei Li": "fei_fei_li_results.json",
        "Noam Chomsky": "noam_chomsky_results.json",
    }
    tally = {}
    for term, fname in queries.items():
        print(f"\n\n================ Processing: '{term}' ================")
        oa_term_results = []
        fpath = f"tests/sdk/data/{fname}"
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                oa_term_results = json.load(f).get('results', [])
        except FileNotFoundError: print(f"Err: File {fpath} missing. Skip."); tally[term] = False; continue
        except json.JSONDecodeError: print(f"Err: JSON decode {fpath}. Skip."); tally[term] = False; continue

        local_res = local_author_search(all_data, term)
        tally[term] = compare_ordering(term, oa_term_results, local_res)

    print("\n\n\n--- Overall Summary ---")
    all_ok = True
    for term, matched in tally.items():
        print(f"Search '{term}': Order {'MATCHED' if matched else 'DID NOT MATCH'}")
        if not matched: all_ok = False

    if all_ok: print("\nAll terms matched OpenAlex ordering for comparable top results!")
    else: print("\nSome terms did not match. Further refinement might be needed.")
