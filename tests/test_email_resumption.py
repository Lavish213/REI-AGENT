from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.lib import db

TENANT='00000000-0000-0000-0000-000000000001'
LEAD='00000000-0000-0000-0000-000000000020'


@pytest.fixture
def campaign(tmp_path, monkeypatch):
    monkeypatch.setenv('TENANT_ID',TENANT)
    monkeypatch.setenv('CONTACT_SUPPRESSION_PATH', str(tmp_path / 'contact.sqlite3'))
    monkeypatch.setenv('WORKFLOW_JOURNAL_PATH',str(tmp_path/'workflow.sqlite3'))
    monkeypatch.setenv('COMMUNICATION_JOURNAL_PATH',str(tmp_path/'messages.sqlite3'))
    monkeypatch.setattr(db,'get_lead_with_property',lambda _: {'tenant_id':TENANT,'owner_email':'seller@example.invalid'})
    token=db.register_email_thread(LEAD,'seller@example.invalid')
    calls=[]
    state={'outage':False,'during_resume':None}
    def rpc(name, params):
        def execute():
            calls.append((name,params))
            if state['outage']:
                raise RuntimeError('offline or acknowledgement lost')
            if name=='resume_reviewed_email' and state['during_resume']:
                state['during_resume']()
                state['during_resume']=None
            return SimpleNamespace(data=params['p_id'])
        return SimpleNamespace(execute=execute)
    monkeypatch.setattr(db,'_get_client',lambda:SimpleNamespace(rpc=rpc))
    def reply(identity='reply', text='Tuesday works', apply=True):
        result=db.stage_inbound_email({'event_id':identity,'thread_token':token,'sender':'seller@example.invalid','sender_verified':True,'text':text})
        if apply:
            db.recover_inbound_email()
        return result
    def review():
        snapshot=db.list_email_reply_holds()['items'][0]
        return {'request_id':str(uuid4()),'actor_id':str(uuid4()),'reason':'Reviewed seller reply and existing follow-up sequence','fingerprint':snapshot['fingerprint']}
    return reply,review,calls,state


def test_reviewed_normal_reply_resumes_once_and_new_reply_reholds(campaign):
    reply,review,calls,_=campaign
    reply()
    body=review()
    assert db.local_lead_reply_hold(LEAD)['email_paused']
    assert db.review_email_resumption(LEAD,body)['state']=='applied'
    assert db.review_email_resumption(LEAD,body)['state']=='applied'
    assert len([call for call in calls if call[0]=='resume_reviewed_email'])==1
    assert db.local_lead_reply_hold(LEAD)=={'email_paused':False,'opted_out':False}
    assert db.list_email_reply_holds()['items']==[]
    reply('new','Wednesday instead')
    assert db.local_lead_reply_hold(LEAD)['email_paused']
    assert db.review_email_resumption(LEAD,body)['state']=='applied'
    assert db.local_lead_reply_hold(LEAD)['email_paused']
    assert db.review_email_resumption(LEAD,review())['state']=='applied'
    assert not db.local_lead_reply_hold(LEAD)['email_paused']


def test_queued_resumption_survives_outage_and_recovers_same_identity(campaign):
    reply,review,calls,state=campaign
    reply()
    body=review()
    state['outage']=True
    assert db.review_email_resumption(LEAD,body)['state']=='pending'
    assert db.local_lead_reply_hold(LEAD)['email_paused']
    state['outage']=False
    db.recover_email_resumptions()
    assert not db.local_lead_reply_hold(LEAD)['email_paused']
    resumes=[params for name,params in calls if name=='resume_reviewed_email']
    assert len(resumes)==2 and resumes[0]==resumes[1]
    assert resumes[0]['p_actor']==body['actor_id']


@pytest.mark.parametrize('text',['STOP','\n stop\t','unsubscribe','remove me','do not contact me'])
def test_stop_never_gets_a_resumption(campaign,text):
    reply,review,calls,_=campaign
    reply(text=text)
    with pytest.raises(ValueError,match='STOP'):
        db.review_email_resumption(LEAD,review())
    assert db.local_lead_reply_hold(LEAD)['opted_out']
    assert not [call for call in calls if call[0]=='resume_reviewed_email']


@pytest.mark.parametrize('text',['STOP','A new ordinary reply'])
def test_new_reply_after_source_receipt_prevents_local_release(campaign,text):
    reply,review,_,state=campaign
    reply()
    body=review()
    state['during_resume']=lambda:reply('late-reply',text,apply=False)
    assert db.review_email_resumption(LEAD,body)['state']=='requires_review'
    assert db.local_lead_reply_hold(LEAD)=={'email_paused':True,'opted_out':db.email_reply_is_stop(text)}
    assert db.local_reply_email_blocked('seller@example.invalid') is db.email_reply_is_stop(text)
    assert db.workflow_journal_health()['requires_review']==1


def test_stale_unpersisted_and_cross_tenant_reviews_are_denied(campaign,monkeypatch):
    reply,review,_,_=campaign
    reply()
    stale=review()
    reply('new',apply=False)
    with pytest.raises(ValueError):
        db.review_email_resumption(LEAD,stale)
    current=review()
    with pytest.raises(ValueError):
        db.review_email_resumption(LEAD,current)
    db.recover_inbound_email()
    current=review()
    monkeypatch.setenv('TENANT_ID','00000000-0000-0000-0000-000000000002')
    assert db.list_email_reply_holds()['items']==[]
    with pytest.raises(ValueError):
        db.review_email_resumption(LEAD,current)


def test_conflicting_replay_and_suppressed_email_cannot_resume(campaign):
    reply,review,_,_=campaign
    reply()
    body=review()
    db.suppress_email_address('seller@example.invalid')
    assert db.review_email_resumption(LEAD,body)['state']=='requires_review'
    assert db.local_lead_reply_hold(LEAD)['email_paused']
    with pytest.raises(ValueError,match='Conflicting'):
        db.review_email_resumption(LEAD,{**body,'reason':'Different review cannot reuse the identity'})


def test_phone_stop_blocks_email_and_resumption_during_database_outage(campaign,monkeypatch):
    from backend.alerts import email
    reply,review,_,_=campaign
    reply()
    body=review()
    db.stage_contact_suppression(TENANT,'+12095550123',LEAD,'seller_request')
    assert db.local_lead_reply_hold(LEAD)['opted_out']
    assert db.list_email_reply_holds()['items'][0]['can_resume'] is False
    assert db.review_email_resumption(LEAD,body)['state']=='requires_review'
    monkeypatch.setenv('OUTBOUND_ENABLED','true')
    monkeypatch.setenv('SENDGRID_API_KEY','test-only')
    provider=__import__('unittest.mock',fromlist=['MagicMock']).MagicMock()
    monkeypatch.setattr('httpx.post',provider)
    assert not email.send_email('seller@example.invalid','Follow up','Body',LEAD)
    provider.assert_not_called()
