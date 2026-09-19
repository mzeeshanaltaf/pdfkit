import { ToolJsonLd } from "@/components/seo/json-ld";
import { ToolSeoSection } from "@/components/seo/tool-seo-section";
import { ToolPage } from "@/components/tool/tool-page";
import { toolMetadata } from "@/lib/tools";

export const metadata = toolMetadata("ocr");

export default function Page() {
  return (
    <>
      <ToolPage toolId="ocr" />
      <ToolSeoSection toolId="ocr" />
      <ToolJsonLd toolId="ocr" />
    </>
  );
}
