import pytest

from dealscope.providers.classify import JOB_ROLE_TERM_TITLES, PERSON_ROLE_GROUP_TITLES, classify_title


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("CTO", ("technical_leadership", "general_engineering")),
        ("Chief Technology Officer", ("technical_leadership", "general_engineering")),
        ("VP Engineering", ("technical_leadership", "general_engineering")),
        ("Vice President of Engineering", ("technical_leadership", "general_engineering")),
        ("Head of Engineering", ("technical_leadership", "general_engineering")),
        ("Director of Engineering", ("technical_leadership", "general_engineering")),
        ("Chief Architect", ("technical_leadership", "general_engineering")),
        ("Head of Platform Engineering", ("technical_leadership", "platform_engineering")),
        ("Principal Engineer", ("senior_technical_ic", "general_engineering")),
        ("Staff Software Engineer", ("senior_technical_ic", "general_engineering")),
        ("Distinguished Engineer", ("senior_technical_ic", "general_engineering")),
        ("Principal Platform Engineer", ("senior_technical_ic", "platform_engineering")),
        ("Staff SRE", ("senior_technical_ic", "reliability")),
        ("Staff Site Reliability Engineer", ("senior_technical_ic", "reliability")),
        ("CISO", ("security", "security")),
        ("Head of Security", ("security", "security")),
        ("Security Engineering Manager", ("security", "security")),
        ("Director of Security", ("security", "security")),
        ("Head of Data", ("data_ml", "data_ml")),
        ("Director of Data Science", ("data_ml", "data_ml")),
        ("Head of Machine Learning", ("data_ml", "data_ml")),
        ("ML Engineering Manager", ("data_ml", "data_ml")),
        ("Machine Learning Platform Engineer", ("data_ml", "data_ml")),
        ("Data Engineer", ("data_ml", "data_ml")),
        ("Senior Backend Engineer", ("other_technical", "platform_engineering")),
        ("Infrastructure Engineer", ("other_technical", "platform_engineering")),
        ("DevOps Engineer", ("other_technical", "reliability")),
        ("Software Engineer", ("other_technical", "general_engineering")),
        ("Sales Engineer", ("non_technical", "other")),
        ("Head of Sales", ("non_technical", "other")),
        ("Technical Recruiter", ("non_technical", "other")),
        ("Product Manager", ("non_technical", "other")),
        ("Staff Accountant", ("non_technical", "other")),
        ("Chief Financial Officer", ("non_technical", "other")),
        ("Principal Consultant", ("non_technical", "other")),
        ("", ("non_technical", "other")),
        (None, ("non_technical", "other")),
    ],
)
def test_classify_title(title, expected):
    assert classify_title(title) == expected


def test_case_and_punctuation_insensitive():
    assert classify_title("  vp, ENGINEERING ") == ("technical_leadership", "general_engineering")


def test_cto_with_other_chief_title_still_technical():
    assert classify_title("CTO and Chief Product Officer")[0] == "technical_leadership"


def test_query_vocabularies_are_consistent_with_classifier():
    # Every title used to search a role group should classify into that group (security/data titles included).
    for group, titles in PERSON_ROLE_GROUP_TITLES.items():
        for title in titles:
            assert classify_title(title)[0] == group, title
    assert set(JOB_ROLE_TERM_TITLES) == {"engineering_leadership", "platform", "security", "data_ml", "reliability"}
