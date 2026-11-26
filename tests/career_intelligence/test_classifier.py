from src.career_intelligence.classifier import classify_job


def test_autonomy_robotics_job():
    result = classify_job(
        "Senior Technical Program Manager - Autonomous Mobility",
        """
        Lead deployment of autonomous vehicle technology across fleet operations.
        Coordinate engineering, suppliers, launch readiness and mobility services.
        """,
    )

    assert result["career_lane"] == "autonomy_robotics"
    assert result["score"] > 0


def test_ai_transformation_job():
    result = classify_job(
        "AI Transformation Program Lead",
        """
        Lead enterprise AI adoption and generative AI transformation programs.
        Coordinate stakeholders, governance and implementation across business units.
        """,
    )

    assert result["career_lane"] == "ai_data_transformation"
    assert result["score"] > 0


def test_strategy_operations_job():
    result = classify_job(
        "Chief of Staff - Technology",
        """
        Support executive operations, strategic initiatives, governance,
        transformation and senior management decision making.
        """,
    )

    assert result["career_lane"] == "strategy_operations"
    assert result["score"] > 0