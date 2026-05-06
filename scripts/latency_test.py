import os
import time
import asyncio
import httpx
from dotenv import load_dotenv

load_dotenv()

TEST_TEXT = "Oh yeah — so based on what I'm seeing for your area we're probably looking somewhere in the one-sixty to one-eighty range. Does that give you something to work with?"
TEST_TEXT_SHORT = "Mhm, yeah — got it."

RESULTS = []


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


async def test_anthropic_ttft():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  SKIP  Anthropic — ANTHROPIC_API_KEY not set")
        return

    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)

    print("  Testing Anthropic first-token latency...")
    start = time.perf_counter()
    ttft = None

    try:
        async with client.messages.stream(
            model=os.environ.get("LLM_MODEL", "claude-sonnet-4-6"),
            max_tokens=80,
            messages=[{
                "role": "user",
                "content": "Hey — is this Maria? Hey! Sophia calling from San Joaquin House Buyers. You still own the place on 1847 East Hammer Lane?",
            }],
            system="You are Sophia Reyes, 25 year old acquisitions coordinator. Respond naturally in 1-2 short sentences. Be warm and casual.",
        ) as stream:
            async for text in stream.text_stream:
                if ttft is None:
                    ttft = _ms(start)
                    break

        total = _ms(start)
        status = "OK" if ttft < 800 else "SLOW"
        print(f"  {status}  Anthropic TTFT={ttft}ms  total={total}ms")
        RESULTS.append(("Anthropic TTFT", ttft, 800, status))
    except Exception as e:
        print(f"  ERR  Anthropic — {e}")
        RESULTS.append(("Anthropic TTFT", None, 800, "ERR"))


async def test_orpheus_ttfb():
    api_key = os.environ.get("TOGETHER_AI_API_KEY")
    if not api_key:
        print("  SKIP  Orpheus TTS — TOGETHER_AI_API_KEY not set")
        return

    print("  Testing Orpheus TTS time-to-first-byte...")
    start = time.perf_counter()
    ttfb = None
    total_bytes = 0

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            async with client.stream(
                "POST",
                "https://api.together.xyz/v1/audio/speech",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "cartesia/orpheus-3b-0.1-ft",
                    "input": TEST_TEXT,
                    "voice": "leah",
                    "response_format": "pcm",
                    "stream": True,
                },
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    print(f"  ERR  Orpheus — HTTP {resp.status_code}: {body[:200]}")
                    RESULTS.append(("Orpheus TTFB", None, 300, "ERR"))
                    return

                async for chunk in resp.aiter_bytes(chunk_size=4096):
                    if chunk:
                        if ttfb is None:
                            ttfb = _ms(start)
                        total_bytes += len(chunk)

        total = _ms(start)
        status = "OK" if ttfb < 300 else "SLOW"
        kb = total_bytes // 1024
        print(f"  {status}  Orpheus TTFB={ttfb}ms  total={total}ms  bytes={kb}KB")
        RESULTS.append(("Orpheus TTFB", ttfb, 300, status))
    except Exception as e:
        print(f"  ERR  Orpheus — {e}")
        RESULTS.append(("Orpheus TTFB", None, 300, "ERR"))


async def test_cartesia_ttfb():
    api_key = os.environ.get("CARTESIA_API_KEY")
    voice_id = os.environ.get("CARTESIA_VOICE_ID")
    if not api_key or not voice_id:
        print("  SKIP  Cartesia TTS — CARTESIA_API_KEY or CARTESIA_VOICE_ID not set")
        return

    print("  Testing Cartesia TTS time-to-first-byte...")
    start = time.perf_counter()
    ttfb = None
    total_bytes = 0

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.cartesia.ai/tts/bytes",
                headers={
                    "X-API-Key": api_key,
                    "Cartesia-Version": "2024-06-10",
                    "Content-Type": "application/json",
                },
                json={
                    "model_id": "sonic-2024-10-19",
                    "transcript": TEST_TEXT,
                    "voice": {"mode": "id", "id": voice_id},
                    "output_format": {
                        "container": "raw",
                        "encoding": "pcm_s16le",
                        "sample_rate": 16000,
                    },
                },
            )
            ttfb = _ms(start)
            resp.raise_for_status()
            total_bytes = len(resp.content)

        total = _ms(start)
        status = "OK" if ttfb < 400 else "SLOW"
        kb = total_bytes // 1024
        print(f"  {status}  Cartesia TTFB={ttfb}ms  total={total}ms  bytes={kb}KB")
        RESULTS.append(("Cartesia TTFB", ttfb, 400, status))
    except Exception as e:
        print(f"  ERR  Cartesia — {e}")
        RESULTS.append(("Cartesia TTFB", None, 400, "ERR"))


async def test_cartesia_backchannel():
    api_key = os.environ.get("CARTESIA_API_KEY")
    voice_id = os.environ.get("CARTESIA_VOICE_ID")
    if not api_key or not voice_id:
        print("  SKIP  Cartesia backchannel — keys not set")
        return

    print("  Testing Cartesia backchannel clip (short phrase)...")
    start = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.cartesia.ai/tts/bytes",
                headers={
                    "X-API-Key": api_key,
                    "Cartesia-Version": "2024-06-10",
                    "Content-Type": "application/json",
                },
                json={
                    "model_id": "sonic-2024-10-19",
                    "transcript": TEST_TEXT_SHORT,
                    "voice": {"mode": "id", "id": voice_id},
                    "output_format": {
                        "container": "raw",
                        "encoding": "pcm_s16le",
                        "sample_rate": 16000,
                    },
                },
            )
            elapsed = _ms(start)
            resp.raise_for_status()
            status = "OK" if elapsed < 300 else "SLOW"
            print(f"  {status}  Cartesia backchannel total={elapsed}ms  bytes={len(resp.content)//1024}KB")
            RESULTS.append(("Cartesia backchannel", elapsed, 300, status))
    except Exception as e:
        print(f"  ERR  Cartesia backchannel — {e}")
        RESULTS.append(("Cartesia backchannel", None, 300, "ERR"))


async def test_deepgram_connect():
    api_key = os.environ.get("DEEPGRAM_API_KEY")
    if not api_key:
        print("  SKIP  Deepgram — DEEPGRAM_API_KEY not set")
        return

    print("  Testing Deepgram API reachability...")
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://api.deepgram.com/v1/projects",
                headers={"Authorization": f"Token {api_key}"},
            )
            elapsed = _ms(start)
            if resp.status_code == 200:
                status = "OK" if elapsed < 500 else "SLOW"
                print(f"  {status}  Deepgram API ping={elapsed}ms")
                RESULTS.append(("Deepgram ping", elapsed, 500, status))
            else:
                print(f"  ERR  Deepgram — HTTP {resp.status_code}")
                RESULTS.append(("Deepgram ping", None, 500, "ERR"))
    except Exception as e:
        print(f"  ERR  Deepgram — {e}")
        RESULTS.append(("Deepgram ping", None, 500, "ERR"))


async def main():
    print("\n=== REI AGENT LATENCY TEST ===\n")

    await test_anthropic_ttft()
    await test_orpheus_ttfb()
    await test_cartesia_ttfb()
    await test_cartesia_backchannel()
    await test_deepgram_connect()

    print("\n=== SUMMARY ===\n")
    if not RESULTS:
        print("  No tests ran — check API keys in .env")
        return

    for name, ms, threshold, status in RESULTS:
        ms_str = f"{ms}ms" if ms is not None else "N/A"
        bar = "█" * min(40, (ms or 0) // 25)
        mark = "✓" if status == "OK" else ("✗" if status == "ERR" else "!")
        print(f"  {mark} {name:<28} {ms_str:<10} (target <{threshold}ms)  {bar}")

    ok = sum(1 for _, _, _, s in RESULTS if s == "OK")
    slow = sum(1 for _, _, _, s in RESULTS if s == "SLOW")
    err = sum(1 for _, _, _, s in RESULTS if s == "ERR")
    skip = sum(1 for _, _, _, s in RESULTS if s == "SKIP")
    print(f"\n  OK={ok}  SLOW={slow}  ERR={err}  SKIP={skip}\n")


if __name__ == "__main__":
    asyncio.run(main())
