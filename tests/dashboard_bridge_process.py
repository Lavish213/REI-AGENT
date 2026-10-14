import asyncio
import json
import os
import sys
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from backend.karpathys import client, emitter, outbox
from backend.lib import db


async def main():
    if urlsplit(client._KARPATHYS_URL).hostname not in {'127.0.0.1', 'localhost'}:
        raise RuntimeError('Contract helper only permits loopback receivers')
    phase, result_path = sys.argv[1:3]
    sid, lead_id = os.environ['CONTRACT_CALL_SID'], os.environ['CONTRACT_LEAD_ID']
    if phase == 'stage':
        assert await emitter.emit_turn_completed(sid, 'user', 'Please call tomorrow', turn_index=0)
        assert await emitter.emit_call_created(sid, {'lead': {'id': lead_id, 'owner_first_name': 'Synthetic seller'}})
        assert await emitter.emit_transcript_completed(sid, None, lead_id, 2, [{'speaker': 'SELLER', 'text': 'Please call tomorrow'}, {'speaker': 'SOPHIA', 'text': 'I can request a callback'}])
        assert await emitter.emit_call_completed(sid, 'WARM', 2, 60)
        assert await emitter.emit_call_ended(sid)
    if phase == 'business':
        from backend.karpathys.business import publish_business
        bob = os.environ['BOB_REPO']
        code = "import runpy,json,sys;from backend.call_planner.brief_generator import generate_call_brief;p=json.load(sys.stdin);r=runpy.run_path('tests/test_valuation.py')['request']();r['subject']['property_id']='property-1';lead={'id':p['lead_id'],'property_id':'property-1'};prop={'id':'property-1','county':'San Joaquin','state':'CA'};json.dump(generate_call_brief(p['lead_id'],lead,prop,{'valuation_inputs':r},{}).to_dict(),sys.stdout)"
        run = subprocess.run([sys.executable, '-c', code], cwd=bob, input=json.dumps({'lead_id': lead_id}), capture_output=True, text=True, timeout=30)
        if run.returncode:
            raise RuntimeError(run.stderr[-1000:])
        report = json.loads(run.stdout)
        canonical = {'id': lead_id, 'property_id': 'property-1', 'properties': {'id': 'property-1', 'address': '123 Synthetic Street', 'apn': '00123456'}, 'call_brief': report, 'appointment_at': '2099-01-01T22:00:00+00:00', 'appointment_status': 'confirmed'}
        db.dashboard_business_source = lambda lead: {'lead': canonical, 'offers': [{'id': 'offer-1', 'lead_id': lead_id, 'offer_status': 'draft', 'offer_amount': 25000000, 'repair_estimate': 2000000}]}
        assert await publish_business(sid, lead_id)
        assert await publish_business(sid, lead_id)
    result = await outbox.recover_events(20)
    health = db.dashboard_event_journal_health()
    Path(result_path).write_text(json.dumps({'recovery': result, 'health': health}))


if __name__ == '__main__':
    asyncio.run(main())
