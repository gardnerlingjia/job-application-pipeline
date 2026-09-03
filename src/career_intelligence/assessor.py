from typing import Dict

from src.career_intelligence.classifier import classify_job
from src.career_intelligence.constraints import evaluate_constraints
from src.career_intelligence.scoring import calculate_opportunity_score
from src.career_intelligence.recommender import recommend_action
from src.career_intelligence.capability_matcher import match_capabilities
from src.career_intelligence.domain_matcher import match_domain
from src.career_intelligence.location_matcher import match_location
from src.career_intelligence.evidence_strength import calculate_evidence_strength
from src.career_intelligence.network_matcher import match_network


def assess_opportunity(
    company_name: str,
    title: str,
    description: str,
) -> Dict:
    classification = classify_job(title, description)
    constraints = evaluate_constraints(title, description)
    capability_match = match_capabilities(title, description)
    evidence = calculate_evidence_strength(
    capability_match["matched_capabilities"]
)
    network_match = match_network(company_name)

    domain_match = match_domain(
        title,
        description,
        classification["career_lane"],
    )

    location_match = match_location(
        title,
        description,
    )

    scores = {
    "career_lane_fit": min(classification["score"] * 5, 100),
    "capability_fit": capability_match["capability_fit"],
    "domain_fit": domain_match["domain_fit"],
    "location_fit": location_match["location_fit"],
    "network_access": network_match["network_access"],
    "evidence_strength": evidence["evidence_strength"],
    }

    opportunity_score = calculate_opportunity_score(scores)

    recommendation = recommend_action(
        opportunity_score=opportunity_score,
        constraint_action=constraints["overall_action"],
        network_access=scores["network_access"],
        high_risks=constraints["high_risks"],
        reviews=constraints["reviews"],
    )

    return {
        "title": title,
        "career_lane": classification["career_lane"],
        "career_lane_label": classification["career_lane_label"],
        "domain_matches": domain_match["domain_matches"],
        "location_matches": location_match["location_matches"],
        "lane_score": classification["score"],
        "lane_confidence": classification["confidence"],
        "runner_up_lane": classification["runner_up_lane"],
        "runner_up_score": classification["runner_up_score"],
        "constraint_action": constraints["overall_action"],
        "boosters": constraints["boosters"],
        "company_name": company_name,
        "network_access": network_match["network_access"],
        "relationship_level": network_match["relationship_level"],
        "strategic_relevance": network_match["strategic_relevance"],
        "known_company": network_match["known_company"],
        "high_risks": constraints["high_risks"],
        "hard_skips": constraints["hard_skips"],
        "reviews": constraints["reviews"],
        "scores": scores,
        "matched_capabilities": capability_match["matched_capabilities"],
        "opportunity_score": opportunity_score,
        "evidence_details": evidence["evidence_details"],
        "recommendation": recommendation,
    }


def print_assessment(result: Dict) -> None:
    print("=" * 60)
    print("OPPORTUNITY ASSESSMENT")
    print("=" * 60)

    print(f"\nRole: {result['title']}")

    print("\nCareer lane")
    print(f"  {result['career_lane_label']}")
    print(f"  Score: {result['lane_score']}")
    print(f"  Confidence: {result['lane_confidence']}")

    print(f"\nCompany: {result['company_name']}")
    print("\nNetwork")
    print(f"  Access score: {result['network_access']}")
    print(f"  Relationship: {result['relationship_level']}")
    print(f"  Strategic relevance: {result['strategic_relevance']}")

    print("\nRunner-up")
    print(
        f"  {result['runner_up_lane']} "
        f"(score {result['runner_up_score']})"
    )

    print("\nConstraint evaluation")
    print(f"  Overall action: {result['constraint_action']}")

    print("\nOpportunity")
    print(f"  Score: {result['opportunity_score']} / 100")
    print(f"  Recommendation: {result['recommendation']}")

    print("\nScore breakdown")
    for name, value in result["scores"].items():
        print(f"  {name}: {value}")

    if result["boosters"]:
        print("\nPositive signals")
        for item in result["boosters"]:
            print(f"  + {item['constraint']}: {item['reason']}")

    if result["reviews"]:
        print("\nReview points")
        for item in result["reviews"]:
            print(f"  ? {item['constraint']}: {item['reason']}")

    if result["high_risks"]:
        print("\nHigh risks")
        for item in result["high_risks"]:
            print(f"  ! {item['constraint']}: {item['reason']}")

    if result["hard_skips"]:
        print("\nHard-stop reasons")
        for item in result["hard_skips"]:
            print(f"  X {item['constraint']}: {item['reason']}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    sample_title = "Senior Cloud Architect - Autonomous Mobility"

    sample_description = """
    Lead AWS architecture for an autonomous driving platform.

    We are looking for extensive hands-on cloud architecture experience.
    The team develops autonomous mobility services and fleet technology.

    Location: Berlin.
    """

    result = assess_opportunity(
        "MOIA",
        sample_title,
        sample_description,
    )

    print_assessment(result)