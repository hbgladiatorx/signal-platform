"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { AppShell } from "@/components/nav/AppShell";
import { useApi } from "@/lib/useApi";
import type { Instrument } from "@/lib/types";

export default function InstrumentsPage() {
  const api = useApi();

  const { data, isLoading, error } = useQuery({
    queryKey: ["instruments"],
    queryFn: () => api.get<Instrument[]>("/instruments"),
  });

  return (
    <AppShell title="Instruments">
      <div className="rounded-lg border border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-base font-semibold text-navy-700">
            Tracked instruments
          </h2>
          <p className="mt-1 text-xs text-gray-500">
            Instruments currently ingested into the platform&rsquo;s market
            data store.
          </p>
        </div>

        {isLoading && (
          <div className="px-6 py-12 text-center text-sm text-gray-500">
            Loading…
          </div>
        )}

        {error && (
          <div className="px-6 py-12 text-center text-sm text-red-600">
            Failed to load instruments: {(error as Error).message}
          </div>
        )}

        {data && data.length === 0 && (
          <div className="px-6 py-12 text-center text-sm text-gray-500">
            No instruments configured.
          </div>
        )}

        {data && data.length > 0 && (
          <table className="w-full text-sm">
            <thead className="border-b border-gray-200 bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-6 py-2 font-medium">Symbol</th>
                <th className="px-6 py-2 font-medium">Asset class</th>
                <th className="px-6 py-2 font-medium">Venue</th>
                <th className="px-6 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.map((inst) => (
                <tr key={inst.id} className="hover:bg-gray-50">
                  <td className="px-6 py-3">
                    <Link
                      href={`/instruments/${encodeURIComponent(inst.canonical_symbol)}`}
                      className="font-mono text-navy-600 hover:underline"
                    >
                      {inst.canonical_symbol}
                    </Link>
                  </td>
                  <td className="px-6 py-3 text-gray-600">{inst.asset_class}</td>
                  <td className="px-6 py-3 text-gray-600">{inst.venue}</td>
                  <td className="px-6 py-3">
                    <span
                      className={
                        inst.active
                          ? "rounded-full bg-green-50 px-2 py-0.5 text-xs text-green-700"
                          : "rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500"
                      }
                    >
                      {inst.active ? "Active" : "Inactive"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </AppShell>
  );
}
