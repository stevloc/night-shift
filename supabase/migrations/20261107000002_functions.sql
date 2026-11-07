-- Server-side functions, called only by the backend (service_role) through PostgREST RPC.
-- They run as the caller (security invoker), and the browser roles cannot execute them.

-- Copy the demo template (seeded from demo-data/) into a new restaurant owned by p_user_id.
-- Idempotent: if the user already has a restaurant, its id is returned.
create or replace function public.create_demo_restaurant(p_user_id uuid)
returns uuid
language plpgsql
set search_path = public
as $$
declare
  v_template uuid;
  v_new uuid;
begin
  select id into v_new from restaurants where owner_user_id = p_user_id;
  if v_new is not null then
    return v_new;
  end if;

  select id into v_template from restaurants where is_template;
  if v_template is null then
    raise exception 'Demo template missing: run the seed_demo_template migration';
  end if;

  begin
    insert into restaurants (owner_user_id, name, settings)
    select p_user_id, name, settings from restaurants where id = v_template
    returning id into v_new;
  exception when unique_violation then
    -- Two first requests at once: the other one won; use its restaurant.
    select id into v_new from restaurants where owner_user_id = p_user_id;
    return v_new;
  end;

  insert into ingredients (restaurant_id, ingredient_key, name, invoice_alias, pack_desc, pack_size, pack_unit,
                           pack_price, yield_pct, baseline_pack_size, baseline_pack_unit, baseline_pack_price, source)
  select v_new, ingredient_key, name, invoice_alias, pack_desc, pack_size, pack_unit,
         pack_price, yield_pct, baseline_pack_size, baseline_pack_unit, baseline_pack_price, source
  from ingredients where restaurant_id = v_template;

  insert into menu_items (restaurant_id, item_key, name, in_store_price, doordash_price)
  select v_new, item_key, name, in_store_price, doordash_price from menu_items where restaurant_id = v_template;

  insert into recipes (restaurant_id, item_key, ingredient_key, qty, unit)
  select v_new, item_key, ingredient_key, qty, unit from recipes where restaurant_id = v_template;

  insert into price_history (restaurant_id, ingredient_key, observed_on, pack_price, pack_size, pack_unit, source)
  select v_new, ingredient_key, observed_on, pack_price, pack_size, pack_unit, source
  from price_history where restaurant_id = v_template;

  insert into orders_daily (restaurant_id, item_key, day, orders)
  select v_new, item_key, day, orders from orders_daily where restaurant_id = v_template;

  return v_new;
end;
$$;

-- "Reset demo": delete the user's restaurant (everything cascades) and seed a fresh copy.
create or replace function public.reset_demo_restaurant(p_user_id uuid)
returns uuid
language plpgsql
set search_path = public
as $$
begin
  delete from restaurants where owner_user_id = p_user_id;
  return create_demo_restaurant(p_user_id);
end;
$$;

-- Everything the engine needs for one restaurant, in one round trip.
create or replace function public.get_restaurant_state(p_restaurant_id uuid)
returns jsonb
language sql
stable
set search_path = public
as $$
  select jsonb_build_object(
    'restaurant',    (select to_jsonb(r) from restaurants r where r.id = p_restaurant_id),
    'ingredients',   coalesce((select jsonb_agg(to_jsonb(x) order by x.id) from ingredients x where x.restaurant_id = p_restaurant_id), '[]'),
    'menu_items',    coalesce((select jsonb_agg(to_jsonb(x) order by x.id) from menu_items x where x.restaurant_id = p_restaurant_id), '[]'),
    'recipes',       coalesce((select jsonb_agg(to_jsonb(x) order by x.id) from recipes x where x.restaurant_id = p_restaurant_id), '[]'),
    'invoices',      coalesce((select jsonb_agg(to_jsonb(x) order by x.local_id) from invoices x where x.restaurant_id = p_restaurant_id), '[]'),
    'invoice_lines', coalesce((select jsonb_agg(to_jsonb(x) order by x.invoice_local_id, x.line_no) from invoice_lines x where x.restaurant_id = p_restaurant_id), '[]'),
    'decisions',     coalesce((select jsonb_agg(to_jsonb(x) order by x.local_id) from decisions x where x.restaurant_id = p_restaurant_id), '[]'),
    'activity_log',  coalesce((select jsonb_agg(to_jsonb(x) order by x.local_id) from activity_log x where x.restaurant_id = p_restaurant_id), '[]')
  );
$$;

-- Save one request's changes atomically. The backend sends the full current rows for small tables
-- (upserted) and only the NEW rows for append-only tables (price_history, activity_log).
create or replace function public.save_restaurant_state(p_restaurant_id uuid, p_state jsonb)
returns void
language plpgsql
set search_path = public
as $$
begin
  update restaurants
     set settings = coalesce(p_state->'settings', settings),
         engine_state = coalesce(p_state->'engine_state', engine_state)
   where id = p_restaurant_id;

  insert into ingredients (restaurant_id, ingredient_key, name, invoice_alias, pack_desc, pack_size, pack_unit, pack_price,
                           yield_pct, baseline_pack_size, baseline_pack_unit, baseline_pack_price, source)
  select p_restaurant_id, x.ingredient_key, x.name, x.invoice_alias, x.pack_desc, x.pack_size, x.pack_unit, x.pack_price,
         x.yield_pct, x.baseline_pack_size, x.baseline_pack_unit, x.baseline_pack_price, x.source
  from jsonb_to_recordset(coalesce(p_state->'ingredients', '[]')) as x(
    ingredient_key text, name jsonb, invoice_alias text, pack_desc text, pack_size numeric, pack_unit text,
    pack_price numeric, yield_pct numeric, baseline_pack_size numeric, baseline_pack_unit text,
    baseline_pack_price numeric, source jsonb)
  on conflict (restaurant_id, ingredient_key) do update set
    pack_size = excluded.pack_size, pack_unit = excluded.pack_unit, pack_price = excluded.pack_price,
    yield_pct = excluded.yield_pct, baseline_pack_size = excluded.baseline_pack_size,
    baseline_pack_unit = excluded.baseline_pack_unit, baseline_pack_price = excluded.baseline_pack_price,
    source = excluded.source;

  insert into recipes (restaurant_id, item_key, ingredient_key, qty, unit)
  select p_restaurant_id, x.item_key, x.ingredient_key, x.qty, x.unit
  from jsonb_to_recordset(coalesce(p_state->'recipes', '[]')) as x(item_key text, ingredient_key text, qty numeric, unit text)
  on conflict (restaurant_id, item_key, ingredient_key) do update set qty = excluded.qty, unit = excluded.unit;

  insert into invoices (restaurant_id, local_id, file_name, supplier, invoice_number, invoice_date, total, lines_sum,
                        totals_match, fingerprint, storage_path, mime, layout, from_demo, read_at)
  select p_restaurant_id, x.local_id, x.file_name, x.supplier, x.invoice_number, x.invoice_date, x.total, x.lines_sum,
         x.totals_match, x.fingerprint, x.storage_path, x.mime, x.layout, coalesce(x.from_demo, false), x.read_at
  from jsonb_to_recordset(coalesce(p_state->'invoices', '[]')) as x(
    local_id integer, file_name text, supplier text, invoice_number text, invoice_date text, total numeric,
    lines_sum numeric, totals_match boolean, fingerprint text, storage_path text, mime text, layout jsonb,
    from_demo boolean, read_at timestamptz)
  on conflict (restaurant_id, local_id) do update set
    lines_sum = excluded.lines_sum, totals_match = excluded.totals_match,
    storage_path = coalesce(excluded.storage_path, invoices.storage_path), layout = excluded.layout;

  insert into invoice_lines (restaurant_id, invoice_local_id, line_no, description, quantity, ingredient_key, pack_size,
                             pack_unit, pack_price, match_confidence, needs_review, reasons, unclear, corrected, applied,
                             prev, prev_source)
  select p_restaurant_id, x.invoice_local_id, x.line_no, x.description, x.quantity, x.ingredient_key, x.pack_size,
         x.pack_unit, x.pack_price, x.match_confidence, x.needs_review, coalesce(x.reasons, '[]'),
         coalesce(x.unclear, '[]'), x.corrected, x.applied, x.prev, x.prev_source
  from jsonb_to_recordset(coalesce(p_state->'invoice_lines', '[]')) as x(
    invoice_local_id integer, line_no integer, description text, quantity numeric, ingredient_key text,
    pack_size numeric, pack_unit text, pack_price numeric, match_confidence numeric, needs_review boolean,
    reasons jsonb, unclear jsonb, corrected boolean, applied boolean, prev jsonb, prev_source jsonb)
  on conflict (restaurant_id, invoice_local_id, line_no) do update set
    ingredient_key = excluded.ingredient_key, pack_size = excluded.pack_size, pack_unit = excluded.pack_unit,
    pack_price = excluded.pack_price, match_confidence = excluded.match_confidence,
    needs_review = excluded.needs_review, reasons = excluded.reasons, unclear = excluded.unclear,
    corrected = excluded.corrected, applied = excluded.applied, prev = excluded.prev, prev_source = excluded.prev_source;

  insert into price_history (restaurant_id, ingredient_key, observed_on, pack_price, pack_size, pack_unit, source)
  select p_restaurant_id, x.ingredient_key, x.observed_on, x.pack_price, x.pack_size, x.pack_unit, x.source
  from jsonb_to_recordset(coalesce(p_state->'price_history_new', '[]')) as x(
    ingredient_key text, observed_on date, pack_price numeric, pack_size numeric, pack_unit text, source jsonb);

  insert into findings (restaurant_id, item_key, status, evidence, updated_at)
  select p_restaurant_id, x.item_key, x.status, coalesce(x.evidence, '{}'), now()
  from jsonb_to_recordset(coalesce(p_state->'findings', '[]')) as x(item_key text, status text, evidence jsonb)
  on conflict (restaurant_id, item_key) do update set
    status = excluded.status, evidence = excluded.evidence, updated_at = now();

  insert into decisions (restaurant_id, local_id, item_key, action, reason, user_id, decided_at, details)
  select p_restaurant_id, x.local_id, x.item_key, x.action, x.reason, x.user_id, x.decided_at, coalesce(x.details, '{}')
  from jsonb_to_recordset(coalesce(p_state->'decisions', '[]')) as x(
    local_id integer, item_key text, action text, reason text, user_id uuid, decided_at timestamptz, details jsonb)
  on conflict (restaurant_id, local_id) do update set details = excluded.details;

  insert into activity_log (restaurant_id, local_id, run_id, "group", message, evidence, at)
  select p_restaurant_id, x.local_id, x.run_id, x."group", x.message, coalesce(x.evidence, '{}'), x.at
  from jsonb_to_recordset(coalesce(p_state->'activity_new', '[]')) as x(
    local_id integer, run_id uuid, "group" text, message text, evidence jsonb, at timestamptz)
  on conflict (restaurant_id, local_id) do nothing;
end;
$$;

-- Only the backend may call these.
revoke all on function public.create_demo_restaurant(uuid) from public, anon, authenticated;
revoke all on function public.reset_demo_restaurant(uuid) from public, anon, authenticated;
revoke all on function public.get_restaurant_state(uuid) from public, anon, authenticated;
revoke all on function public.save_restaurant_state(uuid, jsonb) from public, anon, authenticated;
grant execute on function public.create_demo_restaurant(uuid) to service_role;
grant execute on function public.reset_demo_restaurant(uuid) to service_role;
grant execute on function public.get_restaurant_state(uuid) to service_role;
grant execute on function public.save_restaurant_state(uuid, jsonb) to service_role;
