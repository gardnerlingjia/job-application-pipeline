from typing import Dict, List


CATEGORY_WEIGHTS = {
    "core": 1.0,
    "domain": 1.0,
    "differentiator": 0.9,
    "transferable": 0.8,
    "emerging": 0.6,
    "adjacent": 0.4,
    "gap": 0.1,
}


def calculate_evidence_strength(
    matched_capabilities: List[Dict],
) -> Dict:
    if not matched_capabilities:
        return {
            "evidence_strength": 0.0,
            "evidence_details": [],
        }

    details = []
    weighted_values = []

    for item in matched_capabilities:
        category = item["category"]
        strength = item["strength"]

        category_weight = CATEGORY_WEIGHTS.get(category, 0.5)

        normalized_strength = strength / 5
        weighted_strength = normalized_strength * category_weight

        weighted_values.append(weighted_strength)

        details.append(
            {
                "capability": item["capability"],
                "strength": strength,
                "category": category,
                "category_weight": category_weight,
                "weighted_strength": round(
                    weighted_strength * 100,
                    1,
                ),
            }
        )

    average_strength = sum(weighted_values) / len(weighted_values)

    evidence_strength = round(
        min(average_strength * 100, 100),
        1,
    )

    return {
        "evidence_strength": evidence_strength,
        "evidence_details": details,
    }


if __name__ == "__main__":
    sample = [
        {
            "capability": "technical_program_leadership",
            "strength": 5,
            "category": "core",
        },
        {
            "capability": "ai_data_transformation",
            "strength": 3,
            "category": "emerging",
        },
    ]

    result = calculate_evidence_strength(sample)

    print("Evidence strength:", result["evidence_strength"])
    print("Details:", result["evidence_details"])