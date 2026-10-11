import os
import sys
import types

os.environ.setdefault("SUPABASE_URL", "https://stub.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "stub-key")
os.environ.setdefault("OUTBOUND_ENABLED", "false")

if "signalwire" not in sys.modules:
    _sw = types.ModuleType("signalwire")
    _rest = types.ModuleType("signalwire.rest")
    _rest.Client = object
    _sw.rest = _rest
    sys.modules["signalwire"] = _sw
    sys.modules["signalwire.rest"] = _rest
