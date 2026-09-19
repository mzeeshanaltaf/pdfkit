import { SiteFooter } from "@/components/layout/site-footer";

/**
 * Tool workspaces own the first viewport below the header, and `ToolPage` keeps that floor
 * with a `min-h` of its own. Below it sits each route's server-rendered content section,
 * then the footer.
 *
 * The footer used to be omitted here so the options sidebar could run full height. It still
 * does — the sidebar lives inside the workspace, which is a full viewport tall regardless of
 * what follows it — and the footer is now the only place a crawler on a tool page can find
 * all ten tool links as real HTML: the header's "All tools" menu is a Radix dropdown whose
 * items are not rendered until it is opened.
 *
 * The `main` landmark stays here rather than inside `ToolShell`, so every phase of the state
 * machine — dropzone, workspace, result and failure screen — sits inside one.
 */
export default function ToolsLayout({ children }: LayoutProps<"/">) {
  return (
    <>
      <main className="flex flex-1 flex-col">{children}</main>
      <SiteFooter />
    </>
  );
}
