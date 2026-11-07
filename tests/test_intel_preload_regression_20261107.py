def test_missing_disposition_does_not_break_intel_preload(monkeypatch):
    from backend.lib import db, intel_assembler

    class Response:
        def __init__(self, data):
            self.data = data

    class Query:
        def __init__(self, data):
            self.data = data

        def select(self, *_args):
            return self

        def eq(self, *_args):
            return self

        def limit(self, *_args):
            return self

        def execute(self):
            return Response(self.data)

    class Client:
        def table(self, name):
            if name == "leads":
                return Query([{"id": "lead-1", "property_id": None, "disposition": None}])
            return Query([])

    monkeypatch.setattr(db, "_get_client", lambda: Client())
    monkeypatch.setattr(db, "load_intel_packet", lambda _lead_id: None)
    monkeypatch.setattr(db, "save_intel_packet", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(db, "write_packet_event", lambda *_args, **_kwargs: None)

    packet = intel_assembler.assemble_intel_packet("lead-1")

    assert packet["seller_profile"]["disposition"]["value"] == ""
