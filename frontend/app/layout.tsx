import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import type { Metadata, Viewport } from "next";
import { MobileNav, Sidebar } from "@/components/sidebar";
import { THEME_SCRIPT } from "@/components/theme-toggle";
import { ToastProvider } from "@/components/toast";
import "./globals.css";

export const metadata: Metadata = {
  title: "Radar · Veille d'offres",
  description: "Agent de veille d'offres piloté par fichiers Markdown",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fbfbfd" },
    { media: "(prefers-color-scheme: dark)", color: "#16171c" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr" className={`${GeistSans.variable} ${GeistMono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="font-sans">
        <ToastProvider>
        <div className="flex min-h-dvh">
          <Sidebar />
          <main className="min-w-0 flex-1 px-5 pb-24 pt-8 md:px-10 md:pb-12 md:pt-10">
            <div className="animate-fade-in mx-auto max-w-6xl">{children}</div>
          </main>
        </div>
        <MobileNav />
        </ToastProvider>
      </body>
    </html>
  );
}
