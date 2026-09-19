import { ToolJsonLd } from "@/components/seo/json-ld";
import { ToolSeoSection } from "@/components/seo/tool-seo-section";
import { ToolPage } from "@/components/tool/tool-page";
import { toolMetadata } from "@/lib/tools";

export const metadata = toolMetadata("pdf-to-jpg");

export default function Page() {
  return (
    <>
      <ToolPage toolId="pdf-to-jpg" />
      <ToolSeoSection toolId="pdf-to-jpg" />
      <ToolJsonLd toolId="pdf-to-jpg" />
    </>
  );
}
