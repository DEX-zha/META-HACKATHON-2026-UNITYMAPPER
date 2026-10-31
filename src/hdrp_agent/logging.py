import logging
import re


class SecretFilter(logging.Filter):
    def __init__(self, secrets=()):
        super().__init__()
        self.secrets = tuple(s for s in secrets if s)

    def filter(self, record):
        message = record.getMessage()
        for secret in self.secrets: message = message.replace(secret, "[redacted]")
        message = re.sub(r"(?i)Bearer\s+[^\s\"']+", "Bearer [redacted]", message)
        record.msg, record.args = message, ()
        return True


def configure(secrets=()):
    handler = logging.StreamHandler()
    handler.addFilter(SecretFilter(secrets))
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
