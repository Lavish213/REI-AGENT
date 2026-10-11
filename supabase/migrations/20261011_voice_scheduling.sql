create extension if not exists btree_gist;

create table if not exists public.walkthrough_availability (
    starts_at timestamptz primary key,
    ends_at timestamptz not null,
    check (ends_at > starts_at)
);

create table if not exists public.voice_appointments (
    id uuid primary key default gen_random_uuid(),
    lead_id uuid not null references public.leads(id),
    starts_at timestamptz not null,
    ends_at timestamptz not null,
    address text not null,
    status text not null default 'confirmed' check (status in ('confirmed', 'cancelled')),
    created_at timestamptz not null default now(),
    unique (lead_id, starts_at),
    exclude using gist (tstzrange(starts_at, ends_at, '[)') with &&) where (status = 'confirmed')
);

alter table public.walkthrough_availability enable row level security;
alter table public.voice_appointments enable row level security;

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
    insert into voice_appointments(lead_id, starts_at, ends_at, address)
    values (p_lead_id, p_starts_at, slot_end, p_address) returning id into reservation;
    update leads set appointment_at = p_starts_at, stage = 'walkthrough_booked', updated_at = now()
    where id = p_lead_id;
    return reservation;
end;
$$;

revoke all on function public.reserve_voice_appointment(uuid, timestamptz, text) from public, anon, authenticated;
grant execute on function public.reserve_voice_appointment(uuid, timestamptz, text) to service_role;

alter table public.leads add column if not exists callback_claimed_until timestamptz;
alter table public.followups add column if not exists claimed_until timestamptz;

create or replace function public.claim_due_callbacks(p_limit integer default 3)
returns table(id uuid, callback_scheduled_at timestamptz)
language sql
security definer
set search_path = public
as $$
    with due as (
        select l.id from leads l
        where l.callback_scheduled_at <= now()
        and coalesce(l.opted_out, false) = false
        and (l.callback_claimed_until is null or l.callback_claimed_until < now())
        order by l.callback_scheduled_at
        for update skip locked limit greatest(0, least(p_limit, 20))
    )
    update leads l set callback_claimed_until = now() + interval '2 minutes'
    from due where l.id = due.id returning l.id, l.callback_scheduled_at;
$$;

create or replace function public.claim_due_call_followups(p_limit integer default 5)
returns setof public.followups
language sql
security definer
set search_path = public
as $$
    with due as (
        select f.id from followups f
        where f.followup_type = 'call'
        and (f.state = 'pending' or (f.state = 'processing' and f.claimed_until < now()))
        and (f.scheduled_at is null or f.scheduled_at <= now())
        order by case f.priority when 'high' then 0 when 'medium' then 1 else 2 end, f.created_at
        for update skip locked limit greatest(0, least(p_limit, 20))
    )
    update followups f set state = 'processing', claimed_until = now() + interval '2 minutes'
    from due where f.id = due.id returning f.*;
$$;

revoke all on function public.claim_due_callbacks(integer) from public, anon, authenticated;
revoke all on function public.claim_due_call_followups(integer) from public, anon, authenticated;
grant execute on function public.claim_due_callbacks(integer) to service_role;
grant execute on function public.claim_due_call_followups(integer) to service_role;

create table if not exists public.dnc_list (
    id uuid primary key default gen_random_uuid(),
    phone text not null unique,
    created_at timestamptz not null default now()
);
alter table public.dnc_list enable row level security;

create table if not exists public.campaigns (
    id text primary key,
    state text not null default 'paused' check (state in ('paused', 'running')),
    created_at timestamptz not null default now()
);
insert into public.campaigns(id, state) values ('default', 'paused') on conflict do nothing;

do $$
declare
    relation record;
begin
    for relation in select tablename from pg_tables where schemaname = 'public' loop
        execute format('alter table public.%I enable row level security', relation.tablename);
        execute format('revoke all on public.%I from anon', relation.tablename);
        execute format('grant select, insert, update, delete on public.%I to service_role', relation.tablename);
    end loop;
end;
$$;
