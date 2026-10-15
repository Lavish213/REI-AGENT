import hashlib
import hmac
import os
import time

from backend.lib import db


def verify_adapter(body, timestamp, signature):
    secret = os.environ.get('INBOUND_EMAIL_ADAPTER_SECRET', '')
    if len(secret) < 32:
        return False
    try:
        if len(body) > 64000 or abs(time.time() - int(timestamp)) > 300:
            return False
        expected = hmac.new(secret.encode(), timestamp.encode() + b'.' + body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    except (ValueError, TypeError, AttributeError):
        return False


def accept_reply(payload):
    receipt = db.stage_inbound_email(payload)
    if db.email_reply_is_stop(payload["text"]):
        db.suppress_email_address(payload["sender"])
    db.recover_inbound_email()
    return receipt
