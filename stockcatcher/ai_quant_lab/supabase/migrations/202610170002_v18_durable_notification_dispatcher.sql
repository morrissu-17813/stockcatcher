-- AI Quant Lab V18: durable notification dispatcher. Additive to V17; no Tianji 3K production writes.
begin;

alter table public.ai_quant_lab_outbox
  add column if not exists max_attempts integer not null default 8,
  add column if not exists claimed_by text,
  add column if not exists external_message_id text,
  add column if not exists response_metadata jsonb not null default '{}'::jsonb,
  add column if not exists delivered_at timestamptz,
  add column if not exists last_attempt_at timestamptz,
  add column if not exists dead_lettered_at timestamptz,
  add column if not exists priority integer not null default 100;

-- Extend the existing status check without assuming PostgreSQL's generated constraint name.
do $$
declare c record;
begin
  for c in
    select conname from pg_constraint
    where conrelid = 'public.ai_quant_lab_outbox'::regclass and contype = 'c'
      and pg_get_constraintdef(oid) ilike '%status%'
  loop
    execute format('alter table public.ai_quant_lab_outbox drop constraint %I', c.conname);
  end loop;
end $$;
alter table public.ai_quant_lab_outbox
  add constraint ai_quant_lab_outbox_status_v18_check
  check (status in ('PENDING','SENDING','SENT','RETRY_PENDING','FAILED','UNKNOWN','DEAD_LETTER','SUPPRESSED'));

create index if not exists ix_ai_quant_lab_outbox_claim
  on public.ai_quant_lab_outbox(status, available_at, priority, created_at);
create index if not exists ix_ai_quant_lab_outbox_expired_lease
  on public.ai_quant_lab_outbox(status, lease_expires_at) where status = 'SENDING';
create index if not exists ix_ai_quant_lab_outbox_event
  on public.ai_quant_lab_outbox(event_id, created_at desc);

-- Atomic claim: one transaction locks and leases due jobs. Expired SENDING leases are reclaimable.
create or replace function public.ai_quant_lab_claim_outbox(
  p_worker_id text,
  p_limit integer default 10,
  p_lease_seconds integer default 45
) returns setof public.ai_quant_lab_outbox
language plpgsql
security definer
set search_path = public
as $$
begin
  if p_worker_id is null or length(trim(p_worker_id)) = 0 then
    raise exception 'worker_id is required';
  end if;
  update public.ai_quant_lab_outbox o
     set status = 'DEAD_LETTER', dead_lettered_at = now(),
         last_error = coalesce(o.last_error || ' | ', '') || 'LEASE_EXPIRED_MAX_ATTEMPTS',
         lease_expires_at = null, claimed_by = null, updated_at = now()
   where o.status = 'SENDING' and o.lease_expires_at < now() and o.attempts >= o.max_attempts;
  return query
  with candidates as (
    select o.outbox_id
    from public.ai_quant_lab_outbox o
    where (
      (o.status in ('PENDING','RETRY_PENDING') and o.available_at <= now())
      or (o.status = 'SENDING' and o.lease_expires_at is not null and o.lease_expires_at < now())
    )
    and o.attempts < o.max_attempts
    order by o.priority asc, o.available_at asc, o.created_at asc
    for update skip locked
    limit greatest(1, least(coalesce(p_limit, 10), 100))
  ), claimed as (
    update public.ai_quant_lab_outbox o
    set status = 'SENDING', claimed_by = p_worker_id,
        lease_expires_at = now() + make_interval(secs => greatest(10, least(coalesce(p_lease_seconds,45),300))),
        attempts = o.attempts + 1, last_attempt_at = now(), updated_at = now()
    from candidates c where o.outbox_id = c.outbox_id
    returning o.*
  ) select * from claimed;
end;
$$;

create or replace function public.ai_quant_lab_notification_counts()
returns table(status text, count bigint, oldest_created_at timestamptz)
language sql
security definer
set search_path = public
as $$
  select o.status, count(*)::bigint, min(o.created_at)
  from public.ai_quant_lab_outbox o
  group by o.status;
$$;

revoke all on function public.ai_quant_lab_claim_outbox(text, integer, integer) from public, anon, authenticated;
revoke all on function public.ai_quant_lab_notification_counts() from public, anon, authenticated;
grant execute on function public.ai_quant_lab_claim_outbox(text, integer, integer) to service_role;
grant execute on function public.ai_quant_lab_notification_counts() to service_role;
grant select, insert, update on public.ai_quant_lab_outbox to service_role;


-- Atomic paper-fill + event + notification outbox commit (transactional outbox pattern).
create or replace function public.ai_quant_lab_commit_event_and_outbox(
  p_event jsonb,
  p_outcome jsonb,
  p_trade jsonb,
  p_outbox jsonb
) returns table(event_seq bigint, inserted boolean, outbox_inserted boolean)
language plpgsql
security definer
set search_path = public
as $$
declare
  v_event_seq bigint;
  v_inserted boolean := false;
  v_outbox_inserted boolean := false;
  v_event_id text;
begin
  v_event_id := p_event ->> 'event_id';
  if v_event_id is null or length(v_event_id) = 0 then raise exception 'event_id is required'; end if;
  if p_trade is null or p_outbox is null then raise exception 'paper trade and outbox payload are required'; end if;

  insert into public.ai_quant_lab_events
    (event_key, idempotency_key, schema_version, event_type, source, symbol, stock_name, occurred_at, payload)
  values
    (v_event_id, v_event_id, coalesce((p_event ->> 'schema_version')::integer, 1),
     coalesce(p_event ->> 'event_type', 'unknown'), coalesce(p_event ->> 'source', 'ai_quant_lab'),
     nullif(p_event -> 'payload' ->> 'symbol', ''), nullif(p_event -> 'payload' ->> 'stock_name', ''),
     coalesce((p_event ->> 'occurred_at')::timestamptz, now()),
     jsonb_build_object('event', p_event, 'outcome', p_outcome, 'session_id', p_event -> 'session_id'))
  on conflict (idempotency_key) do nothing
  returning ai_quant_lab_events.event_seq into v_event_seq;
  v_inserted := found;

  insert into public.ai_quant_lab_paper_trades
    (trade_key, idempotency_key, session_id, symbol, stock_name, side, quantity, price, fees,
     realized_pnl, strategy, status, executed_at, metadata)
  values
    (p_trade ->> 'trade_key', p_trade ->> 'idempotency_key', nullif(p_trade ->> 'session_id', '')::uuid,
     p_trade ->> 'symbol', p_trade ->> 'stock_name', p_trade ->> 'side',
     (p_trade ->> 'quantity')::integer, (p_trade ->> 'price')::numeric, (p_trade ->> 'fees')::numeric,
     (p_trade ->> 'realized_pnl')::numeric, coalesce(p_trade ->> 'strategy', 'AI_QUANT_LAB_PAPER'),
     coalesce(p_trade ->> 'status', 'FILLED'), coalesce((p_trade ->> 'executed_at')::timestamptz, now()),
     coalesce(p_trade -> 'metadata', '{}'::jsonb))
  on conflict (idempotency_key) do nothing;

  insert into public.ai_quant_lab_outbox
    (outbox_id, session_id, event_id, destination, payload, status, idempotency_key,
     attempts, available_at, max_attempts, priority, created_at, updated_at)
  values
    ((p_outbox ->> 'outbox_id')::uuid, nullif(p_outbox ->> 'session_id', '')::uuid,
     p_outbox ->> 'event_id', p_outbox ->> 'destination', p_outbox -> 'payload',
     coalesce(p_outbox ->> 'status', 'PENDING'), p_outbox ->> 'idempotency_key', 0,
     coalesce((p_outbox ->> 'available_at')::timestamptz, now()),
     coalesce((p_outbox ->> 'max_attempts')::integer, 8), coalesce((p_outbox ->> 'priority')::integer, 100), now(), now())
  on conflict (idempotency_key) do nothing;
  v_outbox_inserted := found;

  if v_event_seq is null then
    select e.event_seq into v_event_seq from public.ai_quant_lab_events e where e.idempotency_key = v_event_id;
  end if;
  return query select v_event_seq, v_inserted, v_outbox_inserted;
end;
$$;
revoke all on function public.ai_quant_lab_commit_event_and_outbox(jsonb,jsonb,jsonb,jsonb) from public, anon, authenticated;
grant execute on function public.ai_quant_lab_commit_event_and_outbox(jsonb,jsonb,jsonb,jsonb) to service_role;

commit;
