"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/lib/useApi";
import { cn } from "@/lib/utils";
import { VENUE_SCHEMAS, type Instrument } from "@/lib/types";

/**
 * Data Sources section.
 *
 * For Phase 1 this is a status overview rather than a configuration panel —
 * the only adapter we have is Binance.US, configured via env. The page
 * shows what's connected, what's planned, and (for the active venue) how
 * many instruments it's serving.
 */
export function DataSourcesSection() {
  const api = useApi();

  const instrumentsQuery = useQuery({
    queryKey: ["settings", "data-sources", "instruments"],
    queryFn: async () => {
      const [active, inactive] = await Promise.all([
        api.get<Instrument[]>("/instruments?active=true"),
        api.get<Instrument[]>("/instruments?active=false"),
      ]);
      return [...active, ...inactive];
    },
  });

  const countsByVenue = new Map<string, { active: number; inactive: number }>();
  for (const inst of instrumentsQuery.data ?? []) {
    const c = countsByVenue.get(inst.venue) ?? { active: 0, inactive: 0 };
    if (inst.active) c.active++;
    else c.inactive++;
    countsByVenue.set(inst.venue, c);
  }

  return (
    <div className="space-y-4">
      {VENUE_SCHEMAS.map((venue) => {
        const counts = countsByVenue.get(venue.id);
        return (
          <div
            key={venue.id}
            className="rounded-lg border border-gray-200 bg-white p-6"
          >
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-3">
                  <h3 className="text-base font-semibold text-navy-700">
                    {venue.displayName}
                  </h3>
                  <StatusBadge status={venue.status} />
                </div>
                <p className="mt-2 max-w-2xl text-sm text-gray-600">
                  {venue.notes ?? "—"}
                </p>
              </div>

              <div className="text-right text-xs text-gray-500">
                <div className="uppercase tracking-wide">Venue code</div>
                <div className="mt-1 font-mono text-gray-700">{venue.id}</div>
              </div>
            </div>

            <div className="mt-5 grid grid-cols-2 gap-4 md:grid-cols-4">
              <Metric
                label="Asset classes"
                value={venue.supportedAssetClasses.join(", ")}
              />
              <Metric
                label="Active instruments"
                value={
                  venue.status === "available"
                    ? (counts?.active ?? 0).toString()
                    : "—"
                }
              />
              <Metric
                label="Inactive instruments"
                value={
                  venue.status === "available"
                    ? (counts?.inactive ?? 0).toString()
                    : "—"
                }
              />
              <Metric
                label="Status"
                value={
                  venue.status === "available" ? "Connected" : "Not connected"
                }
              />
            </div>
          </div>
        );
      })}

      <div className="rounded-lg border border-gray-200 bg-gray-50 p-5">
        <h3 className="text-sm font-semibold text-navy-700">
          Adding more venues
        </h3>
        <p className="mt-2 text-sm text-gray-600">
          Each venue requires a custom adapter (WebSocket subscription,
          message parsing, canonical symbol mapping). Phase 1 ships
          Binance.US. Phase 4 adds Alpaca for US equities and crypto.
          Custom venues can be added by writing a new adapter class under
          <code className="mx-1 rounded bg-white px-1 py-0.5 font-mono text-xs">
            packages/adapters
          </code>
          and registering it.
        </p>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: "available" | "coming_soon" }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium",
        status === "available"
          ? "bg-green-50 text-green-700"
          : "bg-gray-100 text-gray-500",
      )}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          status === "available" ? "animate-pulse bg-green-500" : "bg-gray-400",
        )}
      />
      {status === "available" ? "Available" : "Coming soon"}
    </span>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-gray-500">
        {label}
      </div>
      <div className="mt-1 text-sm font-medium text-gray-800">{value}</div>
    </div>
  );
}
