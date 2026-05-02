import os

from loguru import logger
from signalwire.rest import Client as SignalWireClient

from backend.lib.db import insert_sms


_client: SignalWireClient | None = None


def _get_client() -> SignalWireClient:
    global _client
    if _client is None:
        project_id = os.environ["SIGNALWIRE_PROJECT_ID"]
        token = os.environ["SIGNALWIRE_TOKEN"]
        space = os.environ["SIGNALWIRE_SPACE"]
        _client = SignalWireClient(
            project_id,
            token,
            signalwire_space_url=space
        )
        logger.info("SignalWire client initialized")
    return _client


def send_sms(to: str, body: str) -> bool:
    from_number = os.environ["SIGNALWIRE_PHONE"]

    calling_start = int(os.environ.get("CALLING_HOURS_START", 8))
    calling_end = int(os.environ.get("CALLING_HOURS_END", 21))

    from datetime import datetime, timezone
    import pytz
    pacific = pytz.timezone("America/Los_Angeles")
    current_hour = datetime.now(pacific).hour

    if current_hour < calling_start or current_hour >= calling_end:
        logger.warning("send_sms blocked outside TCPA hours hour={}", current_hour)
        return False

    try:
        client = _get_client()
        message = client.messages.create(
            from_=from_number,
            to=to,
            body=body
        )

        insert_sms({
            "direction": "outbound",
            "body": body,
            "signalwire_message_id": message.sid,
            "sent_at": datetime.now(timezone.utc).isoformat()
        })

        logger.info("send_sms to={} sid={}", to, message.sid)
        return True

    except Exception as e:
        logger.error("send_sms failed to={} error={}", to, str(e))
        return False


def send_alert_to_owner(body: str) -> bool:
    alert_phone = os.environ.get("ALERT_PHONE", "")
    if not alert_phone:
        logger.warning("ALERT_PHONE not set skipping owner alert")
        return False
    return send_sms(to=alert_phone, body=body)


def send_drip_sms(to: str, body: str, lead_id: str) -> bool:
    from_number = os.environ["SIGNALWIRE_PHONE"]

    from datetime import datetime, timezone
    import pytz
    pacific = pytz.timezone("America/Los_Angeles")
    current_hour = datetime.now(pacific).hour
    calling_start = int(os.environ.get("CALLING_HOURS_START", 8))
    calling_end = int(os.environ.get("CALLING_HOURS_END", 21))

    if current_hour < calling_start or current_hour >= calling_end:
        logger.warning("send_drip_sms blocked outside TCPA hours")
        return False

    try:
        client = _get_client()
        message = client.messages.create(
            from_=from_number,
            to=to,
            body=body
        )

        insert_sms({
            "lead_id": lead_id,
            "direction": "outbound",
            "body": body,
            "signalwire_message_id": message.sid,
            "sent_at": datetime.now(timezone.utc).isoformat()
        })

        logger.info("send_drip_sms to={} lead_id={} sid={}", to, lead_id, message.sid)
        return True

    except Exception as e:
        logger.error("send_drip_sms failed to={} error={}", to, str(e))
        return False
