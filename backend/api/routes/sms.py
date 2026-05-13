from fastapi import APIRouter, Query, HTTPException

router = APIRouter()


@router.get("/sms")
async def list_sms(
    lead_id: str = Query(default=""),
    limit: int = Query(default=100),
):
    from backend.lib.db import _get_client
    client = _get_client()
    query = client.table("sms_messages").select("*")
    if lead_id:
        query = query.eq("lead_id", lead_id)
    response = query.order("sent_at", desc=True).limit(limit).execute()
    messages = response.data
    return {"messages": messages, "count": len(messages)}


@router.post("/sms/send")
async def send_manual_sms(to: str, body: str, lead_id: str = ""):
    from backend.alerts.sms import send_sms
    success = send_sms(to=to, body=body)
    if not success:
        raise HTTPException(status_code=400, detail="SMS failed — check TCPA hours or SignalWire config")
    return {"success": True, "to": to}


@router.post("/sms/drip/{lead_id}")
async def trigger_drip(lead_id: str):
    from backend.lib.db import _get_client
    client = _get_client()

    response = (
        client.table("leads")
        .select("*, properties(*)")
        .eq("id", lead_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Lead not found")

    lead = response.data[0]
    prop = lead.get("properties", {})

    contacts = client.table("contacts").select("phone").eq(
        "property_id", prop.get("id", "")
    ).limit(1).execute()

    if not contacts.data:
        raise HTTPException(status_code=400, detail="No phone number for this lead")

    phone = contacts.data[0]["phone"]
    owner_name = lead.get("owner_name") or prop.get("owner_name", "")
    first_name = owner_name.strip().split()[0].title() if owner_name else "there"

    from backend.alerts.formatter import format_sms_drip_day1
    message = format_sms_drip_day1(prop, first_name)

    from backend.alerts.sms import send_drip_sms
    success = send_drip_sms(to=phone, body=message, lead_id=lead_id)

    return {"success": success, "lead_id": lead_id, "to": phone}
