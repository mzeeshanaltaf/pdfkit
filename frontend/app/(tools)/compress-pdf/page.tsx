import { ToolJsonLd } from "@/components/seo/json-ld";
import { ToolSeoSection } from "@/components/seo/tool-seo-section";
import { ToolPage } from "@/components/tool/tool-page";
import { toolMetadata } from "@/lib/tools";

export const metadata = toolMetadata("compress");

export default function Page() {
  return (
    <>
      <ToolPage toolId="compress" />
      <ToolSeoSection toolId="compress" />
      <ToolJsonLd toolId="compress" />
    </>
  );
}
