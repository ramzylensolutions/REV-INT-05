def build_alert_message(details: dict) -> dict:
    """Turn an alert's details into a Slack message.

    Placeholder: replaced with the agreed wording in Step 9.
    """
    text = f"New qualified lead: {details['name']} (score {details['score']}/100)"
    return {"text": text}