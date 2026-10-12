"""Opt-in mail realism profile; invented data only, never private examples."""
import re
PROFILE = "mail-realism-v1"
GUIDANCE = """Generation profile mail-realism-v1. Write a plausible received email, not an explanation of a category. Use invented names, organizations and reserved example.org domains only. Respect the requested length and format, including subject-only mail, messy HTML-to-text artifacts, links, Unicode punctuation, signatures and quoted histories. Do not copy real brands, correspondence or private identifying information. Never disclose intended labels or generation metadata in the content. Empty body is valid when the subject supplies readable evidence. Use the length requested by the scenario and the provider completion-token budget. Do not silently truncate text."""
REVIEW_GUIDANCE = """Classify communicative purpose rather than topic keywords or delivery frequency. An automated application receipt/rejection, task deadline, delivery failure, authentication notice, or report-available notice is an operational alert even if warmly worded. An account statement or retained application-data copy can also be transactions/records; an acknowledgement alone need not be a transaction. A past meeting recap/notes-ready notice is an alert, not a new invitation or group discussion merely because it says someone invited a recorder or mentions discussions. Current meeting confirmation/reminder/reschedule is scheduling and can also be an alert. A product release changelog can be both curated publication and operational update. A delivered editorial article is not promotional merely because it has subscription links. Judge concrete persuasive outreach separately. Ignore obsolete quoted invitations and generic calendar/signature/footer links. Informative subject-only operational reports remain observable alerts; attachments do not reveal unseen contents. Missing context must not become seven negative labels. Return unknown for genuinely undecidable purposes, with exact visible positive evidence."""

def profile_valid(content):
    if not isinstance(content, dict) or set(content) != {"subject", "body"}:
        return False
    for key in ("subject", "body"):
        value = content[key]
        if not isinstance(value, str):
            return False
        if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value):
            return False
    return any(v.strip() for v in content.values())
