-- Night Shift schema.
-- Every table carries restaurant_id and created_at. Row Level Security is ON for every table and
-- there are NO policies: the anon/authenticated roles (the browser) can read or write nothing.
-- Only the backend, using the service_role key (which bypasses RLS), touches this data.

create table public.restaurants (
  id              uuid primary key default gen_random_uuid(),
  owner_user_id   uuid references auth.users (id) on delete cascade,
  name            text not null,
  settings        jsonb not null default '{}'::jsonb,   -- fee %, packaging, target %, forecast
  engine_state    jsonb not null default '{}'::jsonb,   -- small bookkeeping (open decisions, run flags)
  is_template     boolean not null default false,       -- the demo-data/ copy new users are seeded from
  created_at      timestamptz not null default now()
);
create unique index restaurants_one_per_owner on public.restaurants (owner_user_id) where owner_user_id is not null;
create unique index restaurants_one_template on public.restaurants (is_template) where is_template;

create table public.ingredients (
  id                  bigint generated always as identity primary key,
  restaurant_id       uuid not null references public.restaurants (id) on delete cascade,
  ingredient_key      text not null,
  name                jsonb not null,                    -- {"en": "...", "es": "..."}
  invoice_alias       text not null,
  pack_desc           text,
  pack_size           numeric not null,
  pack_unit           text not null,
  pack_price          numeric not null,
  yield_pct           numeric not null,
  baseline_pack_size  numeric,                           -- price before the latest run ("before")
  baseline_pack_unit  text,
  baseline_pack_price numeric,
  source              jsonb,                             -- invoice line / price history it came from
  created_at          timestamptz not null default now(),
  unique (restaurant_id, ingredient_key)
);

create table public.menu_items (
  id              bigint generated always as identity primary key,
  restaurant_id   uuid not null references public.restaurants (id) on delete cascade,
  item_key        text not null,
  name            jsonb not null,
  in_store_price  numeric not null,
  doordash_price  numeric not null,
  created_at      timestamptz not null default now(),
  unique (restaurant_id, item_key)
);

create table public.recipes (
  id              bigint generated always as identity primary key,
  restaurant_id   uuid not null references public.restaurants (id) on delete cascade,
  item_key        text not null,
  ingredient_key  text not null,
  qty             numeric not null,                      -- per serving, in `unit`
  unit            text not null,
  created_at      timestamptz not null default now(),
  unique (restaurant_id, item_key, ingredient_key)
);

create table public.invoices (
  id              bigint generated always as identity primary key,
  restaurant_id   uuid not null references public.restaurants (id) on delete cascade,
  local_id        integer not null,                      -- position within this restaurant
  file_name       text,
  supplier        text,
  invoice_number  text,
  invoice_date    text,
  total           numeric,
  lines_sum       numeric,
  totals_match    boolean,
  fingerprint     text,                                  -- normalized supplier + invoice_number
  storage_path    text,                                  -- private bucket "invoices"
  mime            text,
  layout          jsonb,                                 -- detected line positions (for crops)
  from_demo       boolean not null default false,
  read_at         timestamptz,
  created_at      timestamptz not null default now(),
  unique (restaurant_id, local_id),
  unique (restaurant_id, fingerprint)                    -- the same invoice is never counted twice
);

create table public.invoice_lines (
  id                bigint generated always as identity primary key,
  restaurant_id     uuid not null,
  invoice_local_id  integer not null,
  line_no           integer not null,
  description       text,
  quantity          numeric,
  ingredient_key    text,
  pack_size         numeric,
  pack_unit         text,
  pack_price        numeric,
  match_confidence  numeric,                             -- 1 = matched by alias / confirmed; lower = unsure
  needs_review      boolean not null default false,
  reasons           jsonb not null default '[]'::jsonb,
  unclear           jsonb not null default '[]'::jsonb,
  corrected         boolean not null default false,
  applied           boolean not null default false,
  prev              jsonb,
  prev_source       jsonb,
  created_at        timestamptz not null default now(),
  unique (restaurant_id, invoice_local_id, line_no),
  foreign key (restaurant_id, invoice_local_id)
    references public.invoices (restaurant_id, local_id) on delete cascade
);

create table public.price_history (
  id              bigint generated always as identity primary key,
  restaurant_id   uuid not null references public.restaurants (id) on delete cascade,
  ingredient_key  text not null,
  observed_on     date not null,
  pack_price      numeric not null,
  pack_size       numeric,
  pack_unit       text,
  source          jsonb,
  created_at      timestamptz not null default now()
);
create index price_history_lookup on public.price_history (restaurant_id, ingredient_key, observed_on);

create table public.orders_daily (
  id              bigint generated always as identity primary key,
  restaurant_id   uuid not null references public.restaurants (id) on delete cascade,
  item_key        text not null,
  day             date not null,
  orders          integer not null,
  created_at      timestamptz not null default now(),
  unique (restaurant_id, item_key, day)
);

create table public.findings (
  id              bigint generated always as identity primary key,
  restaurant_id   uuid not null references public.restaurants (id) on delete cascade,
  item_key        text not null,
  status          text not null,                         -- below_target | cost_up_ok | ok | loses_money | needs_review
  evidence        jsonb not null default '{}'::jsonb,
  updated_at      timestamptz not null default now(),
  created_at      timestamptz not null default now(),
  unique (restaurant_id, item_key)
);

create table public.decisions (
  id              bigint generated always as identity primary key,
  restaurant_id   uuid not null references public.restaurants (id) on delete cascade,
  local_id        integer not null,
  item_key        text,
  action          text not null,                         -- price_scenario | dismissed
  reason          text,
  user_id         uuid,
  decided_at      timestamptz not null,                  -- when the owner decided
  details         jsonb not null default '{}'::jsonb,    -- prices, monthly effect, undone
  created_at      timestamptz not null default now(),
  unique (restaurant_id, local_id)
);

create table public.activity_log (
  id              bigint generated always as identity primary key,
  restaurant_id   uuid not null references public.restaurants (id) on delete cascade,
  local_id        integer not null,
  run_id          uuid,                                  -- set for entries written by a Night Shift run
  "group"         text check ("group" in ('verified', 'needs_input', 'proposed')),
  message         text not null,
  evidence        jsonb not null default '{}'::jsonb,    -- {kind, params}: the numbers behind the message
  at              timestamptz not null,                  -- when it happened (overnight clock for demo runs)
  created_at      timestamptz not null default now(),
  unique (restaurant_id, local_id)
);
create index activity_log_run on public.activity_log (restaurant_id, run_id);

-- RLS on, no policies, no grants to the browser roles.
do $$
declare t text;
begin
  foreach t in array array['restaurants', 'ingredients', 'menu_items', 'recipes', 'invoices', 'invoice_lines',
                           'price_history', 'orders_daily', 'findings', 'decisions', 'activity_log']
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on table public.%I from anon, authenticated', t);
  end loop;
end $$;
