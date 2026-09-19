import { ToolJsonLd } from "@/components/seo/json-ld";
import { ToolSeoSection } from "@/components/seo/tool-seo-section";
import { ToolPage } from "@/components/tool/tool-page";
import { toolMetadata } from "@/lib/tools";

export const metadata = toolMetadata("unlock");

export default function Page() {
  return (
    <>
      <ToolPage toolId="unlock" />
      <ToolSeoSection toolId="unlock" />
      <ToolJsonLd toolId="unlock" />
    </>
  );
}
