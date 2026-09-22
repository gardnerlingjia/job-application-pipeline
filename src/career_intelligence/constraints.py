from pathlib import Path
from typing import Dict, List

import yaml


CONFIG_PATH = Path("config/constraints.yaml")


def load_constraints() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def normalize_text(title: str, description: str) -> str:
    return f"{title} {description}".lower()


def detect_constraints(title: str, description: str) -> List[Dict]:
    config = load_constraints()
    text = normalize_text(title, description)

    detected = []

    keyword_map = {
        "relocation_required": [
            "relocation required",
            "must relocate",
            "relocate to",
        ],
        "china_based_role": [
            "based in china",
            "location: china",
            "shanghai",
            "beijing",
            "hefei",
            "shenzhen",
        ],
        "munich_only": [
            "munich onsite",
            "münchen onsite",
            "based in munich",
            "based in münchen",
        ],
        "deep_cloud_architecture": [
            "cloud architect",
            "aws architecture",
            "azure architecture",
            "gcp architecture",
            "solution architect cloud",
        ],
        "senior_software_engineering": [
            "senior software engineer",
            "staff software engineer",
            "principal software engineer",
        ],
        "production_ml_engineering": [
            "production ml engineer",
            "machine learning engineer",
            "ml engineer",
        ],
        "deep_data_engineering": [
            "senior data engineer",
            "staff data engineer",
            "data platform engineer",
        ],
        "spark_kafka_platform_engineering": [
            "apache spark",
            "kafka",
            "distributed data platform",
        ],
        "quota_carrying_sales": [
            "quota carrying",
            "sales quota",
            "quota responsibility",
        ],
        "enterprise_sales": [
            "enterprise sales",
            "account executive",
            "enterprise account executive",
        ],
        "revenue_target_ownership": [
            "revenue target",
            "sales target",
            "own revenue",
        ],
        "commercial_business_development": [
            "commercial ownership",
            "business development",
            "commercial relationships",
            "commercial negotiations",
            "negotiate business agreements",
            "commercial strategy",
        ],
        "several_years_formal_product_owner_required": [
            "years as product owner",
            "years of product owner experience",
            "formal product owner experience",
        ],
        "robotics_research_engineer": [
            "robotics research engineer",
            "research scientist robotics",
        ],
        "perception_engineer": [
            "perception engineer",
            "computer vision engineer",
        ],
        "senior_ml_engineer": [
            "senior machine learning engineer",
            "senior ml engineer",
        ],
        "ml_research_scientist": [
            "machine learning research scientist",
            "ai research scientist",
            "research scientist",
        ],
        "junior_role": [
            "junior ",
            "entry level",
            "graduate program",
        ],
        "berlin_or_remote_germany": [
            "berlin",
            "remote germany",
            "remote in germany",
        ],
        "autonomous_mobility": [
            "autonomous mobility",
            "autonomous vehicle",
            "autonomous driving",
        ],
        "adas_automated_driving": [
            "adas",
            "automated driving",
            "automated parking",
        ],
        "robotics_program_management": [
            "robotics program manager",
            "robotics program",
        ],
        "robotics_deployment_operations": [
            "robotics deployment",
            "robot operations",
            "field operations",
        ],
        "physical_ai_program_role": [
            "physical ai",
            "embodied ai",
        ],
        "ai_program_management": [
            "ai program manager",
            "ai program lead",
        ],
        "ai_transformation": [
            "ai transformation",
            "ai adoption",
            "ai enablement",
        ],
        "ai_product_operations": [
            "ai product operations",
            "ai operations",
        ],
        "chief_of_staff_technical": [
            "chief of staff",
        ],
        "executive_operations": [
            "executive operations",
            "executive program manager",
        ],
        "transformation_program": [
            "transformation program",
            "transformation lead",
        ],
        "germany_china_interface": [
            "germany china",
            "germany-china",
            "china germany",
            "china-germany",
        ],
        "europe_china_program": [
            "europe china",
            "europe-china",
            "china europe",
            "china-europe",
        ],
        "chinese_language_required": [
            "chinese required",
            "mandarin required",
            "fluent chinese",
            "fluent mandarin",
        ],
        "international_program": [
            "international program",
            "global program",
            "global operations",
        ],
        "mobility": [
            "mobility",
        ],
        "robotics": [
            "robotics",
        ],
        "enterprise_technology": [
            "enterprise technology",
            "software platform",
            "technology platform",
        ],
        "logistics_technology": [
            "logistics technology",
            "warehouse automation",
        ],
        "industrial_automation": [
            "industrial automation",
        ],
    }

    for section_name, section in config["constraints"].items():
        for constraint_name, rule in section.items():
            keywords = keyword_map.get(constraint_name, [])

            title_only = constraint_name in {
                "senior_software_engineering", "production_ml_engineering",
                "deep_data_engineering", "robotics_research_engineer", "perception_engineer",
                "senior_ml_engineer", "ml_research_scientist",
            }
            haystack = title.lower() if title_only else text
            matched_keywords = [keyword for keyword in keywords if keyword in haystack]

            if matched_keywords:
                detected.append(
                    {
                        "constraint": constraint_name,
                        "section": section_name,
                        "severity": rule["severity"],
                        "action": rule["default_action"],
                        "reason": rule["reason"],
                        "matches": matched_keywords,
                    }
                )

    return detected


def evaluate_constraints(title: str, description: str) -> Dict:
    detected = detect_constraints(title, description)
    from src.career_intelligence.location_matcher import match_location

    location = match_location(title, description)
    if location.get("travel_status", "").startswith("frequent"):
        detected.append({"constraint": "frequent_travel_required", "section": "location",
                         "severity": "high", "action": "SKIP",
                         "reason": "Explicit frequent travel conflicts with occasional domestic travel.",
                         "matches": location["travel_evidence"]})
    if not location.get("hard_conflict"):
        detected = [item for item in detected if item["constraint"] not in {
            "relocation_required", "china_based_role", "munich_only"
        }]

    hard_skips = [
        item for item in detected if item["action"] == "SKIP"
    ]
    high_risks = [
        item for item in detected if item["action"] == "HIGH_RISK"
    ]
    reviews = [
        item for item in detected if item["action"] == "REVIEW"
    ]
    boosters = [
        item for item in detected if item["action"] == "BOOST"
    ]

    if hard_skips:
        overall_action = "SKIP"
    elif high_risks:
        overall_action = "HIGH_RISK"
    elif reviews:
        overall_action = "REVIEW"
    else:
        overall_action = "CLEAR"

    return {
        "overall_action": overall_action,
        "detected_constraints": detected,
        "hard_skips": hard_skips,
        "high_risks": high_risks,
        "reviews": reviews,
        "boosters": boosters,
    }


if __name__ == "__main__":
    sample_title = "Senior Cloud Architect - Autonomous Mobility"
    sample_description = """
    Lead AWS architecture for an autonomous driving platform.
    Strong hands-on cloud architecture experience required.
    Location Berlin.
    """

    result = evaluate_constraints(sample_title, sample_description)

    print("Overall action:", result["overall_action"])

    for item in result["detected_constraints"]:
        print(
            f"- {item['constraint']} | "
            f"{item['severity']} | "
            f"{item['action']}"
        )