"use client";

import { useAuth0 } from "@auth0/auth0-react";

import { LogoutButton } from "@/components/auth/LogoutButton";

export function Header({ title }: { title: string }) {
  const { user } = useAuth0();

  return (
    <header className="flex h-14 items-center justify-between border-b border-gray-200 bg-white px-6">
      <h1 className="text-base font-semibold text-navy-700">{title}</h1>

      <div className="flex items-center gap-4">
        {user?.email && (
          <span className="text-sm text-gray-600">{user.email}</span>
        )}
        <LogoutButton />
      </div>
    </header>
  );
}
