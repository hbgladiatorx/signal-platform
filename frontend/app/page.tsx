"use client";

import { useAuth0 } from "@auth0/auth0-react";
import { BarChart3 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { LoginButton } from "@/components/auth/LoginButton";

export default function HomePage() {
  const { isAuthenticated, isLoading } = useAuth0();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.replace("/dashboard");
    }
  }, [isLoading, isAuthenticated, router]);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center px-4">
      <div className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-8 shadow-sm">
        <div className="mb-6 flex items-center gap-3">
          <div className="rounded-lg bg-navy-600 p-2">
            <BarChart3 className="h-6 w-6 text-gold-500" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-navy-700">
              Signal Platform
            </h1>
            <p className="text-xs text-gray-500">Quantitative research</p>
          </div>
        </div>

        <p className="mb-6 text-sm text-gray-600">
          A multi-asset platform for research, backtesting, and disciplined
          deployment of trading strategies.
        </p>

        <div className="flex justify-end">
          <LoginButton />
        </div>
      </div>

      <p className="mt-6 text-center text-xs text-gray-400">
        Educational use only — not investment advice.
      </p>
    </main>
  );
}
