import json
from collections import Counter, defaultdict

def summarize_review_results(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        review_data = json.load(f)

    # Count ACCEPT/REJECT
    status_counts = Counter(entry["status"] for entry in review_data.values())

    # Track unique agency_yr labels
    agency_by_status = defaultdict(set)
    for entry in review_data.values():
        status = entry["status"]
        agency_yr = entry.get("label", f"Index_{entry}")
        agency_by_status[status].add(agency_yr)

    # Print Summary
    print("====== Manual Review Summary ======\n")
    print(f"Total reviewed entries: {len(review_data)}")
    for status in ["ACCEPT", "REJECT"]:
        count = status_counts.get(status, 0)
        agencies = sorted(agency_by_status.get(status, []))
        print(f"\n{status} ({count}):")
        print("  Unique agency-years:", len(agencies))
        for agency in agencies:
            print("   •", agency)

    print("\n===================================")

# Example usage:
if __name__ == "__main__":
    review_file = "table_detected_review.json"  # or goal_match_review.json, etc.
    summarize_review_results(review_file)
