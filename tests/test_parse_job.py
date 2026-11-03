import json

import pytest

from scripts.handlers import MalformedJob, require
from scripts.main import parse_job


def body(**fields):
    """Turn keyword arguments into a JSON message body."""
    return json.dumps(fields)


VALID = {
    "task": "score_account",
    "account_id": "31ae6896-8097-4920-83db-97e211f8acaf",
    "idempotency_key": "7f3a9c2e-1b4d-4e8a-9c6f-2d5e8a1b3c7f",
}


# ---------------------------------------------------------------
# parse_job: valid messages
# ---------------------------------------------------------------

def test_valid_job_is_returned_as_dict():
    # Bug caught: good messages rejected or changed while parsing
    job = parse_job(body(**VALID))
    assert job == VALID


def test_extra_fields_are_allowed():
    # Bug caught: messages rejected just because they carry an extra field
    job = parse_job(body(**VALID, rescore=True))
    assert job["task"] == "score_account"


# ---------------------------------------------------------------
# parse_job: malformed messages (must raise MalformedJob, so they are
# parked in the DLQ instead of retried forever)
# ---------------------------------------------------------------

def test_bad_json_is_malformed():
    # Bug caught: broken JSON crashing with a normal error and retrying forever
    with pytest.raises(MalformedJob):
        parse_job("{not valid json")


def test_empty_body_is_malformed():
    with pytest.raises(MalformedJob):
        parse_job("")


@pytest.mark.parametrize("raw", ['"just a string"', "[1, 2, 3]", "42", "null"])
def test_body_that_is_not_an_object_is_malformed(raw):
    # Bug caught: valid JSON that is not an object (string, list, number)
    # crashing later with a confusing error
    with pytest.raises(MalformedJob):
        parse_job(raw)


@pytest.mark.parametrize("missing", ["task", "account_id", "idempotency_key"])
def test_missing_required_field_is_malformed(missing):
    # Bug caught: a message without a required field reaching the handler and crashing
    fields = {k: v for k, v in VALID.items() if k != missing}
    with pytest.raises(MalformedJob) as error:
        parse_job(body(**fields))
    assert missing in str(error.value)


def test_unknown_task_is_malformed():
    # Bug caught: unknown task types retried forever instead of parked
    with pytest.raises(MalformedJob):
        parse_job(body(**{**VALID, "task": "delete_everything"}))


def test_task_name_is_case_sensitive():
    # Bug caught: "Score_account" accepted while HANDLERS only knows "score_account"
    with pytest.raises(MalformedJob):
        parse_job(body(**{**VALID, "task": "Score_account"}))


# ---------------------------------------------------------------
# require
# ---------------------------------------------------------------

def test_require_passes_when_all_fields_present():
    require({"a": 1, "b": 2}, "a", "b")  # no error means pass


def test_require_lists_every_missing_field():
    # Bug caught: only the first missing field reported, hiding the others
    with pytest.raises(MalformedJob) as error:
        require({}, "task", "account_id")
    message = str(error.value)
    assert "task" in message
    assert "account_id" in message


def test_require_treats_none_value_as_present():
    # Documents current behaviour: require only checks that the key exists.
    # A key with value None passes here; the handler must cope with it.
    require({"account_id": None}, "account_id")