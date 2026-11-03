import pytest
from pydantic import ValidationError
from app.models.create_companies import create_companies

def make(domain, **extra):
    return create_companies(name="Test Co", domain=domain, **extra)

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://WWW.Example.com/", "example.com"),   # the exact case from the ticket
        ("http://example.com", "example.com"),
        ("https://example.com", "example.com"),
        ("www.example.com", "example.com"),
        ("WWW.EXAMPLE.COM", "example.com"),
        ("example.com/about", "example.com"),
        ("http://example.com/about/team", "example.com"),
        ("  Example.COM  ", "example.com"),
        ("example.com", "example.com"),                 # already clean: unchanged
    ],
)
def test_domain_is_cleaned(raw, expected):
    # Bug caught: messy domains stored as-is, so the same company
    # could be imported twice under two different spellings
    assert make(raw).domain == expected


def test_messy_and_clean_domain_become_identical():
    # Bug caught: duplicate protection failing because cleaning
    # produces different results for the same company
    assert make("https://WWW.Example.com/").domain == make("example.com").domain


def test_www_inside_the_name_is_kept():
    # Bug caught: removing "www" from the middle of a domain
    # instead of only from the start
    assert make("mywwwsite.com").domain == "mywwwsite.com"


# ---------------------------------------------------------------
# Required and optional fields
# ---------------------------------------------------------------

def test_missing_employees_is_allowed():
    # Bug caught: companies with missing employees rejected (422)
    # instead of imported and scored. The ticket requires they still get an account.
    company = create_companies(name="Test Co", domain="example.com", country="India")
    assert company.employees is None


def test_missing_country_is_allowed():
    # Bug caught: same as above, for country
    company = create_companies(name="Test Co", domain="example.com", employees=100)
    assert company.country is None


def test_explicit_nulls_are_allowed():
    # Bug caught: null values in the file rejected instead of treated as missing
    company = create_companies(name="Test Co", domain="example.com", employees=None, country=None)
    assert company.employees is None
    assert company.country is None


def test_missing_name_is_rejected():
    # Bug caught: companies without a name accepted
    with pytest.raises(ValidationError):
        create_companies(domain="example.com")


def test_missing_domain_is_rejected():
    # Bug caught: companies without a domain accepted; without a domain
    # there is no way to detect duplicates
    with pytest.raises(ValidationError):
        create_companies(name="Test Co")


def test_text_employee_count_is_rejected():
    # Bug caught: "abc" accepted as an employee count
    with pytest.raises(ValidationError):
        make("example.com", employees="abc")


def test_numeric_text_employee_count_is_converted():
    # Documents current behaviour: "1300" (text) is converted to 1300
    assert make("example.com", employees="1300").employees == 1300