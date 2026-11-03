import pytest

from scripts.scoring_rule import calculate_score, THRESHOLD, TIER_1, TIER_2
@pytest.mark.parametrize(
    "employees, expected_size",
    [
        (5000, 60),
        (1000, 60),  # exact boundary: 1000 is top tier
        (999, 45),   # just below: catches using > 1000 instead of >= 1000
        (200, 45),   # exact boundary
        (199, 30),
        (50, 30),    # exact boundary
        (49, 15),
        (1, 15),     # smallest real company
    ],
)
def test_size_points_by_employee_count(employees, expected_size):
    # Bug caught: wrong points for a size band, or off-by-one at a boundary
    assert calculate_score(employees, "Japan")["size"] == expected_size


def test_zero_employees_gets_no_size_points():
    # Bug caught: 0 employees treated as a small company (15 points)
    assert calculate_score(0, "Japan")["size"] == 0


def test_negative_employees_gets_no_size_points():
    # Bug caught: bad data giving points or crashing
    assert calculate_score(-10, "Japan")["size"] == 0


def test_missing_employees_gets_no_size_points():
    # Bug caught: crash on None (e.g. None > 999 raises TypeError)
    assert calculate_score(None, "Japan")["size"] == 0


@pytest.mark.parametrize("country", sorted(TIER_1))
def test_tier_1_countries_get_40(country):
    # Bug caught: Tier 1 country getting the wrong points
    assert calculate_score(10, country)["market"] == 40


@pytest.mark.parametrize("country", sorted(TIER_2))
def test_tier_2_countries_get_25(country):
    # Bug caught: Tier 2 country missing from the list
    assert calculate_score(10, country)["market"] == 25


def test_india_gets_exactly_40_not_50():
    # Bug caught: two separate ifs instead of if/elif, so India also
    # falls into the "other country" branch and gets +10 extra
    assert calculate_score(10, "India")["market"] == 40


def test_united_kingdom_full_name_is_tier_2():
    # Bug caught: list using "UK" while the data uses "United Kingdom"
    assert calculate_score(10, "United Kingdom")["market"] == 25


@pytest.mark.parametrize("country", ["Japan", "Brazil", "France"])
def test_other_countries_get_10(country):
    # Bug caught: unknown countries getting 0 or Tier points
    assert calculate_score(10, country)["market"] == 10


def test_missing_country_gets_no_market_points():
    # Bug caught: crash on None, or None treated as "other country" (10)
    assert calculate_score(10, None)["market"] == 0


def test_empty_country_gets_no_market_points():
    # Bug caught: empty string treated as a real country
    assert calculate_score(10, "")["market"] == 0


def test_country_match_is_case_sensitive():
    # Documents current behaviour: "india" (lowercase) is not "India".
    # If this test starts failing, the rule changed on purpose or by accident.
    assert calculate_score(10, "india")["market"] == 10



def test_score_is_size_plus_market():
    # Bug caught: score calculated from the wrong parts
    result = calculate_score(749, "India")
    assert result["score"] == result["size"] + result["market"] == 85


def test_missing_country_keeps_size_points():
    # Bug caught: a missing country resetting the whole score to 0
    result = calculate_score(1500, None)
    assert result["size"] == 60
    assert result["score"] == 60


def test_maximum_score_is_100():
    # Bug caught: points adding up to more than 100
    assert calculate_score(5000, "USA")["score"] == 100


def test_missing_everything_scores_0():
    # Bug caught: crash or a non-zero default for an empty record
    result = calculate_score(None, None)
    assert result["score"] == 0
    assert result["stage"] == "disqualified"


def test_score_exactly_at_threshold_is_qualified():
    # Bug caught: using > instead of >= for the threshold
    result = calculate_score(1500, None)  # 60 + 0
    assert result["score"] == THRESHOLD
    assert result["stage"] == "qualified"


def test_score_just_below_threshold_is_disqualified():
    # Bug caught: threshold set too low, or stage not set at all
    result = calculate_score(30, "India")  # 15 + 40 = 55
    assert result["score"] < THRESHOLD
    assert result["stage"] == "disqualified"


@pytest.mark.parametrize(
    "employees, country, expected_score, expected_stage",
    [
        (2400, "India", 100, "qualified"),
        (1200, "Germany", 85, "qualified"),
        (3100, "Japan", 70, "qualified"),
        (150, "India", 70, "qualified"),
        (520, "Brazil", 55, "disqualified"),
        (120, "Japan", 40, "disqualified"),
        (3, "Japan", 25, "disqualified"),
    ],
)
def test_examples_from_companies_20_file(employees, country, expected_score, expected_stage):
    # Bug caught: the rule no longer matching the hand-checked ranking table
    result = calculate_score(employees, country)
    assert result["score"] == expected_score
    assert result["stage"] == expected_stage


def test_result_has_all_expected_keys():
    # Bug caught: a key renamed or removed, which would break the handler
    result = calculate_score(100, "India")
    assert set(result.keys()) == {"size", "market", "score", "stage"}


def test_stage_is_always_a_known_value():
    # Bug caught: a stage value the database check constraint would reject
    for employees in [None, 0, 10, 100, 500, 5000]:
        for country in [None, "India", "Germany", "Japan"]:
            assert calculate_score(employees, country)["stage"] in {"qualified", "disqualified"}