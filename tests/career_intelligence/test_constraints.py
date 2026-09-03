from src.career_intelligence.constraints import evaluate_constraints


def test_cloud_architecture_is_high_risk():
    result = evaluate_constraints(
        "Senior Cloud Architect - Autonomous Mobility",
        """
        Lead AWS architecture for an autonomous driving platform.
        Strong hands-on cloud architecture experience required.
        Location Berlin.
        """,
    )

    assert result["overall_action"] == "HIGH_RISK"

    names = [
        item["constraint"]
        for item in result["detected_constraints"]
    ]

    assert "deep_cloud_architecture" in names
    assert "autonomous_mobility" in names


def test_quota_sales_is_skip():
    result = evaluate_constraints(
        "Enterprise Account Executive",
        """
        Own enterprise sales targets and carry a quarterly sales quota.
        """,
    )

    assert result["overall_action"] == "SKIP"


def test_ai_transformation_has_positive_boost():
    result = evaluate_constraints(
        "AI Transformation Program Lead",
        """
        Lead AI transformation and AI adoption across international teams.
        """,
    )

    names = [
        item["constraint"]
        for item in result["boosters"]
    ]

    assert "ai_transformation" in names


def test_china_germany_interface_is_positive():
    result = evaluate_constraints(
        "Global Program Manager",
        """
        Coordinate a Germany-China technology program across Europe and Asia.
        Fluent Chinese is required.
        """,
    )

    names = [
        item["constraint"]
        for item in result["boosters"]
    ]

    assert "germany_china_interface" in names
    assert "chinese_language_required" in names