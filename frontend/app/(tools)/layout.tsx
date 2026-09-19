/**
 * Tool workspaces fill everything below the header and own their own scrolling. The `main`
 * landmark lives here rather than inside `ToolShell`, so every phase of the state machine —
 * the dropzone, the workspace, the result and the failure screen — sits inside one.
 */
export default function ToolsLayout({ children }: LayoutProps<"/">) {
  return <main className="flex flex-1 flex-col">{children}</main>;
}
