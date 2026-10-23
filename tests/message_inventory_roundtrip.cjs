const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const http=require('node:http');
const {spawn}=require('node:child_process');
const {PGlite}=require('@electric-sql/pglite');
(async()=>{
 const db=new PGlite();const root=fs.mkdtempSync(path.join(os.tmpdir(),'message-inventory-'));let server;
 try{
  await db.exec(`create role anon;create role authenticated;create role service_role;create table leads(id uuid primary key,tenant_id uuid,owner_email text,email_paused boolean default false,opted_out boolean default false,updated_at timestamptz default now());`);
  await db.exec(fs.readFileSync(path.join(__dirname,'../supabase/migrations/20261020_provider_delivery_receipts.sql'),'utf8'));
  const tenant='00000000-0000-0000-0000-000000000001',lead='00000000-0000-0000-0000-000000000020';
  await db.query("insert into leads(id,tenant_id,owner_email) values ($1,$2,'seller@example.invalid')",[lead,tenant]);
  let sends=0;
  server=http.createServer(async(req,res)=>{
   try{
    let raw='';for await(const chunk of req)raw+=chunk;
    if(req.url==='/send'){
     sends++;const data=JSON.parse(raw);assert.equal(data.personalizations[0].to[0].email,'seller@example.invalid');assert.match(data.personalizations[0].custom_args.communication_intent,/^[a-f0-9]{64}$/);
     res.writeHead(202,{'x-message-id':'fixture-api-receipt'});res.end();return;
    }
    res.setHeader('content-type','application/json');
    if(req.url==='/rpc'){
     const p=JSON.parse(raw);const result=await db.query('select apply_delivery_event($1,$2,$3,$4,$5) as id',[p.p_tenant,p.p_id,p.p_intent,p.p_lead,p.p_payload]);res.end(JSON.stringify(result.rows[0].id));return;
    }
    if(req.url==='/messages'){
     const result=await db.query('select * from provider_delivery_messages where tenant_id=$1 order by updated_at desc limit 100',[tenant]);res.end(JSON.stringify(result.rows));return;
    }
    res.writeHead(404);res.end('{}');
   }catch(error){res.writeHead(500);res.end(JSON.stringify({error:error.message}));}
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const source=String.raw`
import asyncio,json,os
from pathlib import Path
from types import SimpleNamespace
import httpx
from fastapi import FastAPI
from backend.alerts.email import send_email
from backend.alerts.delivery import accept_events
from backend.api.routes.bob import router
from backend.api.security import OperatorAuthentication
from backend.lib import db
base=os.environ['FIXTURE_HTTP']
native=httpx.post

def post(url,**kwargs):
    if url=='https://api.sendgrid.com/v3/mail/send':
        kwargs.pop('headers',None)
        return native(base+'/send',**kwargs)
    return native(url,**kwargs)
httpx.post=post
class Client:
    def rpc(self,name,params):
        assert name=='apply_delivery_event'
        def execute():
            response=native(base+'/rpc',json=params,timeout=10)
            response.raise_for_status()
            return SimpleNamespace(data=response.json())
        return SimpleNamespace(execute=execute)
    def table(self,name):
        assert name=='provider_delivery_messages'
        class Query:
            def select(self,*args):return self
            def eq(self,*args):return self
            def order(self,*args,**kwargs):return self
            def limit(self,*args):return self
            def execute(self):
                response=httpx.get(base+'/messages',timeout=10)
                response.raise_for_status()
                return SimpleNamespace(data=response.json())
        return Query()
db._get_client=Client
lead='00000000-0000-0000-0000-000000000020'
assert send_email('seller@example.invalid','Fixture','AI assistant fixture message',lead)
assert send_email('seller@example.invalid','Fixture','AI assistant fixture message',lead)
assert db.stage_message_acceptances()['staged']==1
assert db.recover_delivery_events()['synced']==1
app=FastAPI();app.add_middleware(OperatorAuthentication);app.include_router(router,prefix='/api')
async def read():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.get('/api/operations/delivery')).status_code==401
        result=await client.get('/api/operations/delivery',headers={'X-Source-Command-Secret':os.environ['SOURCE_COMMAND_SECRET']})
        assert result.status_code==200,result.text
        return result.json()
first=asyncio.run(read())
assert first['inventory']['accepted']==1 and first['messages'][0]['delivery_status']=='pending'
identity=first['messages'][0]['intent_id']
accept_events('email',[{'event':'delivered','email':'seller@example.invalid','timestamp':1792700000,'sg_event_id':'fixture-delivered','sg_message_id':'different-internal-webhook-id','communication_intent':identity}])
assert db.recover_delivery_events()['synced']==1
second=asyncio.run(read())
assert second['messages'][0]['delivery_status']=='delivered'
assert second['inventory']['accepted']==1
Path(os.environ['FIXTURE_OUTPUT']).write_text(json.dumps({'first':first,'second':second}))
`;
  const child=spawn(process.env.PYTHON||'python',['-c',source],{cwd:path.join(__dirname,'..'),env:{...process.env,PYTHONPATH:path.join(__dirname,'..'),FIXTURE_HTTP:`http://127.0.0.1:${server.address().port}`,FIXTURE_OUTPUT:path.join(root,'result.json'),COMMUNICATION_JOURNAL_PATH:path.join(root,'communications.sqlite3'),WORKFLOW_JOURNAL_PATH:path.join(root,'workflows.sqlite3'),CONTACT_SUPPRESSION_PATH:path.join(root,'suppression.sqlite3'),TENANT_ID:tenant,OUTBOUND_ENABLED:'true',ENABLE_BACKGROUND_JOBS:'false',SENDGRID_API_KEY:'synthetic-fixture-only',SOURCE_COMMAND_SECRET:'synthetic-command-secret-'.repeat(2)}});
  let output='';child.stdout.on('data',chunk=>output+=chunk);child.stderr.on('data',chunk=>output+=chunk);
  const code=await new Promise(resolve=>child.on('close',resolve));assert.equal(code,0,output);
  assert.equal(sends,1);const data=JSON.parse(fs.readFileSync(path.join(root,'result.json'),'utf8'));
  assert.equal(data.first.messages.length,1);assert.equal(data.second.messages[0].delivery_status,'delivered');
  console.log('PASS: fixture HTTP provider acceptance -> durable SQLite inventory -> actual PostgreSQL projection -> authenticated source read; absent callback stays pending, callback changes to delivered, duplicate send prevented. No live provider contacted.');
 }finally{if(server)await new Promise(resolve=>server.close(resolve));await db.close();fs.rmSync(root,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exitCode=1});
