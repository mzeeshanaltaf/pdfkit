import { SiteFooter } from "@/components/layout/site-footer";

/** Marketing surfaces get the footer; tool workspaces do not, so the sidebar can run full height. */
export default function SiteLayout({ children }: LayoutProps<"/">) {
  return (
    <>
      <div className="flex flex-1 flex-col">{children}</div>
      <SiteFooter />
    </>
  );
}
