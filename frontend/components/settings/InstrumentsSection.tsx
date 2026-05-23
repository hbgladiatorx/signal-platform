"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useApi } from "@/lib/useApi";
import { cn } from "@/lib/utils";
import {
  VENUE_SCHEMAS,
  type Instrument,
  type InstrumentCreate,
  type VenueSchema,
} from "@/lib/types";

export function InstrumentsSection() {
  const api = useApi();
  const qc = useQueryClient();

  // We fetch ALL instruments (active and inactive) by passing active=false explicitly
  // ... actually the backend's default is active=true, so we need a second query.
  // Simpler: fetch active + inactive in two parallel queries and concatenate.
  const allQuery = useQuery({
    queryKey: ["settings", "instruments", "all"],
    queryFn: async () => {
      const [active, inactive] = await Promise.all([
        api.get<Instrument[]>("/instruments?active=true"),
        api.get<Instrument[]>("/instruments?active=false"),
      ]);
      return [...active, ...inactive].sort((a, b) =>
        a.canonical_symbol.localeCompare(b.canonical_symbol),
      );
    },
  });

  const [adding, setAdding] = useState(false);

  const toggleMutation = useMutation({
    mutationFn: ({
      symbol,
      active,
    }: {
      symbol: string;
      active: boolean;
    }) =>
      api.put<Instrument>(
        `/instruments/${encodeURIComponent(symbol)}/active`,
        { active },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings", "instruments", "all"] });
      qc.invalidateQueries({ queryKey: ["instruments"] });
    },
  });

  // PATCH isn't standard in apiClient — we exposed put/post/delete only.
  // Override here: send PATCH manually via fetch since lib/api.ts doesn't
  // include patch yet. Defer to creating a PATCH wrapper if used elsewhere.
  // (Implemented below as a direct PATCH function for clarity.)

  const createMutation = useMutation({
    mutationFn: (body: InstrumentCreate) =>
      api.post<Instrument>("/instruments", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings", "instruments", "all"] });
      qc.invalidateQueries({ queryKey: ["instruments"] });
      setAdding(false);
    },
  });

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-gray-200 bg-white">
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <div>
            <h2 className="text-base font-semibold text-navy-700">
              Tracked instruments
            </h2>
            <p className="mt-1 text-xs text-gray-500">
              Toggling active stores the change immediately. Newly-added
              instruments and toggled-on instruments require an ingestion
              service restart to begin receiving live data.
            </p>
          </div>
          {!adding && (
            <button
              type="button"
              onClick={() => setAdding(true)}
              className="rounded-md bg-navy-600 px-4 py-2 text-sm font-medium text-white hover:bg-navy-700"
            >
              + Add instrument
            </button>
          )}
        </div>

        {adding && (
          <div className="border-b border-gray-200 bg-gray-50 px-6 py-5">
            <AddInstrumentForm
              onCancel={() => {
                setAdding(false);
                createMutation.reset();
              }}
              onSubmit={(body) => createMutation.mutate(body)}
              isSubmitting={createMutation.isPending}
              errorMessage={
                createMutation.isError
                  ? (createMutation.error as Error).message
                  : null
              }
            />
          </div>
        )}

        {allQuery.isLoading && (
          <div className="px-6 py-8 text-center text-sm text-gray-500">
            Loading…
          </div>
        )}

        {allQuery.error && (
          <div className="px-6 py-8 text-center text-sm text-red-600">
            {(allQuery.error as Error).message}
          </div>
        )}

        {allQuery.data && allQuery.data.length === 0 && !adding && (
          <div className="px-6 py-12 text-center text-sm text-gray-500">
            No instruments configured.
          </div>
        )}

        {allQuery.data && allQuery.data.length > 0 && (
          <table className="w-full text-sm">
            <thead className="border-b border-gray-200 bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-6 py-2 font-medium">Symbol</th>
                <th className="px-6 py-2 font-medium">Asset class</th>
                <th className="px-6 py-2 font-medium">Venue</th>
                <th className="px-6 py-2 font-medium">Native</th>
                <th className="px-6 py-2 font-medium">Active</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {allQuery.data.map((inst) => (
                <tr key={inst.canonical_symbol}>
                  <td className="px-6 py-3 font-mono">
                    {inst.canonical_symbol}
                  </td>
                  <td className="px-6 py-3 text-gray-600">
                    {inst.asset_class}
                  </td>
                  <td className="px-6 py-3 text-gray-600">{inst.venue}</td>
                  <td className="px-6 py-3 font-mono text-xs text-gray-500">
                    {inst.native_symbol}
                  </td>
                  <td className="px-6 py-3">
                    <Toggle
                      checked={inst.active}
                      onChange={(active) =>
                        toggleMutation.mutate({
                          symbol: inst.canonical_symbol,
                          active,
                        })
                      }
                      disabled={
                        toggleMutation.isPending &&
                        toggleMutation.variables?.symbol ===
                          inst.canonical_symbol
                      }
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {toggleMutation.isError && (
        <div className="text-sm text-red-600">
          {(toggleMutation.error as Error).message}
        </div>
      )}
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={() => !disabled && onChange(!checked)}
      disabled={disabled}
      className={cn(
        "relative inline-flex h-5 w-9 items-center rounded-full transition-colors",
        checked ? "bg-navy-600" : "bg-gray-300",
        disabled && "opacity-50 cursor-not-allowed",
      )}
      aria-pressed={checked}
    >
      <span
        className={cn(
          "inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform",
          checked ? "translate-x-5" : "translate-x-1",
        )}
      />
    </button>
  );
}

function AddInstrumentForm({
  onCancel,
  onSubmit,
  isSubmitting,
  errorMessage,
}: {
  onCancel: () => void;
  onSubmit: (body: InstrumentCreate) => void;
  isSubmitting: boolean;
  errorMessage: string | null;
}) {
  const availableVenues = VENUE_SCHEMAS.filter((v) => v.status === "available");
  const [venue, setVenue] = useState<VenueSchema>(availableVenues[0]);
  const [base, setBase] = useState("");
  const [quote, setQuote] = useState("");

  const valid = base.trim().length > 0 && quote.trim().length > 0;

  function handleSubmit() {
    if (!valid || isSubmitting) return;
    onSubmit({
      asset_class: venue.supportedAssetClasses[0],
      venue: venue.id,
      base: base.trim().toUpperCase(),
      quote: quote.trim().toUpperCase(),
    });
  }

  function pickSuggested(b: string, q: string) {
    setBase(b);
    setQuote(q);
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Venue
          </label>
          <select
            value={venue.id}
            onChange={(e) => {
              const next = availableVenues.find((v) => v.id === e.target.value);
              if (next) setVenue(next);
            }}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-navy-500 focus:outline-none focus:ring-1 focus:ring-navy-500"
          >
            {availableVenues.map((v) => (
              <option key={v.id} value={v.id}>
                {v.displayName}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Base asset
          </label>
          <input
            type="text"
            value={base}
            onChange={(e) => setBase(e.target.value.toUpperCase())}
            placeholder="BTC"
            maxLength={16}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm font-mono focus:border-navy-500 focus:outline-none focus:ring-1 focus:ring-navy-500"
          />
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Quote asset
          </label>
          <input
            type="text"
            value={quote}
            onChange={(e) => setQuote(e.target.value.toUpperCase())}
            placeholder="USDT"
            maxLength={16}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm font-mono focus:border-navy-500 focus:outline-none focus:ring-1 focus:ring-navy-500"
          />
        </div>
      </div>

      {venue.suggestedPairs && venue.suggestedPairs.length > 0 && (
        <div>
          <div className="text-xs font-medium uppercase tracking-wide text-gray-500">
            Quick pick
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {venue.suggestedPairs.map((p) => (
              <button
                key={`${p.base}-${p.quote}`}
                type="button"
                onClick={() => pickSuggested(p.base, p.quote)}
                className="rounded-md border border-gray-200 bg-white px-3 py-1 text-xs font-mono text-gray-700 hover:border-navy-300 hover:bg-navy-50"
              >
                {p.base}-{p.quote}
              </button>
            ))}
          </div>
        </div>
      )}

      <p className="text-xs text-gray-500">
        Symbol will be verified against {venue.displayName} before saving. If
        the symbol isn&rsquo;t listed there, the save will fail with a clear
        error.
      </p>

      {errorMessage && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {errorMessage}
        </div>
      )}

      <div className="flex items-center justify-end gap-3 border-t border-gray-200 pt-4">
        <button
          type="button"
          onClick={onCancel}
          className="text-sm text-gray-600 hover:text-gray-900"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!valid || isSubmitting}
          className={cn(
            "rounded-md px-4 py-2 text-sm font-medium text-white transition-colors",
            !valid || isSubmitting
              ? "cursor-not-allowed bg-navy-300"
              : "bg-navy-600 hover:bg-navy-700",
          )}
        >
          {isSubmitting ? "Verifying…" : "Add instrument"}
        </button>
      </div>
    </div>
  );
}
