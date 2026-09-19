import { ImageResponse } from "next/og";

import { APP_NAME, APP_TAGLINE, BRAND_HEX } from "@/lib/constants";
import { TOOLS } from "@/lib/tools";

/**
 * One share card for the whole site. Next inherits the nearest `opengraph-image`, so every
 * tool route picks this up without a file of its own — the per-route title and description
 * still come from `toolMetadata`, which is the part a preview actually shows as text.
 */
export const alt = `${APP_NAME} — ${APP_TAGLINE}`;
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "#ffffff",
          padding: 72,
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", fontSize: 44, fontWeight: 700, letterSpacing: "-0.03em" }}>
            <span style={{ color: BRAND_HEX }}>PDF</span>
            <span style={{ color: "#111111" }}>{APP_NAME.replace("PDF", "")}</span>
          </div>
          <div
            style={{
              marginTop: 32,
              fontSize: 76,
              fontWeight: 700,
              lineHeight: 1.1,
              letterSpacing: "-0.04em",
              color: "#111111",
              maxWidth: 900,
            }}
          >
            {APP_TAGLINE}
          </div>
        </div>

        {/* The tool names are the clearest statement of what the product is. */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12, maxWidth: 1000 }}>
          {TOOLS.map((tool) => (
            <div
              key={tool.id}
              style={{
                display: "flex",
                padding: "10px 20px",
                borderRadius: 999,
                background: "#f1f5f5",
                color: "#3f4a4a",
                fontSize: 26,
              }}
            >
              {tool.name}
            </div>
          ))}
        </div>

        <div style={{ display: "flex", fontSize: 26, color: BRAND_HEX }}>
          No account, no uploads for most tools, nothing kept.
        </div>
      </div>
    ),
    size,
  );
}
