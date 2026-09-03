from src.career_intelligence.assessor import assess_opportunity


def test_dx_one_product_owner():
    result = assess_opportunity(
        "dx.one",
        "Product Owner - Vehicle & Customer Analytics",
        """
        Own data-driven vehicle and customer analytics use cases.

        Work with cloud-based platforms, data services and external
        development teams. Define product requirements and priorities.

        Several years of Product Owner experience in data-related
        use cases and strong cloud technology fundamentals are expected.

        Location: Berlin or Wolfsburg.
        """,
    )

    print("\nDX.ONE")
    print(result)

    assert result["recommendation"] in {
        "EXPLORE",
        "WATCH",
        "SKIP",
    }

    assert len(result["high_risks"]) > 0


def test_freenow_av_partnership_manager():
    result = assess_opportunity(
        "FREENOW",
        "Senior Autonomous Vehicle Partnership Manager",
        """
        Build and manage partnerships with autonomous vehicle companies.

        Develop commercial relationships, negotiate business agreements,
        support autonomous mobility market launches and work across
        mobility operations and strategic partnerships.

        Commercial ownership and business development experience are
        important.

        Location: Germany.
        """,
    )

    print("\nFREENOW")
    print(result)

    assert result["career_lane"] in {
        "autonomy_robotics",
        "mobility_ecosystem",
    }

    assert result["recommendation"] in {
        "NETWORK_FIRST",
        "EXPLORE",
        "WATCH",
        "SKIP",
    }


def test_vw_china_adas_role():
    result = assess_opportunity(
        "Volkswagen",
        "Expert ADAS Global Functions",
        """
        Coordinate global ADAS functions between Germany and China.

        Work with engineering organizations, technical stakeholders
        and global vehicle programs.

        Chinese and German cross-cultural experience is highly valuable.

        Position is based in Hefei, China and requires relocation.
        """,
    )

    print("\nVW CHINA")
    print(result)

    assert result["recommendation"] == "SKIP"
    assert result["constraint_action"] == "SKIP"

def test_strong_av_tpm_berlin():
    result = assess_opportunity(
        "MOIA",
        "Senior Technical Program Manager - Autonomous Mobility",
        """
        Lead cross-functional autonomous mobility programs in Berlin.

        Coordinate engineering, suppliers, fleet operations, deployment,
        launch readiness, milestones, risks and senior stakeholders.

        Experience in ADAS, automated driving, mobility services and
        international technical programs is highly relevant.

        The role focuses on program execution, technical operations and
        deployment rather than hands-on software engineering or sales.

        Location: Berlin.
        """,
    )

    print("\nSTRONG AV TPM")
    print(result)

    assert result["career_lane"] == "autonomy_robotics"
    assert result["constraint_action"] in {
        "CLEAR",
        "REVIEW",
    }

    assert result["opportunity_score"] >= 70

    assert result["recommendation"] in {
        "NETWORK_FIRST",
        "APPLY_NOW",
        "EXPLORE",
    }