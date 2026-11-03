RULE_VERSION = "v1"
THRESHOLD = 60
TIER_1 = {"India", "USA"}
TIER_2 = {"United Kingdom", "Germany", "Singapore", "Australia", "Canada"}


def calculate_score(employees, country):
    if employees is None:
        size = 0
    elif employees >= 1000:
        size = 60
    elif employees >= 200:
        size = 45
    elif employees >= 50:
        size = 30
    elif employees >= 1:
        size = 15
    else:
        size = 0

    if not country:
        market = 0
    elif country in TIER_1:
        market = 40
    elif country in TIER_2:
        market = 25
    else:
        market = 10

    score = size + market
    stage = "qualified" if score > THRESHOLD else "disqualified"

    return {"size": size, "market": market, "score": score, "stage": stage}