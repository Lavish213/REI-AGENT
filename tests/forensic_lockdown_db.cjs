const assert = require('node:assert/strict');
const fs = require('node:fs');
const { PGlite } = require('@electric-sql/pglite');
(async () => {
 const db = new PGlite();
 try {
  await db.exec(`create role anon; create role authenticated; create role service_role;
   create table tenants(id uuid primary key);
   create table properties(id uuid primary key,tenant_id uuid not null references tenants(id),lead_id uuid);
   create table leads(id uuid primary key default gen_random_uuid(),tenant_id uuid references tenants(id),property_id uuid references properties(id),stage text,callable boolean);
   insert into tenants values ('00000000-0000-0000-0000-000000000001'),('00000000-0000-0000-0000-000000000002');
   insert into properties(id,tenant_id) values ('00000000-0000-0000-0000-000000000010','00000000-0000-0000-0000-000000000001');`);
  const sql = fs.readFileSync(require('node:path').join(__dirname,'../supabase/migrations/20261015_forensic_lockdown.sql'),'utf8');
  await db.exec(sql); await db.exec(sql);
  const query = () => db.query("select create_canonical_lead('00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000010') as id");
  const first = (await query()).rows[0].id;
  const results = await Promise.all(Array.from({length:100}, query));
  assert(results.every(r => r.rows[0].id === first));
  assert.deepEqual((await db.query('select callable,stage from leads')).rows, [{callable:false,stage:'new'}]);
  await assert.rejects(db.query("select create_canonical_lead('00000000-0000-0000-0000-000000000002','00000000-0000-0000-0000-000000000010')"), /property/i);
  await assert.rejects(db.query("update properties set tenant_id='00000000-0000-0000-0000-000000000002'"), /immutable/i);
  const rights = (await db.query("select has_function_privilege('anon','create_canonical_lead(uuid,uuid)','EXECUTE') as allowed")).rows[0];
  assert.equal(rights.allowed,false);
  console.log('Lockdown migration: repeat apply, 100 replays, tenant isolation and function permissions passed');
 } finally { await db.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
