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
