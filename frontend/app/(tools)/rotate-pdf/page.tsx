import { ToolPage } from "@/components/tool/tool-page";
import { toolMetadata } from "@/lib/tools";

export const metadata = toolMetadata("rotate");

export default function Page() {
  return <ToolPage toolId="rotate" />;
}
