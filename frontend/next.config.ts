import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const nextConfig: NextConfig = {};

// No locale-prefixed routing: the language belongs to the user, not the URL (spec §2.1).
export default createNextIntlPlugin("./i18n/request.ts")(nextConfig);
