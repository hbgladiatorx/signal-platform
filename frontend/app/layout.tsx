import type { Metadata } from "next";
import { type ReactNode } from "react";

import { AuthProvider } from "@/components/auth/AuthProvider";

import "./globals.css";

export const metadata: Metadata = {
  title: "Signal Platform",
  description: "Multi-asset quantitative research and trading platform",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
