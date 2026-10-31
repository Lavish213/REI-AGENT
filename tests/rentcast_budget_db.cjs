const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { PGlite } = require('@electric-sql/pglite');
const tenant = '00000000-0000-0000-0000-000000000001';
(async () => {
  const db = new PGlite();
  try {
    await db.exec(`create role anon; create role authenticated; create role service_role;
      create table tenants(id uuid primary key);
      insert into tenants values ('${tenant}');
      create table properties(id uuid primary key, tenant_id uuid not null references tenants(id));
      create table comps(id uuid primary key default gen_random_uuid(), subject_property_id uuid references properties(id), tenant_id uuid);
      insert into properties values ('00000000-0000-0000-0000-000000000010', '${tenant}');`);
    const sql = fs.readFileSync(path.join(__dirname, '../supabase/migrations/20261031_rentcast_budget.sql'), 'utf8');
    await db.exec(sql);
    await db.exec(sql);
    const reserve = (cap) => db.query(`select reserve_rentcast_call($1, '00000000-0000-0000-0000-000000000010', $2) as id`, [tenant, cap]);
    const results = await Promise.all(Array.from({ length: 80 }, () => reserve(50)));
    const granted = results.filter((r) => r.rows[0].id !== null).length;
    assert.equal(granted, 50, 'exactly 50 reservations granted out of 80 concurrent attempts');
    assert.equal((await reserve(50)).rows[0].id, null, 'call 51 refused');
    assert.equal((await reserve(1000)).rows[0].id, null, 'a cap above 50 cannot widen the budget');
    await assert.rejects(db.query(`insert into rentcast_calls (tenant_id) values ($1)`, [tenant]), /hard ceiling/, 'direct insert past 50 rejected by trigger');
    const usage = (await db.query('select rentcast_usage() as u')).rows[0].u;
    assert.equal(usage.used, 50);
    assert.equal(usage.hard_cap, 50);
    assert.equal(usage.unfinished, 50);
    const first = results.find((r) => r.rows[0].id !== null).rows[0].id;
    assert.equal((await db.query(`select finish_rentcast_call($1, 200, 'ok') as ok`, [first])).rows[0].ok, true);
    assert.equal((await db.query(`select finish_rentcast_call($1, 200, 'ok') as ok`, [first])).rows[0].ok, false, 'a finished call cannot be finished again');
    await assert.rejects(db.query(`select finish_rentcast_call($1, 200, 'bogus')`, [first]), /Invalid RentCast outcome/);
    assert.equal((await db.query('select rentcast_usage() as u')).rows[0].u.used, 50, 'finishing a call never frees budget');
    await db.exec(`update rentcast_calls set reserved_at = clock_timestamp() - interval '32 days' where id in (select id from rentcast_calls order by id limit 5)`);
    const reopened = await Promise.all(Array.from({ length: 10 }, () => reserve(50)));
    assert.equal(reopened.filter((r) => r.rows[0].id !== null).length, 5, 'only calls older than 31 days free up slots');
    const lowCap = new PGlite();
    await lowCap.exec(`create role anon; create role authenticated; create role service_role;
      create table tenants(id uuid primary key); insert into tenants values ('${tenant}');
      create table properties(id uuid primary key, tenant_id uuid not null references tenants(id));
      create table comps(id uuid primary key default gen_random_uuid(), subject_property_id uuid references properties(id), tenant_id uuid);`);
    await lowCap.exec(sql);
    const lowGrants = await Promise.all(Array.from({ length: 20 }, () => lowCap.query(`select reserve_rentcast_call($1, null, 10) as id`, [tenant])));
    assert.equal(lowGrants.filter((r) => r.rows[0].id !== null).length, 10, 'a lower configured cap is honored');
    assert.equal((await lowCap.query(`select reserve_rentcast_call($1, null, -5) as id`, [tenant])).rows[0].id, null, 'a negative cap grants nothing');
    await lowCap.close();
    for (const role of ['anon', 'authenticated']) {
      const allowed = (await db.query(`select has_function_privilege('${role}', 'reserve_rentcast_call(uuid,uuid,integer)', 'EXECUTE') as a`)).rows[0].a;
      assert.equal(allowed, false, role + ' cannot reserve');
    }
    console.log('rentcast budget database checks passed');
  } finally {
    await db.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
