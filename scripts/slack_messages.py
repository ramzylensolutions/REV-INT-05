def build_alert_message(details: dict) -> dict:
    """Turn an alert's details into a Slack message.

    Placeholder: replaced with the agreed wording in Step 9.
    """
    text = f"New qualified lead: {details['name']} (score {details['score']}/100)"
    return {"text": text}

def build_summary_message(alerts: list[dict]) -> dict:
    """One message for many alerts: count, top 5 by score, and how many more."""
    ranked = sorted(
        alerts,
        key=lambda d: (-(d["score"] or 0), -(d["employees"] or 0), d["name"]),
    )
    top = ranked[:5]

    lines = [f"📥 *{len(alerts)} new qualified leads*", f"Top {len(top)} by score:"]
    for number, d in enumerate(top, start=1):
        lines.append(f"{number}. {d['name']}, {d['score']}, {d['domain']}")

    more = len(alerts) - len(top)
    if more > 0:
        lines.append(f"…and {more} more. They'll appear in the morning summary.")

    return {"text": "\n".join(lines)}