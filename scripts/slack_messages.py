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
def build_digest_message(
    day_label: str,
    since_label: str,
    new_count: int,
    waiting_count: int,
    top: list[dict],
) -> dict:
    """The morning summary: counts + top 10 qualified leads."""
    lines = [f"☀️ *Morning summary: {day_label}*"]

    if new_count == 0:
        lines.append(f"No new qualified leads since {since_label}.")
    else:
        word = "lead" if new_count == 1 else "leads"
        lines.append(f"🆕 *{new_count}* new qualified {word} since {since_label}")

    company_word = "company" if waiting_count == 1 else "companies"
    lines.append(f"⏳ *{waiting_count}* {company_word} still waiting to be scored")
    lines.append("")

    if not top:
        lines.append("There are no qualified leads yet.")
    else:
        lines.append("*Top 10 qualified leads*")
        for number, d in enumerate(top, start=1):
            mark = " 🆕" if d.get("is_new") else ""
            lines.append(f"{number}. {d['name']}, {d['score']}, {d['domain']}{mark}")

    return {"text": "\n".join(lines)}