/** Tool workspaces fill everything below the header and own their own scrolling. */
export default function ToolsLayout({ children }: LayoutProps<"/">) {
  return <div className="flex flex-1 flex-col">{children}</div>;
}
