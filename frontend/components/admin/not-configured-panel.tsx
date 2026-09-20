import { DatabaseZap } from "lucide-react";

interface NotConfiguredPanelProps {
  reason?: string;
}

export function NotConfiguredPanel({ reason }: NotConfiguredPanelProps) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border py-16 text-center">
      <DatabaseZap className="size-8 text-muted-foreground" aria-hidden />
      <div>
        <p className="font-medium">Stats are not configured</p>
        <p className="mt-1 max-w-sm text-sm text-muted-foreground">
          {reason ?? "DATABASE_URL is not set, so no run has ever been recorded."}
        </p>
      </div>
    </div>
  );
}
