alter table public.leads add column if not exists callback_claim_token uuid;
alter table public.followups add column if not exists claim_token uuid;
alter table public.leads add column if not exists last_provider_call_sid text;
alter table public.leads add column if not exists last_call_outcome text;
alter table public.leads add column if not exists call_attempts integer not null default 0;
alter table public.leads add column if not exists last_called_at timestamptz;

drop function public.claim_due_callbacks(integer);
create function public.claim_due_callbacks(p_limit integer default 3)
returns table(id uuid, callback_scheduled_at timestamptz, callback_claim_token uuid)
language sql security definer set search_path = public
as $$
    with due as (
        select l.id from leads l
        where l.callback_scheduled_at <= now() and coalesce(l.opted_out, false) = false
        and (l.callback_claimed_until is null or l.callback_claimed_until < now())
        order by l.callback_scheduled_at
        for update skip locked limit greatest(0, least(p_limit, 20))
    )
    update leads l set callback_claimed_until = now() + interval '2 minutes', callback_claim_token = gen_random_uuid()
    from due where l.id = due.id returning l.id, l.callback_scheduled_at, l.callback_claim_token;
$$;

create or replace function public.claim_due_call_followups(p_limit integer default 5)
returns setof public.followups
language sql security definer set search_path = public
as $$
    with due as (
        select f.id from followups f join leads l on l.id = f.lead_id
        where f.followup_type = 'call' and coalesce(l.opted_out, false) = false
        and (f.state = 'pending' or (f.state = 'processing' and f.claimed_until < now()))
        and (f.scheduled_at is null or f.scheduled_at <= now())
        order by case f.priority when 'high' then 0 when 'medium' then 1 else 2 end, f.created_at
        for update of f skip locked limit greatest(0, least(p_limit, 20))
    )
    update followups f set state = 'processing', claimed_until = now() + interval '2 minutes', claim_token = gen_random_uuid()
    from due where f.id = due.id returning f.*;
$$;

create table public.provider_call_events (
    call_sid text primary key,
    lead_id uuid not null references public.leads(id),
    outcome text not null,
    duration_seconds integer not null default 0 check (duration_seconds >= 0),
    created_at timestamptz not null default clock_timestamp(),
    updated_at timestamptz not null default clock_timestamp()
);
alter table public.provider_call_events enable row level security;
revoke all on public.provider_call_events from public, anon, authenticated;
grant select, insert, update on public.provider_call_events to service_role;

create function public.record_provider_call_outcome(p_lead_id uuid, p_call_sid text, p_outcome text, p_duration integer default 0)
returns boolean language plpgsql security definer set search_path = public
as $$
declare
    current_sid text;
    event_row provider_call_events%rowtype;
    was_inserted boolean := false;
    event_outcome text;
begin
    if nullif(trim(p_call_sid), '') is null or p_outcome not in ('initiated', 'answered', 'no_answer', 'no-answer', 'busy', 'failed', 'canceled', 'voicemail') then
        raise exception 'Invalid provider event';
    end if;
    select last_provider_call_sid into current_sid from leads where id = p_lead_id for update;
    if not found then raise exception 'Lead not found'; end if;
    select * into event_row from provider_call_events where call_sid = p_call_sid;
    if found and event_row.lead_id <> p_lead_id then raise exception 'Provider call lead mismatch'; end if;
    if not found then
        insert into provider_call_events(call_sid, lead_id, outcome, duration_seconds)
        values(p_call_sid, p_lead_id, p_outcome, greatest(0, p_duration)) returning * into event_row;
        was_inserted := true;
    end if;
    event_outcome := case
        when event_row.outcome = 'voicemail' then 'voicemail'
        when event_row.outcome <> 'initiated' and p_outcome <> 'voicemail' then event_row.outcome
        else p_outcome end;
    update provider_call_events set outcome = event_outcome,
        duration_seconds = greatest(duration_seconds, p_duration, 0), updated_at = clock_timestamp()
        where call_sid = p_call_sid;
    if was_inserted then
        update leads set call_attempts = coalesce(call_attempts, 0) + 1 where id = p_lead_id;
    end if;
    if current_sid is not null and current_sid <> p_call_sid then
        if p_outcome <> 'initiated' or exists (
            select 1 from provider_call_events where call_sid = current_sid and created_at > event_row.created_at
        ) then return false; end if;
    end if;
    update leads set last_provider_call_sid = p_call_sid, last_call_outcome = event_outcome,
        last_called_at = event_row.created_at where id = p_lead_id;
    return true;
end;
$$;

revoke all on function public.claim_due_callbacks(integer) from public, anon, authenticated;
revoke all on function public.claim_due_call_followups(integer) from public, anon, authenticated;
revoke all on function public.record_provider_call_outcome(uuid, text, text, integer) from public, anon, authenticated;
grant execute on function public.claim_due_callbacks(integer) to service_role;
grant execute on function public.claim_due_call_followups(integer) to service_role;
grant execute on function public.record_provider_call_outcome(uuid, text, text, integer) to service_role;

alter table public.leads add column if not exists appt_day_before_sent boolean not null default false;
alter table public.leads add column if not exists appt_morning_sent boolean not null default false;
alter table public.leads add column if not exists appt_no_show_sent boolean not null default false;

create or replace function public.reserve_voice_appointment(p_lead_id uuid, p_starts_at timestamptz, p_address text)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
    slot_end timestamptz;
    reservation uuid;
begin
    if p_starts_at <= now() or length(trim(p_address)) = 0 then
        raise exception 'Invalid appointment';
    end if;
    select id into reservation from voice_appointments
    where lead_id = p_lead_id and starts_at = p_starts_at and status = 'confirmed';
    if reservation is not null then
        return reservation;
    end if;
    select ends_at into slot_end from walkthrough_availability
    where starts_at = p_starts_at for update;
    if slot_end is null then
        raise exception 'No approved availability for this time';
    end if;
    select id into reservation from voice_appointments
    where lead_id = p_lead_id and starts_at = p_starts_at and status = 'confirmed';
    if reservation is not null then
        return reservation;
    end if;
    insert into voice_appointments(lead_id, starts_at, ends_at, address)
    values (p_lead_id, p_starts_at, slot_end, p_address) returning id into reservation;
    update leads set appointment_at = p_starts_at, stage = 'walkthrough_booked', updated_at = now(),
        appt_day_before_sent = false, appt_morning_sent = false, appt_no_show_sent = false
    where id = p_lead_id;
    return reservation;
end;
$$;

