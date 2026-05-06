import os
from loguru import logger

import httpx


VOICEMAIL_SCRIPTS: dict[tuple[int, str], str] = {
    (1, "en"): (
        "Hey {name} — Sophia calling about your place on {address}. "
        "Built in {year}, {beds} bed — I think there's something there. "
        "Call me when you get a chance — {phone}."
    ),
    (2, "en"): (
        "Hey {name} — Sophia again. "
        "Just so you know — similar places in {neighborhood} have been moving around "
        "${arv_min} to ${arv_max} lately. "
        "Might be worth a quick conversation. {phone}."
    ),
    (3, "en"): (
        "Hey {name} — last message on {address}. "
        "We're buying in your area this month and I wanted to make sure you had the option. "
        "{phone}. Take care."
    ),
    (1, "es"): (
        "Oye {name} — te habla Sophia sobre tu propiedad en {address}. "
        "Construida en {year}, {beds} cuartos — creo que hay algo ahí. "
        "Llámame cuando puedas — {phone}."
    ),
    (2, "es"): (
        "Oye {name} — Sophia otra vez. "
        "Para que sepas — propiedades similares en {neighborhood} han estado "
        "moviéndose alrededor de ${arv_min} a ${arv_max} últimamente. "
        "Podría valer una conversación rápida. {phone}."
    ),
    (3, "es"): (
        "Oye {name} — último mensaje sobre {address}. "
        "Estamos comprando en tu área este mes y quería asegurarme de que tuvieras la opción. "
        "{phone}. Cuídate."
    ),
}

_voicemail_callback_tally: dict[int, int] = {1: 0, 2: 0, 3: 0}


def _get_first_name(lead: dict, prop: dict) -> str:
    owner = lead.get("owner_name") or (prop or {}).get("owner_name") or ""
    parts = owner.strip().split()
    return parts[0] if parts else "there"


def _arv_range_str(prop: dict) -> tuple[str, str]:
    arv = prop.get("estimated_arv")
    if not arv:
        return ("unknown", "unknown")
    low = int((arv * 0.90) / 100)
    high = int((arv * 1.05) / 100)
    return (f"{low:,}", f"{high:,}")


def select_script_number(speed_to_lead_attempts: int) -> int:
    if speed_to_lead_attempts <= 2:
        return 1
    if speed_to_lead_attempts <= 5:
        return 2
    return 3


def render_voicemail_script(lead: dict, prop: dict, script_num: int, language: str = "en") -> str:
    prop = prop or {}
    name = _get_first_name(lead, prop)
    address = prop.get("address", "your property")
    year = str(prop.get("year_built", "")) or "a while back"
    beds = str(prop.get("beds", "")) or "several"
    phone = os.environ.get("SIGNALWIRE_PHONE", "")
    neighborhood = prop.get("city", "your area")
    arv_min, arv_max = _arv_range_str(prop)

    key = (script_num, language)
    if key not in VOICEMAIL_SCRIPTS:
        key = (1, "en")

    return VOICEMAIL_SCRIPTS[key].format(
        name=name,
        address=address,
        year=year,
        beds=beds,
        phone=phone,
        neighborhood=neighborhood,
        arv_min=arv_min,
        arv_max=arv_max,
    )


def _generate_cartesia_mp3(text: str) -> bytes | None:
    api_key = os.environ.get("CARTESIA_API_KEY", "")
    voice_id = os.environ.get("CARTESIA_VOICE_ID", "")
    if not api_key or not voice_id:
        return None
    try:
        resp = httpx.post(
            "https://api.cartesia.ai/tts/bytes",
            headers={
                "X-API-Key": api_key,
                "Cartesia-Version": "2024-06-10",
                "Content-Type": "application/json",
            },
            json={
                "model_id": "sonic-2024-10-19",
                "transcript": text,
                "voice": {"mode": "id", "id": voice_id},
                "output_format": {
                    "container": "wav",
                    "encoding": "pcm_s16le",
                    "sample_rate": 22050,
                },
            },
            timeout=20.0,
        )
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        logger.warning("cartesia_voicemail_gen_failed error={}", str(e))
        return None


def _upload_voicemail_to_storage(audio_bytes: bytes, lead_id: str, script_num: int) -> str | None:
    try:
        from backend.lib.db import _get_client
        client = _get_client()
        filename = f"voicemail_{lead_id}_script{script_num}.wav"
        client.storage.from_("voicemails").upload(
            filename,
            audio_bytes,
            {"content-type": "audio/wav", "x-upsert": "true"},
        )
        public_url = client.storage.from_("voicemails").get_public_url(filename)
        logger.info("voicemail_uploaded lead_id={} script={} url={}", lead_id, script_num, public_url)
        return public_url
    except Exception as e:
        logger.warning("voicemail_upload_failed lead_id={} error={}", lead_id, str(e))
        return None


def build_ringless_voicemail_laml(
    lead: dict,
    prop: dict,
    script_num: int = 1,
    language: str = "en",
) -> str:
    lead_id = lead.get("id", "unknown")
    script_text = render_voicemail_script(lead, prop, script_num, language)
    logger.info(
        "ringless_voicemail lead_id={} script={} language={}",
        lead_id,
        script_num,
        language,
    )

    from backend.lib.db import update_call_voicemail_script
    try:
        update_call_voicemail_script(lead_id, script_num)
    except Exception:
        pass

    audio_bytes = _generate_cartesia_mp3(script_text)
    if audio_bytes:
        public_url = _upload_voicemail_to_storage(audio_bytes, lead_id, script_num)
        if public_url:
            return (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<Response>\n"
                f"    <Play>{public_url}</Play>\n"
                "    <Hangup/>\n"
                "</Response>"
            )

    polly_voice = "Polly.Joanna" if language == "en" else "Polly.Lupe"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        f'    <Say voice="{polly_voice}" rate="90%">{script_text}</Say>\n'
        "    <Hangup/>\n"
        "</Response>"
    )


def record_voicemail_callback(script_num: int) -> None:
    if script_num in _voicemail_callback_tally:
        _voicemail_callback_tally[script_num] += 1
    logger.info(
        "voicemail_callback_recorded script={} tally={}",
        script_num,
        _voicemail_callback_tally,
    )


def get_callback_stats() -> dict[int, int]:
    return dict(_voicemail_callback_tally)
