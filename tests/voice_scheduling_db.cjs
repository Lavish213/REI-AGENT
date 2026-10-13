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
    await db.exec(fs.readFileSync(path.join(__dirname, '../supabase/migrations/20261012_call_recovery.sql'), 'utf8'))
    await db.query("insert into dnc_list(tenant_id, phone, reason) values ($1, '+15555550100', 'seller_request')", ['00000000-0000-0000-0000-000000000001'])
    const evidencePermissions = await db.query("select has_table_privilege('service_role', 'suppression_events', 'UPDATE') as update, has_table_privilege('service_role', 'suppression_events', 'DELETE') as delete")
    assert.equal(evidencePermissions.rows[0].update, false)
    assert.equal(evidencePermissions.rows[0].delete, false)
    await db.exec('set role service_role')
    await db.query("insert into suppression_events(id,tenant_id,contact_point,method,source) values ($1,$2,$3,'sms_stop','durable_recovery')", ['00000000-0000-0000-0000-000000000099', '00000000-0000-0000-0000-000000000001', '+12095550123'])
    const suppressionReceipt = await db.query("select id,tenant_id,contact_point,action from suppression_events where id=$1", ['00000000-0000-0000-0000-000000000099'])
    assert.equal(suppressionReceipt.rows[0].action, 'suppressed')
    assert.equal(suppressionReceipt.rows[0].contact_point, '+12095550123')
    await assert.rejects(db.query("update suppression_events set action='released' where id=$1", ['00000000-0000-0000-0000-000000000099']), /permission denied/)
    await db.exec('reset role')
    await db.exec("insert into walkthrough_availability values ('2030-10-12T17:00:00Z', '2030-10-12T18:00:00Z')")
    const book = id => db.query("select reserve_voice_appointment($1, '2030-10-12T17:00:00Z', '123 Main St') as id", [id])
    const first = await book('00000000-0000-0000-0000-000000000001')
    const repeated = await book('00000000-0000-0000-0000-000000000001')
    assert.equal(first.rows[0].id, repeated.rows[0].id)
    await assert.rejects(book('00000000-0000-0000-0000-000000000002'), /exclusion|conflict/)
    await assert.rejects(db.query("select reserve_voice_appointment($1, '2030-10-13T17:00:00Z', '123 Main St')", ['00000000-0000-0000-0000-000000000002']), /availability/)
    await db.query("update voice_appointments set status = 'cancelled' where id = $1", [first.rows[0].id])
    await db.exec('update leads set appt_day_before_sent = true, appt_morning_sent = true, appt_no_show_sent = true')
    const rebooked = await book('00000000-0000-0000-0000-000000000001')
    assert.notEqual(rebooked.rows[0].id, first.rows[0].id)
    const resetFlags = (await db.query('select appt_day_before_sent, appt_morning_sent, appt_no_show_sent from leads where id = $1', ['00000000-0000-0000-0000-000000000001'])).rows[0]
    assert.deepEqual(resetFlags, { appt_day_before_sent: false, appt_morning_sent: false, appt_no_show_sent: false })
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
    await db.exec("update leads set callback_claimed_until = null")
    const generationA = (await db.query('select * from claim_due_callbacks(3)')).rows[0]
    await db.exec("update leads set callback_claimed_until = now() - interval '1 minute'")
    const generationB = (await db.query('select * from claim_due_callbacks(3)')).rows.find(row => row.id === generationA.id)
    assert.notEqual(generationA.callback_claim_token, generationB.callback_claim_token)
    const staleCompletion = await db.query('update leads set callback_scheduled_at = null where id = $1 and callback_claim_token = $2 returning id', [generationA.id, generationA.callback_claim_token])
    assert.equal(staleCompletion.rows.length, 0)
    const complete = await db.query('update leads set callback_scheduled_at = null where id = $1 and callback_claim_token = $2 returning id', [generationB.id, generationB.callback_claim_token])
    assert.equal(complete.rows.length, 1)
    const leadId = '00000000-0000-0000-0000-000000000001'
    const event = (sid, outcome, duration = 0) => db.query('select record_provider_call_outcome($1, $2, $3, $4) as accepted', [leadId, sid, outcome, duration])
    await Promise.all(Array.from({ length: 100 }, () => event('CA-old', 'initiated')))
    assert.equal((await db.query('select call_attempts from leads where id = $1', [leadId])).rows[0].call_attempts, 1)
    await event('CA-old', 'voicemail')
    await event('CA-old', 'answered', 12)
    assert.equal((await db.query('select last_call_outcome from leads where id = $1', [leadId])).rows[0].last_call_outcome, 'voicemail')
    await event('CA-new', 'initiated')
    assert.equal((await event('CA-old', 'busy')).rows[0].accepted, false)
    assert.equal((await event('CA-old', 'initiated')).rows[0].accepted, false)
    let current = (await db.query('select * from leads where id = $1', [leadId])).rows[0]
    assert.equal(current.last_provider_call_sid, 'CA-new')
    assert.equal(current.last_call_outcome, 'initiated')
    assert.equal(current.call_attempts, 2)
    await event('CA-new', 'answered', 30)
    await event('CA-new', 'initiated')
    await event('CA-new', 'no_answer')
    assert.equal((await db.query('select last_call_outcome from leads where id = $1', [leadId])).rows[0].last_call_outcome, 'answered')
    await assert.rejects(db.query('select record_provider_call_outcome($1, $2, $3, 0)', ['00000000-0000-0000-0000-000000000002', 'CA-new', 'busy']), /mismatch/)
    await assert.rejects(event('', 'busy'), /Invalid/)
    await assert.rejects(event('CA-invalid', 'garbage'), /Invalid/)
    await db.exec("update followups set state = 'pending', claimed_until = null; update leads set opted_out = true")
    assert.equal((await db.query('select * from claim_due_call_followups(5)')).rows.length, 0)
    await db.exec('set role anon')
    await assert.rejects(db.query('select * from voice_appointments'), /permission/)
    await assert.rejects(db.query('select * from claim_due_callbacks(3)'), /permission/)
    await assert.rejects(event('CA-anon', 'busy'), /permission/)
    await db.exec('reset role')
    process.stdout.write('PASS: reservation idempotency, collision rejection, availability enforcement, generation-owned callback claims, provider event deduplication/stale rejection, rebooking reminder reset, due/type filtering, and anonymous denial\n')
  } finally { await db.close() }
}

main().catch(error => { process.stderr.write(error.stack + '\n'); process.exitCode = 1 })
