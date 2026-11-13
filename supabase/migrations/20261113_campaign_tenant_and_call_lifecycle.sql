alter table public.campaigns add column if not exists tenant_id uuid;
update public.campaigns set tenant_id = '00000000-0000-0000-0000-000000000001' where tenant_id is null;
alter table public.campaigns alter column tenant_id set default '00000000-0000-0000-0000-000000000001';
alter table public.campaigns alter column tenant_id set not null;

do $$
begin
    alter table public.campaigns add constraint campaigns_tenant_id_fkey foreign key (tenant_id) references public.tenants(id);
exception when duplicate_object then
    null;
end $$;

do $$
declare
    key_columns text[];
begin
    select array_agg(attribute.attname::text order by attribute.attname)
    into key_columns
    from pg_constraint constraint_row
    join pg_attribute attribute on attribute.attrelid = constraint_row.conrelid and attribute.attnum = any(constraint_row.conkey)
    where constraint_row.conrelid = 'public.campaigns'::regclass and constraint_row.contype = 'p';
    if key_columns is distinct from array['id', 'tenant_id'] then
        if key_columns is not null then
            execute (select format('alter table public.campaigns drop constraint %I', conname) from pg_constraint where conrelid = 'public.campaigns'::regclass and contype = 'p');
        end if;
        alter table public.campaigns add constraint campaigns_pkey primary key (tenant_id, id);
    end if;
end $$;

create index if not exists idx_campaigns_tenant on public.campaigns (tenant_id);
alter table public.campaigns enable row level security;
drop policy if exists campaigns_tenant_isolation on public.campaigns;
create policy campaigns_tenant_isolation on public.campaigns using (tenant_id::text = current_setting('app.tenant_id', true));
insert into public.campaigns(tenant_id, id, state) values ('00000000-0000-0000-0000-000000000001', 'default', 'paused') on conflict do nothing;

alter table public.calls add column if not exists tenant_id uuid;
update public.calls set tenant_id = '00000000-0000-0000-0000-000000000001' where tenant_id is null;
alter table public.calls alter column tenant_id set default '00000000-0000-0000-0000-000000000001';
alter table public.calls alter column tenant_id set not null;
alter table public.calls add column if not exists direction text;
alter table public.calls add column if not exists provider_status text;
alter table public.calls add column if not exists provider_status_rank integer not null default 0;
alter table public.calls add column if not exists duration_seconds integer not null default 0;
alter table public.calls add column if not exists ended_at timestamptz;
alter table public.calls add column if not exists recording_url text;
alter table public.calls add column if not exists recording_sid text;
alter table public.calls add column if not exists recording_duration_seconds integer;
alter table public.calls add column if not exists updated_at timestamptz not null default now();

do $$
begin
    if exists (
        select 1 from public.calls
        where signalwire_call_id is not null
        group by tenant_id, signalwire_call_id
        having count(*) > 1
    ) then
        raise exception 'calls contains duplicate provider call IDs; reconcile them before applying this migration';
    end if;
end $$;

create unique index if not exists calls_tenant_provider_call_key on public.calls (tenant_id, signalwire_call_id) where signalwire_call_id is not null;

create or replace function public.record_call_lifecycle(
    p_tenant_id uuid,
    p_lead_id uuid,
    p_call_sid text,
    p_direction text,
    p_status text,
    p_duration integer default 0
)
returns uuid language plpgsql security definer set search_path = public
as $$
declare
    status_rank integer;
    existing public.calls%rowtype;
    row_id uuid;
begin
    if p_tenant_id is null then
        raise exception 'Tenant is required';
    end if;
    if p_call_sid is null or p_call_sid !~ '^[A-Za-z0-9_-]{1,128}$' then
        raise exception 'Invalid provider call ID';
    end if;
    if p_direction is not null and p_direction not in ('inbound', 'outbound') then
        raise exception 'Invalid call direction';
    end if;
    status_rank := case p_status
        when 'queued' then 10
        when 'initiated' then 10
        when 'ringing' then 20
        when 'in-progress' then 30
        when 'answered' then 30
        when 'completed' then 40
        when 'busy' then 40
        when 'no-answer' then 40
        when 'failed' then 40
        when 'canceled' then 40
        else null
    end;
    if p_status is not null and status_rank is null then
        raise exception 'Invalid provider call status';
    end if;
    if p_lead_id is not null and not exists (select 1 from public.leads where id = p_lead_id and tenant_id = p_tenant_id) then
        raise exception 'Lead not found for tenant';
    end if;
    insert into public.calls (tenant_id, lead_id, signalwire_call_id, direction)
    values (p_tenant_id, p_lead_id, p_call_sid, p_direction)
    on conflict (tenant_id, signalwire_call_id) where signalwire_call_id is not null do nothing;
    select * into existing from public.calls where tenant_id = p_tenant_id and signalwire_call_id = p_call_sid for update;
    if existing.lead_id is not null and p_lead_id is not null and existing.lead_id <> p_lead_id then
        raise exception 'Provider call lead mismatch';
    end if;
    if existing.direction is not null and p_direction is not null and existing.direction <> p_direction then
        raise exception 'Provider call direction mismatch';
    end if;
    update public.calls set
        lead_id = coalesce(existing.lead_id, p_lead_id),
        direction = coalesce(existing.direction, p_direction),
        provider_status = case when coalesce(status_rank, 0) > existing.provider_status_rank then p_status else existing.provider_status end,
        provider_status_rank = greatest(existing.provider_status_rank, coalesce(status_rank, 0)),
        duration_seconds = greatest(existing.duration_seconds, coalesce(p_duration, 0), 0),
        ended_at = case when status_rank = 40 and existing.ended_at is null then clock_timestamp() else existing.ended_at end,
        updated_at = clock_timestamp()
    where id = existing.id
    returning id into row_id;
    return row_id;
end;
$$;

create or replace function public.record_call_recording(
    p_tenant_id uuid,
    p_lead_id uuid,
    p_call_sid text,
    p_recording_url text,
    p_recording_sid text,
    p_duration integer default 0
)
returns uuid language plpgsql security definer set search_path = public
as $$
declare
    row_id uuid;
begin
    if nullif(trim(p_recording_url), '') is null then
        raise exception 'Recording URL is required';
    end if;
    row_id := public.record_call_lifecycle(p_tenant_id, p_lead_id, p_call_sid, null, null, 0);
    update public.calls set
        recording_url = coalesce(recording_url, p_recording_url),
        recording_sid = coalesce(recording_sid, nullif(trim(p_recording_sid), '')),
        recording_duration_seconds = coalesce(recording_duration_seconds, greatest(coalesce(p_duration, 0), 0)),
        updated_at = clock_timestamp()
    where id = row_id;
    return row_id;
end;
$$;

revoke all on function public.record_call_lifecycle(uuid, uuid, text, text, text, integer) from public, anon, authenticated;
revoke all on function public.record_call_recording(uuid, uuid, text, text, text, integer) from public, anon, authenticated;
grant execute on function public.record_call_lifecycle(uuid, uuid, text, text, text, integer) to service_role;
grant execute on function public.record_call_recording(uuid, uuid, text, text, text, integer) to service_role;
