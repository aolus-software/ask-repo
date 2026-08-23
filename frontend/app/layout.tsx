import type { Metadata } from "next";
import { Geist_Mono, Lexend } from "next/font/google";
import "./globals.css";

const lexend = Lexend({
  variable: "--font-lexend",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AskRepo",
  description: "Ask questions about a codebase and get grounded, cited answers.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // suppressHydrationWarning: the theme provider sets `class="dark"` on <html>
    // before paint, which the server render cannot know about.
    <html
      lang="en"
      className={`${lexend.variable} ${geistMono.variable} h-full`}
      suppressHydrationWarning
    >
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
