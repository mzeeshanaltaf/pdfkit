create schema if not exists pdfkit;

create table if not exists pdfkit.tool_runs (
  id           bigserial   primary key,
  occurred_at  timestamptz not null default now(),
  tool         text        not null,   -- ToolId, e.g. 'compress', 'page-numbers'
  runs_in      text        not null,   -- 'browser' | 'backend' | 'hybrid'
  outcome      text        not null,   -- 'done' | 'error' | 'cancelled'
  file_count   integer     not null default 0,
  page_count   integer,                -- null when a file list was still loading
  bytes_in     bigint      not null default 0,
  bytes_out    bigint      not null default 0,
  duration_ms  integer,
  error_code   text,                   -- ApiError.code, or a PdfLoadError kind
  visitor      text                    -- sha256(ip + daily salt), never an IP
);

create index if not exists tool_runs_occurred_at_idx on pdfkit.tool_runs (occurred_at desc);
create index if not exists tool_runs_tool_idx        on pdfkit.tool_runs (tool, occurred_at desc);

-- 'create table if not exists' runs once per process and will not add a column
-- to an already-deployed tool_runs, so this ships as its own idempotent
-- statement rather than as part of the create above.
alter table pdfkit.tool_runs add column if not exists placement text;   -- 'server' | 'sandbox', null until Phase 4 writes it

create table if not exists pdfkit.sandbox_runs (
  id            bigserial   primary key,
  occurred_at   timestamptz not null default now(),
  sandbox_id    text        not null,
  operation     text        not null,   -- ocr | word | markdown | compress
  outcome       text        not null,   -- ok | failed | abandoned | cancelled
  shard_index   integer     not null default 0,
  shard_total   integer     not null default 1,
  file_count    integer     not null default 0,
  alive_seconds numeric     not null default 0,
  cpu           integer     not null default 0,   -- vCPU the snapshot carries
  memory_gb     integer     not null default 0,
  disk_gb       integer     not null default 0,
  bytes_up      bigint      not null default 0,
  bytes_down    bigint      not null default 0
);

create index if not exists sandbox_runs_occurred_at_idx on pdfkit.sandbox_runs (occurred_at desc);
