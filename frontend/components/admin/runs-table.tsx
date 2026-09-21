import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatBytes } from "@/lib/format";
import type { RecentRunRow } from "@/lib/stats/queries";
import { getTool } from "@/lib/tools";

import { formatDateTime, formatDuration } from "./format";

const OUTCOME_VARIANT = {
  done: "secondary",
  error: "destructive",
  cancelled: "outline",
} as const;

interface RunsTableProps {
  rows: RecentRunRow[];
}

export function RunsTable({ rows }: RunsTableProps) {
  if (rows.length === 0) {
    return <p className="py-8 text-center text-sm text-muted-foreground">No runs yet.</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Time</TableHead>
          <TableHead>Tool</TableHead>
          <TableHead>Runtime</TableHead>
          <TableHead>Placement</TableHead>
          <TableHead>Files</TableHead>
          <TableHead>Size in → out</TableHead>
          <TableHead>Duration</TableHead>
          <TableHead>Outcome</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row, index) => (
          <TableRow key={`${row.occurredAt}-${index}`}>
            <TableCell className="text-muted-foreground">{formatDateTime(row.occurredAt)}</TableCell>
            <TableCell className="font-medium">{getTool(row.tool).name}</TableCell>
            <TableCell className="text-muted-foreground">{row.runsIn}</TableCell>
            <TableCell className="text-muted-foreground">
              {row.placement === "sandbox" ? (
                <Badge variant="secondary">Cloud sandbox</Badge>
              ) : row.placement === "server" ? (
                <Badge variant="outline">VPS</Badge>
              ) : (
                "—"
              )}
            </TableCell>
            <TableCell>{row.fileCount}</TableCell>
            <TableCell className="text-muted-foreground">
              {formatBytes(row.bytesIn)} → {row.bytesOut > 0 ? formatBytes(row.bytesOut) : "—"}
            </TableCell>
            <TableCell className="text-muted-foreground">{formatDuration(row.durationMs)}</TableCell>
            <TableCell>
              <Badge variant={OUTCOME_VARIANT[row.outcome]}>
                {row.outcome}
                {row.errorCode ? ` · ${row.errorCode}` : ""}
              </Badge>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
