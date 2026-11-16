from scripts.slack_client import SendResult


class FakeSlack:
    """A pretend Slack for tests. Never uses the network."""

    def __init__(self):
        self.sent = []          # messages that were "delivered"
        self.attempts = 0       # how many times send() was called
        self.next_results = []  # answers to give, in order

    def will_return(self, *results: SendResult):
        """Tell the fake what to answer on the next calls."""
        self.next_results.extend(results)

    async def send(self, payload: dict) -> SendResult:
        self.attempts += 1

        if self.next_results:
            result = self.next_results.pop(0)
        else:
            result = SendResult("sent")  # no script left: Slack works normally

        if result.outcome == "sent":
            self.sent.append(payload)

        return result