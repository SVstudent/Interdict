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
