import { ToolPage } from "@/components/tool/tool-page";
import { toolMetadata } from "@/lib/tools";

export const metadata = toolMetadata("organize");

export default function Page() {
  return <ToolPage toolId="organize" />;
}
