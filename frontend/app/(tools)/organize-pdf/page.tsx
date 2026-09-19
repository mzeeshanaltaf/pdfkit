import { ToolJsonLd } from "@/components/seo/json-ld";
import { ToolSeoSection } from "@/components/seo/tool-seo-section";
import { ToolPage } from "@/components/tool/tool-page";
import { toolMetadata } from "@/lib/tools";

export const metadata = toolMetadata("organize");

export default function Page() {
  return (
    <>
      <ToolPage toolId="organize" />
      <ToolSeoSection toolId="organize" />
      <ToolJsonLd toolId="organize" />
    </>
  );
}
