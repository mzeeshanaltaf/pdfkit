import { ToolPage } from "@/components/tool/tool-page";
import { toolMetadata } from "@/lib/tools";

export const metadata = toolMetadata("pdf-to-jpg");

export default function Page() {
  return <ToolPage toolId="pdf-to-jpg" />;
}
