import type { MetadataRoute } from "next";

/**
 * Web app manifest, served at `/manifest.webmanifest` with its `<link>` tag added
 * automatically by Next's metadata handling.
 *
 * The two colours are the only hex values outside `globals.css`
 * (`.claude/rules/design-system.md` §2), and they have to be literals: a manifest is
 * read by the browser's own chrome long before any stylesheet loads, so it cannot
 * reference a CSS token. They mirror the light-theme `--primary` and `--background`
 * and must be moved with them.
 *
 * The icons live in `public/` rather than being `app/icon*.png` conventions: Next
 * serves generated icon routes under hashed URLs, and a manifest needs stable ones.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "AskRepo",
    short_name: "AskRepo",
    description: "Ask questions about a codebase and get grounded, cited answers.",
    start_url: "/",
    display: "standalone",
    theme_color: "#615fff",
    background_color: "#f1f5f9",
    icons: [
      { src: "/android-chrome-192x192.png", sizes: "192x192", type: "image/png" },
      { src: "/android-chrome-512x512.png", sizes: "512x512", type: "image/png" },
    ],
  };
}
