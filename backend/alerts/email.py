import os
from loguru import logger


def send_email(to: str, subject: str, body: str) -> bool:
    sendgrid_key = os.environ.get("SENDGRID_API_KEY", "")
    if not sendgrid_key or sendgrid_key.startswith("placeholder"):
        logger.warning("SendGrid not configured skipping email to={}", to)
        return False

    try:
        import httpx
        response = httpx.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {sendgrid_key}",
                "Content-Type": "application/json",
            },
            json={
                "personalizations": [{"to": [{"email": to}]}],
                "from": {
                    "email": os.environ.get("BUSINESS_EMAIL", "alanzo@sanjoaquinhousebuyers.com"),
                    "name": os.environ.get("BUSINESS_NAME", "San Joaquin House Buyers"),
                },
                "subject": subject,
                "content": [{"type": "text/plain", "value": body}],
            },
            timeout=10,
        )
        response.raise_for_status()
        logger.info("email sent to={} subject={}", to, subject)
        return True
    except Exception as e:
        logger.error("email failed to={} error={}", to, str(e))
        return False


def send_walkthrough_confirmation_email(
    to: str,
    owner_name: str,
    address: str,
    appointment_str: str,
) -> bool:
    subject = f"Walkthrough Confirmed — {address}"
    body = f"""Hey {owner_name},

Just confirming your walkthrough appointment:

Address: {address}
Date/Time: {appointment_str}

Alanzo will be there to take a look. The walkthrough usually takes about 20 minutes.

If anything changes just reply to this email or text us at {os.environ.get('AGENT_PHONE', '')}.

Talk soon,
Sophia
{os.environ.get('BUSINESS_NAME', 'San Joaquin House Buyers')}
{os.environ.get('AGENT_PHONE', '')}
"""
    return send_email(to=to, subject=subject, body=body)


def send_weekly_report_email(report_text: str) -> bool:
    owner_email = os.environ.get("BUSINESS_EMAIL", "")
    if not owner_email:
        logger.warning("no owner email configured for weekly report")
        return False

    subject = f"REI Agent Weekly Report — {__import__('datetime').date.today()}"
    return send_email(to=owner_email, subject=subject, body=report_text)
