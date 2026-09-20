import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { FailureRow } from "@/lib/stats/queries";
import { getTool } from "@/lib/tools";

interface FailuresTableProps {
  rows: FailureRow[];
}

export function FailuresTable({ rows }: FailuresTableProps) {
  if (rows.length === 0) {
    return <p className="py-8 text-center text-sm text-muted-foreground">No failures — nice.</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Tool</TableHead>
          <TableHead>Error code</TableHead>
          <TableHead className="text-right">Count</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={`${row.tool}-${row.errorCode}`}>
            <TableCell className="font-medium">{getTool(row.tool).name}</TableCell>
            <TableCell className="text-muted-foreground">{row.errorCode}</TableCell>
            <TableCell className="text-right tabular-nums">{row.count}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
