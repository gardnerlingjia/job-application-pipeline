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


def main() -> None:
    for config_file in CONFIG_FILES:
        data = load_yaml(config_file)
        print(f"OK: {config_file}")
        print(f"    top-level keys: {', '.join(data.keys())}")

    print("\nAll career intelligence configuration files loaded successfully.")


if __name__ == "__main__":
    main()