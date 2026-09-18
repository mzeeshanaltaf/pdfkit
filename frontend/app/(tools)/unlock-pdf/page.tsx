import { ToolPage } from "@/components/tool/tool-page";
import { toolMetadata } from "@/lib/tools";

export const metadata = toolMetadata("unlock");

export default function Page() {
  return <ToolPage toolId="unlock" />;
}
