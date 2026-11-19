"""Choose exactly one transport; never fall back after a submission failure."""
from .email_policy import email_provider


def create_email_client():
    if email_provider() == "gmail":
        from .gmail_client import GmailClient
        return GmailClient()
    from .graph_client import GraphClient
    return GraphClient()
