# Sophia Voice Pipeline Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix six root-cause bugs in `backend/voice/agent.py` so Sophia correctly hears callers, speaks her greeting, executes tools, and routes audio through SignalWire.

**Architecture:** All changes are confined to `backend/voice/agent.py`. Each fix is self-contained: message seeding, stream_sid capture loop, tools wiring, sample rate explicitness, and dead code removal. No new files needed.

**Tech Stack:** Python 3.11, Pipecat 1.1.0, FastAPI WebSocket, SignalWire (Twilio-compatible streaming), Anthropic Claude, Deepgram STT, Cartesia TTS.

---

## Files

- Modify: `backend/voice/agent.py` (all six tasks touch only this file)

---

### Task 1: Fix stream_sid capture — loop until `start` event

**Problem:** Code reads exactly one WebSocket message and checks if it's `start`. SignalWire sends a `connected` event first, then `start`. The single read consumes `connected`, the `start` check fails, and `stream_sid` falls back to `call_sid`. Every outbound media JSON has the wrong `streamSid` — SignalWire discards all audio.

**Files:**
- Modify: `backend/voice/agent.py:60-68`

- [ ] **Step 1: Replace single-read with loop that waits for `start`**

Replace lines 60–68 in `backend/voice/agent.py`:

```python
    stream_sid = call_sid
    try:
        for _ in range(5):
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            msg = json.loads(raw)
            if msg.get("event") == "start":
                stream_sid = msg.get("streamSid", call_sid)
                logger.info("stream started stream_sid={}", stream_sid)
                break
            logger.debug("pre-start event={}", msg.get("event"))
    except asyncio.TimeoutError:
        logger.warning("timed out waiting for start event using call_sid as fallback")
    except Exception as e:
        logger.warning("could not read start event error={}", str(e))
```

- [ ] **Step 2: Verify change looks correct in file**

Run: `grep -n "stream_sid\|for _\|wait_for\|pre-start" /Users/angelowashington/rei-agent/backend/voice/agent.py`

Expected output includes lines with `for _ in range(5)`, `wait_for`, and `pre-start event`.

- [ ] **Step 3: Commit**

```bash
cd /Users/angelowashington/rei-agent
git add backend/voice/agent.py
git commit -m "fix(voice): loop waiting for SignalWire start event to get correct stream_sid"
```

---

### Task 2: Fix opening greeting — valid message seed

**Problem:** `messages` list has `role: system` + `role: assistant` with no user turn. The Anthropic adapter extracts `system` into a separate param; the remaining array is a single-assistant-turn message array — invalid for Anthropic API. The LLM call errors on connect and Sophia never speaks.

**Fix:** Seed context with only a synthetic `[call started]` user turn. When `on_client_connected` fires and queues `LLMContextFrame`, Claude generates Sophia's greeting from the system prompt.

**Files:**
- Modify: `backend/voice/agent.py:119-128`

- [ ] **Step 1: Replace message seed**

Replace lines 119–128 in `backend/voice/agent.py`:

```python
    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": "[call started]",
        },
    ]
```

- [ ] **Step 2: Verify messages no longer has assistant turn**

Run: `grep -A8 "messages = \[" /Users/angelowashington/rei-agent/backend/voice/agent.py | head -12`

Expected: shows `role: system` and `role: user` — NO `role: assistant`.

- [ ] **Step 3: Commit**

```bash
cd /Users/angelowashington/rei-agent
git add backend/voice/agent.py
git commit -m "fix(voice): seed context with user turn so Anthropic API accepts first LLM call"
```

---

### Task 3: Fix tools — build ToolsSchema and register handlers

**Problem:** `tools=SOPHIA_TOOLS` is passed as a kwarg to `AnthropicLLMService` where it propagates up the `**kwargs` chain to `BaseObject` and is silently discarded. Claude has no tool definitions. `llm.register_function()` is never called so even if Claude tried to call a tool, no handler would execute.

**Fix:**
1. Convert each dict in `SOPHIA_TOOLS` to `FunctionSchema`, wrap in `ToolsSchema`, pass to `LLMContext`.
2. Register async handlers via `llm.register_function()` that call `execute_tool()` and return the result via `params.result_callback`.

**Files:**
- Modify: `backend/voice/agent.py` (imports, tool wiring section, `run_sophia_agent`)

- [ ] **Step 1: Add required imports at top of file**

After the existing imports block (after line 30), add:

```python
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams

from backend.voice.tools import SOPHIA_TOOLS, execute_tool
```

Note: `execute_tool` is already imported via `from backend.voice.tools import SOPHIA_TOOLS` — change that line to also import `execute_tool`.

The full updated import line:

```python
from backend.voice.tools import SOPHIA_TOOLS, execute_tool
```

- [ ] **Step 2: Add `_build_tools_schema()` helper function**

Add this function after `_load_system_prompt` (after line 50 in the original file, before `run_sophia_agent`):

```python
def _build_tools_schema() -> ToolsSchema:
    schemas = []
    for tool in SOPHIA_TOOLS:
        props = tool["input_schema"]["properties"]
        required = tool["input_schema"].get("required", [])
        schemas.append(FunctionSchema(
            name=tool["name"],
            description=tool["description"],
            properties=props,
            required=required,
        ))
    return ToolsSchema(standard_tools=schemas)
```

- [ ] **Step 3: Add `_make_tool_handler()` factory function**

Add immediately after `_build_tools_schema`:

```python
def _make_tool_handler(tool_name: str):
    async def handler(params: FunctionCallParams) -> None:
        result = execute_tool(tool_name, dict(params.arguments))
        await params.result_callback(result)
    return handler
```

- [ ] **Step 4: Remove `tools=SOPHIA_TOOLS` from `AnthropicLLMService` constructor**

In `run_sophia_agent`, find:

```python
    llm = AnthropicLLMService(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        settings=AnthropicLLMService.Settings(
            model=os.environ.get("LLM_MODEL", "claude-sonnet-4-6"),
        ),
        tools=SOPHIA_TOOLS,
    )
```

Replace with:

```python
    llm = AnthropicLLMService(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        settings=AnthropicLLMService.Settings(
            model=os.environ.get("LLM_MODEL", "claude-sonnet-4-6"),
        ),
    )

    for tool in SOPHIA_TOOLS:
        llm.register_function(tool["name"], _make_tool_handler(tool["name"]))
```

- [ ] **Step 5: Pass `ToolsSchema` to `LLMContext`**

Find:

```python
    context = LLMContext(messages=messages)
```

Replace with:

```python
    context = LLMContext(messages=messages, tools=_build_tools_schema())
```

- [ ] **Step 6: Verify tools are wired**

Run: `grep -n "register_function\|ToolsSchema\|_build_tools\|_make_tool" /Users/angelowashington/rei-agent/backend/voice/agent.py`

Expected: lines showing `_build_tools_schema`, `_make_tool_handler`, `register_function` for each tool, and `LLMContext(messages=messages, tools=`.

- [ ] **Step 7: Commit**

```bash
cd /Users/angelowashington/rei-agent
git add backend/voice/agent.py
git commit -m "fix(voice): wire SOPHIA_TOOLS to LLMContext and register function handlers on llm"
```

---

### Task 4: Set explicit `audio_in_sample_rate`

**Problem:** `TwilioFrameSerializer` resamples inbound 8kHz mulaw to whatever `frame.audio_in_sample_rate` is. That rate comes from `TransportParams.audio_in_sample_rate`, which defaults to `None`, letting Pipecat use its global default. If that default doesn't match what Deepgram expects, STT receives garbled audio and transcripts are empty.

**Fix:** Explicitly set `audio_in_sample_rate=16000` (Deepgram nova-2 optimal rate). The serializer will resample mulaw 8kHz → PCM 16kHz.

**Files:**
- Modify: `backend/voice/agent.py` (FastAPIWebsocketParams block)

- [ ] **Step 1: Add `audio_in_sample_rate` to transport params**

Find:

```python
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=TwilioFrameSerializer(
```

Replace with:

```python
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_in_sample_rate=16000,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=TwilioFrameSerializer(
```

- [ ] **Step 2: Verify**

Run: `grep -n "audio_in_sample_rate" /Users/angelowashington/rei-agent/backend/voice/agent.py`

Expected: one line showing `audio_in_sample_rate=16000`.

- [ ] **Step 3: Commit**

```bash
cd /Users/angelowashington/rei-agent
git add backend/voice/agent.py
git commit -m "fix(voice): set audio_in_sample_rate=16000 for Deepgram nova-2 compatibility"
```

---

### Task 5: Clean up dead code and unused imports

**Problem:** `FrameLogger`, `compress_context`, `transcript_turns`, and `owner_first` are imported/defined but never used. They add noise and suggest the pipeline isn't fully wired.

**Files:**
- Modify: `backend/voice/agent.py`

- [ ] **Step 1: Remove unused imports**

Find and delete these two import lines:

```python
from pipecat.processors.logger import FrameLogger
```

```python
from backend.voice.context import compress_context
```

- [ ] **Step 2: Remove unused variables in `run_sophia_agent`**

Find and delete:

```python
    owner_first = call_context.get("owner_first_name") or "there"
```

Find and delete:

```python
    transcript_turns = []
```

- [ ] **Step 3: Verify no remaining references**

Run: `grep -n "FrameLogger\|compress_context\|transcript_turns\|owner_first" /Users/angelowashington/rei-agent/backend/voice/agent.py`

Expected: no output.

- [ ] **Step 4: Commit**

```bash
cd /Users/angelowashington/rei-agent
git add backend/voice/agent.py
git commit -m "chore(voice): remove unused imports and dead variables"
```

---

### Task 6: Final verification — read and confirm complete file

- [ ] **Step 1: Read full agent.py and confirm all fixes present**

Run: `cat -n /Users/angelowashington/rei-agent/backend/voice/agent.py`

Confirm all of the following:
- [ ] `for _ in range(5):` loop for stream_sid (Task 1)
- [ ] Messages has `role: user` / `[call started]`, no `role: assistant` seed (Task 2)
- [ ] `_build_tools_schema()` function exists (Task 3)
- [ ] `_make_tool_handler()` function exists (Task 3)
- [ ] `llm.register_function(...)` called for each of 3 tools (Task 3)
- [ ] `LLMContext(messages=messages, tools=_build_tools_schema())` (Task 3)
- [ ] `audio_in_sample_rate=16000` in FastAPIWebsocketParams (Task 4)
- [ ] No `FrameLogger`, `compress_context`, `transcript_turns`, `owner_first` (Task 5)
- [ ] `tools=SOPHIA_TOOLS` no longer on `AnthropicLLMService(...)` (Task 3)

- [ ] **Step 2: Check no syntax errors**

Run: `python3 -c "import ast; ast.parse(open('/Users/angelowashington/rei-agent/backend/voice/agent.py').read()); print('syntax ok')" `

Expected: `syntax ok`
