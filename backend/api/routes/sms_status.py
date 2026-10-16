import asyncio
import sqlite3

from fastapi import APIRouter, Request, Response
from loguru import logger

from backend.alerts.delivery import accept_events

router = APIRouter()


@router.post('/voice/sms-status')
async def sms_status_callback(request: Request) -> Response:
    try:
        form = await request.form()
        await asyncio.to_thread(accept_events, 'sms', [dict(form)])
    except (ValueError, TypeError):
        return Response(status_code=422)
    except (RuntimeError, OSError, sqlite3.Error) as error:
        logger.warning('sms_status_not_saved type={}', type(error).__name__)
        return Response(status_code=503)
    return Response(status_code=204)
