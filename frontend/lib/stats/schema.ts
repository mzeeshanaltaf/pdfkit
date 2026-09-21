/**
 * Mirrors `schema.sql` exactly (kept as a plain `.sql` file too, for anyone applying or
 * inspecting it by hand — e.g. the `psql -c "\d pdfkit.tool_runs"` check in the phase doc).
 * Imported as a template string rather than read from disk at runtime so it travels through
 * the `output: "standalone"` bundle like any other code, with nothing to file-trace.
 */
export const SCHEMA_SQL = `
create schema if not exists pdfkit;

create table if not exists pdfkit.tool_runs (
  id           bigserial   primary key,
  occurred_at  timestamptz not null default now(),
  tool         text        not null,
  runs_in      text        not null,
  outcome      text        not null,
  file_count   integer     not null default 0,
  page_count   integer,
  bytes_in     bigint      not null default 0,
  bytes_out    bigint      not null default 0,
  duration_ms  integer,
  error_code   text,
  visitor      text
);

create index if not exists tool_runs_occurred_at_idx on pdfkit.tool_runs (occurred_at desc);
create index if not exists tool_runs_tool_idx        on pdfkit.tool_runs (tool, occurred_at desc);

alter table pdfkit.tool_runs add column if not exists placement text;

create table if not exists pdfkit.sandbox_runs (
  id            bigserial   primary key,
  occurred_at   timestamptz not null default now(),
  sandbox_id    text        not null,
  operation     text        not null,
  outcome       text        not null,
  shard_index   integer     not null default 0,
  shard_total   integer     not null default 1,
  file_count    integer     not null default 0,
  alive_seconds numeric     not null default 0,
  cpu           integer     not null default 0,
  memory_gb     integer     not null default 0,
  disk_gb       integer     not null default 0,
  bytes_up      bigint      not null default 0,
  bytes_down    bigint      not null default 0
);

create index if not exists sandbox_runs_occurred_at_idx on pdfkit.sandbox_runs (occurred_at desc);
`;
