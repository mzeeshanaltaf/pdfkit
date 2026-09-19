import { ToolJsonLd } from "@/components/seo/json-ld";
import { ToolSeoSection } from "@/components/seo/tool-seo-section";
import { ToolPage } from "@/components/tool/tool-page";
import { toolMetadata } from "@/lib/tools";

export const metadata = toolMetadata("pdf-to-markdown");

export default function Page() {
  return (
    <>
      <ToolPage toolId="pdf-to-markdown" />
      <ToolSeoSection toolId="pdf-to-markdown" />
      <ToolJsonLd toolId="pdf-to-markdown" />
    </>
  );
}
