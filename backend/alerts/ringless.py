from __future__ import annotations

import os
from loguru import logger

_voicemail_callback_tally: dict[int, int] = {1: 0, 2: 0, 3: 0}

_SCRIPTS: dict[str, dict[int, str]] = {
    "en": {
        1: (
            "Hey, this is Sophia calling from San Joaquin House Buyers. "
            "I was reaching out about your property and wanted to connect. "
            "Give me a call back at {phone} when you get a chance. Thanks!"
        ),
        2: (
            "Hey {first_name}, Sophia again from San Joaquin House Buyers. "
            "Properties in your area have been moving fast lately and I wanted to get you a real number. "
            "Call me back at {phone} — takes about five minutes. Hope to hear from you!"
        ),
        3: (
            "Hey {first_name}, last message from Sophia at San Joaquin House Buyers. "
            "We're actively buying in your neighborhood this month. "
            "If you ever want a fast cash offer, no repairs, no hassle — call me at {phone}. "
            "No pressure at all. Take care!"
        ),
    },
    "es": {
        1: (
            "Hola, soy Sophia de San Joaquin House Buyers. "
            "Te llamo sobre tu propiedad y quería comunicarme contigo. "
            "Llámame al {phone} cuando puedas. ¡Gracias!"
        ),
        2: (
            "Hola {first_name}, soy Sophia de nuevo de San Joaquin House Buyers. "
            "Las propiedades en tu área se están vendiendo rápido. "
            "Llámame al {phone} — solo toma cinco minutos. ¡Espero saber de ti!"
        ),
        3: (
            "Hola {first_name}, último mensaje de Sophia de San Joaquin House Buyers. "
            "Estamos comprando activamente en tu vecindario este mes. "
            "Si alguna vez quieres una oferta en efectivo rápida, llámame al {phone}. ¡Cuídate!"
        ),
    },
}


def select_script_number(attempts: int) -> int:
    if attempts <= 1:
        return 1
    if attempts == 2:
        return 2
    return 3


def _get_script_text(script_num: int, lead: dict, prop: dict, lang: str = "en") -> str:
    scripts = _SCRIPTS.get(lang, _SCRIPTS["en"])
    template = scripts.get(script_num, scripts[3])
    name_raw = lead.get("owner_name") or (prop or {}).get("owner_name") or ""
    first_name = name_raw.strip().split()[0] if name_raw.strip() else "there"
    phone = os.environ.get("AGENT_PHONE", os.environ.get("SIGNALWIRE_PHONE", ""))
    return template.format(first_name=first_name, phone=phone)


def build_ringless_voicemail_laml(lead: dict, prop: dict, script_num: int, lang: str = "en") -> str:
    from backend.alerts.ringless import _build_cartesia_laml, _build_polly_laml
    script_text = _get_script_text(script_num, lead, prop, lang)
    cartesia_key = os.environ.get("CARTESIA_API_KEY", "")
    if cartesia_key:
        try:
            return _build_cartesia_laml(script_text, lead, prop, script_num)
        except Exception as e:
            logger.warning("cartesia_laml_failed script={} error={} falling back to polly", script_num, str(e))
    return _build_polly_laml(script_text)


def _build_cartesia_laml(script_text: str, lead: dict, prop: dict, script_num: int) -> str:
    voice_id   = os.environ.get("CARTESIA_VOICE_ID", "")
    model      = os.environ.get("CARTESIA_MODEL", "sonic-3")
    api_key    = os.environ.get("CARTESIA_API_KEY", "")
    public_url = os.environ.get("PUBLIC_URL", "").rstrip("/")

    if not voice_id or not api_key:
        raise ValueError("cartesia env vars not set")

    import httpx
    response = httpx.post(
        "https://api.cartesia.ai/tts/bytes",
        headers={
            "X-API-Key": api_key,
            "Cartesia-Version": "2024-06-10",
            "Content-Type": "application/json",
        },
        json={
            "model_id": model,
            "transcript": script_text,
            "voice": {"mode": "id", "id": voice_id},
            "output_format": {"container": "mp3", "encoding": "mp3", "sample_rate": 44100},
        },
        timeout=15,
    )
    response.raise_for_status()

    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    lead_id = lead.get("id", "unknown")
    file_key = f"voicemails/{lead_id}_script{script_num}.mp3"
    sb.storage.from_("voicemails").upload(
        file_key,
        response.content,
        {"content-type": "audio/mpeg", "upsert": "true"},
    )
    audio_url = f"{os.environ['SUPABASE_URL']}/storage/v1/object/public/voicemails/{file_key}"
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Play>{audio_url}</Play></Response>'


def _build_polly_laml(script_text: str) -> str:
    safe = script_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        '<Say voice="Polly.Joanna" language="en-US">'
        f"{safe}"
        "</Say>"
        "</Response>"
    )


def build_voicemail_laml(lead: dict, prop: dict) -> str:
    prop = prop or {}
    name_raw = lead.get("owner_name") or prop.get("owner_name") or ""
    first_name = name_raw.strip().split()[0] if name_raw.strip() else "there"
    phone = os.environ.get("AGENT_PHONE", os.environ.get("SIGNALWIRE_PHONE", ""))
    text = (
        f"Hey {first_name}, this is Sophia from San Joaquin House Buyers. "
        f"Just calling about your property — give me a call back at {phone} when you get a chance. Thanks!"
    )
    return _build_polly_laml(text)


def record_voicemail_callback(script_num: int, lead_id: str | None = None, call_sid: str | None = None) -> None:
    if script_num in _voicemail_callback_tally:
        _voicemail_callback_tally[script_num] += 1
    logger.info("voicemail_callback_recorded script={} tally={}", script_num, _voicemail_callback_tally)

    if lead_id:
        try:
            from backend.lib.db import _get_client
            _get_client().table("calls").insert({
                "lead_id": lead_id,
                "signalwire_call_id": call_sid or f"vm_callback_{lead_id}_{script_num}",
                "direction": "inbound",
                "call_disposition": "vm_callback",
                "notes": f"Caller called back after voicemail script {script_num}",
                "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            }).execute()
            logger.info("voicemail_callback_persisted lead_id={} script={}", lead_id, script_num)
        except Exception as e:
            logger.warning("voicemail_callback_persist_failed lead_id={} error={}", lead_id, str(e))
