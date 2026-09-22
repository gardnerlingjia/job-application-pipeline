from pathlib import Path

import yaml


CONFIG_FILES = [
    "config/career_profile.yaml",
    "config/capability_profile.yaml",
    "config/constraints.yaml",
    "config/network_profile.yaml",
]


def load_yaml(path: str) -> dict:
    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(f"Missing configuration file: {path}")

    with file_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level.")

    return data


def validate_strategy(profile: dict) -> None:
    policy = profile["strategy_policy"]
    weights = policy["candidacy_weights"]
    if set(weights) != {
        "career_lane_fit",
        "capability_fit",
        "domain_fit",
        "evidence_strength",
        "location_fit",
        "network_access",
    }:
        raise ValueError("Candidacy weights must define all six dimensions")
    if abs(sum(weights.values()) - 1) > 1e-9 or any(value < 0 for value in weights.values()):
        raise ValueError("Candidacy weights must be nonnegative and sum to one")
    if weights["network_access"] or weights["location_fit"]:
        raise ValueError("Access/location cannot contribute to current candidacy")
    anchors = policy["evidence_anchors"]
    if not 0 <= anchors["unknown"] < anchors["adjacent"] <= 75 < anchors["direct"] <= 100:
        raise ValueError("Invalid direct/adjacent evidence anchors")
    if anchors["adjacent_total_cap"] > 75:
        raise ValueError("Adjacent candidacy must be capped at 75")
    if sum(lane.get("allocation_percent", 0) for lane in profile["career_lanes"].values()) != 100:
        raise ValueError("Search allocation must sum to 100")


def main() -> None:
    for config_file in CONFIG_FILES:
        data = load_yaml(config_file)
        if config_file == "config/career_profile.yaml":
            validate_strategy(data)
        print(f"OK: {config_file}")
        print(f"    top-level keys: {', '.join(data.keys())}")

    print("\nAll career intelligence configuration files loaded successfully.")


if __name__ == "__main__":
    main()
