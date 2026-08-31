"""Redaction helpers for anything that leaves the process as text.

Log lines are the leak path nobody audits, so account-like digit runs are masked to their last
four before they can reach a log sink, a span attribute or an error message. This is defence in
depth rather than the primary control: the domain model already cannot hold a full account
number (`BankingDetails` stores only `account_last4`).
"""
import re


class RedactionModule:
    @staticmethod
    def mask_account_number(account_num: str) -> str:
        clean = re.sub(r"\D", "", account_num)
        if len(clean) >= 4:
            return f"****{clean[-4:]}"
        return "****"

    @staticmethod
    def sanitize_log_message(message: str) -> str:
        # Mask 9-16 digit numbers that look like bank accounts or SSNs
        return re.sub(r"\b\d{9,16}\b", lambda m: f"****{m.group(0)[-4:]}", message)

redactor = RedactionModule()
