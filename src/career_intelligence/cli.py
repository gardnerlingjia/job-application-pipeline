import argparse
from pathlib import Path

from src.career_intelligence.assessor import (
    assess_opportunity,
    print_assessment,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Assess a job opportunity against the career intelligence profile."
    )

    parser.add_argument(
        "--company",
        required=True,
        help="Company name",
    )

    parser.add_argument(
        "--title",
        required=True,
        help="Job title",
    )

    parser.add_argument(
        "--file",
        required=True,
        help="Path to a text file containing the job description",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    job_file = Path(args.file)

    if not job_file.exists():
        raise FileNotFoundError(
            f"Job description file not found: {job_file}"
        )

    description = job_file.read_text(encoding="utf-8")

    result = assess_opportunity(
        args.company,
        args.title,
        description,
    )

    print_assessment(result)


if __name__ == "__main__":
    main()