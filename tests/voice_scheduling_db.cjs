const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { PGlite } = require('@electric-sql/pglite')
const { btree_gist } = require('@electric-sql/pglite/contrib/btree_gist')

async function main() {
  const db = new PGlite({ extensions: { btree_gist } })
  try {
    await db.exec(`
      create role anon;
      create role authenticated;
      create role service_role bypassrls;
      create table leads (
        id uuid primary key, appointment_at timestamptz, stage text,
        updated_at timestamptz, opted_out boolean default false,
        callback_scheduled_at timestamptz
      );
      create table followups (
        id uuid primary key default gen_random_uuid(), lead_id uuid references leads(id),
        followup_type text, state text default 'pending', priority text,
        scheduled_at timestamptz, created_at timestamptz default now()
      );
      insert into leads(id) values ('00000000-0000-0000-0000-000000000001'), ('00000000-0000-0000-0000-000000000002');
    `)
    await db.exec(fs.readFileSync(path.join(__dirname, '../supabase/migrations/20260911_tenant_and_suppression.sql'), 'utf8'))
    await db.exec(fs.readFileSync(path.join(__dirname, '../supabase/migrations/20261011_voice_scheduling.sql'), 'utf8'))
    await db.query("insert into dnc_list(tenant_id, phone, reason) values ($1, '+15555550100', 'seller_request')", ['00000000-0000-0000-0000-000000000001'])
    const evidencePermissions = await db.query("select has_table_privilege('service_role', 'suppression_events', 'UPDATE') as update, has_table_privilege('service_role', 'suppression_events', 'DELETE') as delete")
    assert.equal(evidencePermissions.rows[0].update, false)
    assert.equal(evidencePermissions.rows[0].delete, false)
    await db.exec("insert into walkthrough_availability values ('2030-10-12T17:00:00Z', '2030-10-12T18:00:00Z')")
    const book = id => db.query("select reserve_voice_appointment($1, '2030-10-12T17:00:00Z', '123 Main St') as id", [id])
    const first = await book('00000000-0000-0000-0000-000000000001')
    const repeated = await book('00000000-0000-0000-0000-000000000001')
    assert.equal(first.rows[0].id, repeated.rows[0].id)
    await assert.rejects(book('00000000-0000-0000-0000-000000000002'), /exclusion|conflict/)
    await assert.rejects(db.query("select reserve_voice_appointment($1, '2030-10-13T17:00:00Z', '123 Main St')", ['00000000-0000-0000-0000-000000000002']), /availability/)
    await db.query("update voice_appointments set status = 'cancelled' where id = $1", [first.rows[0].id])
    const rebooked = await book('00000000-0000-0000-0000-000000000001')
    assert.notEqual(rebooked.rows[0].id, first.rows[0].id)
    const repeatedBookings = await Promise.all(Array.from({ length: 100 }, () => book('00000000-0000-0000-0000-000000000001')))
    assert(repeatedBookings.every(result => result.rows[0].id === rebooked.rows[0].id))
    await db.exec("insert into walkthrough_availability values ('2030-10-12T18:00:00Z', '2030-10-12T19:00:00Z')")
    await db.query("select reserve_voice_appointment($1, '2030-10-12T18:00:00Z', '101 Test Ave')", ['00000000-0000-0000-0000-000000000002'])
    await db.exec("update leads set callback_scheduled_at = now() - interval '1 minute'")
    const callbacks = await db.query('select * from claim_due_callbacks(3)')
    assert.equal(callbacks.rows.length, 2)
    assert.equal((await db.query('select * from claim_due_callbacks(3)')).rows.length, 0)
    await db.exec("update leads set callback_claimed_until = now() - interval '1 minute'")
    const claimBatches = await Promise.all(Array.from({ length: 100 }, () => db.query('select * from claim_due_callbacks(3)')))
    const claimedIds = claimBatches.flatMap(batch => batch.rows.map(row => row.id))
    assert.equal(claimedIds.length, 2)
    assert.equal(new Set(claimedIds).size, 2)
    await db.exec("update leads set callback_claimed_until = null, opted_out = true")
    assert.equal((await db.query('select * from claim_due_callbacks(3)')).rows.length, 0)
    await db.exec("update leads set opted_out = false")
    await db.exec(`
      insert into followups(lead_id, followup_type, priority, scheduled_at) values
      ('00000000-0000-0000-0000-000000000001', 'call', 'high', now() - interval '1 minute'),
      ('00000000-0000-0000-0000-000000000001', 'call', 'low', now() + interval '1 day'),
      ('00000000-0000-0000-0000-000000000001', 'sms', 'high', now() - interval '1 minute');
    `)
    assert.equal((await db.query('select * from claim_due_call_followups(5)')).rows.length, 1)
    assert.equal((await db.query('select * from claim_due_call_followups(5)')).rows.length, 0)
    await db.exec('set role anon')
    await assert.rejects(db.query('select * from voice_appointments'), /permission/)
    await assert.rejects(db.query('select * from claim_due_callbacks(3)'), /permission/)
    await db.exec('reset role')
    process.stdout.write('PASS: reservation idempotency, collision rejection, availability enforcement, callback claims, due/type filtering, and anonymous denial\n')
  } finally { await db.close() }
}

main().catch(error => { process.stderr.write(error.stack + '\n'); process.exitCode = 1 })
