// Finnhub-backed server functions for live market data + news.
// All calls are server-only so the API key never ships to the client.
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";

const BASE = "https://finnhub.io/api/v1";

// In-memory cache to stay inside Finnhub's free-tier rate limits.
type CacheEntry<T> = { value: T; expires: number };
const cache = new Map<string, CacheEntry<unknown>>();
function cached<T>(key: string, ttlMs: number, get: () => Promise<T>): Promise<T> {
  const hit = cache.get(key);
  const now = Date.now();
  if (hit && hit.expires > now) return Promise.resolve(hit.value as T);
  return get().then((value) => {
    cache.set(key, { value, expires: now + ttlMs });
    return value;
  });
}

function getKey(): string {
  const key = process.env.FINNHUB_API_KEY;
  if (!key) throw new Error("FINNHUB_API_KEY is not configured");
  return key;
}

async function fh<T>(path: string): Promise<T> {
  const sep = path.includes("?") ? "&" : "?";
  const res = await fetch(`${BASE}${path}${sep}token=${getKey()}`);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Finnhub ${res.status}: ${body.slice(0, 200)}`);
  }
  return (await res.json()) as T;
}

/* -------------------- Ticker validation -------------------- */

export type TickerInfo = {
  valid: boolean;
  symbol: string;
  description: string | null;
  exchange: string | null;
  type: string | null;
  price: number | null;
};

export const validateTicker = createServerFn({ method: "POST" })
  .inputValidator(z.object({ symbol: z.string().min(1).max(20) }))
  .handler(async ({ data }): Promise<TickerInfo> => {
    const sym = data.symbol.trim().toUpperCase();
    return cached(`validate:${sym}`, 60_000, async () => {
      try {
        const search = await fh<{
          count: number;
          result: Array<{ symbol: string; description: string; type: string }>;
        }>(`/search?q=${encodeURIComponent(sym)}`);
        const match =
          search.result?.find((r) => r.symbol.toUpperCase() === sym) ??
          search.result?.find((r) => r.symbol.toUpperCase().endsWith(sym)) ??
          null;
        const quote = await fh<{ c: number; d: number; dp: number }>(
          `/quote?symbol=${encodeURIComponent(sym)}`
        );
        const hasPrice = typeof quote.c === "number" && quote.c > 0;
        if (!match && !hasPrice) {
          return { valid: false, symbol: sym, description: null, exchange: null, type: null, price: null };
        }
        return {
          valid: true,
          symbol: match?.symbol ?? sym,
          description: match?.description ?? null,
          exchange: null,
          type: match?.type ?? null,
          price: hasPrice ? quote.c : null,
        };
      } catch {
        return { valid: false, symbol: sym, description: null, exchange: null, type: null, price: null };
      }
    });
  });

/* -------------------- Quotes -------------------- */

export type LiveQuote = {
  symbol: string;
  price: number;
  change: number;
  changePct: number;
  high: number;
  low: number;
  open: number;
  prevClose: number;
};

export const getQuotes = createServerFn({ method: "POST" })
  .inputValidator(z.object({ symbols: z.array(z.string().min(1).max(20)).max(40) }))
  .handler(async ({ data }): Promise<LiveQuote[]> => {
    const syms = Array.from(new Set(data.symbols.map((s) => s.trim().toUpperCase()))).filter(Boolean);
    const results = await Promise.all(
      syms.map(async (symbol) =>
        cached(`quote:${symbol}`, 30_000, async () => {
          try {
            const q = await fh<{
              c: number; d: number; dp: number; h: number; l: number; o: number; pc: number;
            }>(`/quote?symbol=${encodeURIComponent(symbol)}`);
            if (!q || typeof q.c !== "number" || q.c === 0) return null;
            return {
              symbol,
              price: q.c,
              change: q.d ?? 0,
              changePct: q.dp ?? 0,
              high: q.h ?? q.c,
              low: q.l ?? q.c,
              open: q.o ?? q.c,
              prevClose: q.pc ?? q.c,
            } satisfies LiveQuote;
          } catch {
            return null;
          }
        })
      )
    );
    return results.filter((x): x is LiveQuote => x !== null);
  });

/* -------------------- News -------------------- */

export type NewsItem = {
  id: string;
  headline: string;
  summary: string;
  source: string;
  url: string;
  datetime: number; // unix seconds
  image: string | null;
  category: string;
  symbol: string | null;
};

function fmtDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export const getMarketNews = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      category: z.enum(["general", "forex", "crypto", "merger"]).default("general"),
    }).optional()
  )
  .handler(async ({ data }): Promise<NewsItem[]> => {
    const category = data?.category ?? "general";
    return cached(`news:${category}`, 120_000, async () => {
      try {
        const items = await fh<Array<{
          id: number; headline: string; summary: string; source: string;
          url: string; datetime: number; image: string; category: string; related: string;
        }>>(`/news?category=${category}`);
        return (items ?? []).slice(0, 50).map((n) => ({
          id: String(n.id),
          headline: n.headline,
          summary: n.summary ?? "",
          source: n.source ?? "Finnhub",
          url: n.url,
          datetime: n.datetime,
          image: n.image || null,
          category: n.category || category,
          symbol: n.related?.split(",")[0]?.trim() || null,
        }));
      } catch {
        return [];
      }
    });
  });

export const getCompanyNews = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      symbol: z.string().min(1).max(20),
      days: z.number().int().min(1).max(30).default(7),
    })
  )
  .handler(async ({ data }): Promise<NewsItem[]> => {
    const sym = data.symbol.trim().toUpperCase();
    const to = new Date();
    const from = new Date(Date.now() - data.days * 86_400_000);
    return cached(`cnews:${sym}:${data.days}`, 120_000, async () => {
      try {
        const items = await fh<Array<{
          id: number; headline: string; summary: string; source: string;
          url: string; datetime: number; image: string; category: string; related: string;
        }>>(`/company-news?symbol=${encodeURIComponent(sym)}&from=${fmtDate(from)}&to=${fmtDate(to)}`);
        return (items ?? []).slice(0, 30).map((n) => ({
          id: String(n.id),
          headline: n.headline,
          summary: n.summary ?? "",
          source: n.source ?? "Finnhub",
          url: n.url,
          datetime: n.datetime,
          image: n.image || null,
          category: n.category || "company",
          symbol: sym,
        }));
      } catch {
        return [];
      }
    });
  });

/* -------------------- Symbol search (autocomplete) -------------------- */

export type SymbolMatch = { symbol: string; description: string; type: string };

export const searchSymbols = createServerFn({ method: "POST" })
  .inputValidator(z.object({ query: z.string().min(1).max(40) }))
  .handler(async ({ data }): Promise<SymbolMatch[]> => {
    const q = data.query.trim();
    return cached(`search:${q.toUpperCase()}`, 60_000, async () => {
      try {
        const res = await fh<{ result: Array<{ symbol: string; description: string; type: string }> }>(
          `/search?q=${encodeURIComponent(q)}`
        );
        return (res.result ?? []).slice(0, 8).map((r) => ({
          symbol: r.symbol,
          description: r.description,
          type: r.type,
        }));
      } catch {
        return [];
      }
    });
  });

/* -------------------- Config status -------------------- */

/** Whether FINNHUB_API_KEY is present in the frontend container (no value leaked). */
export const getFinnhubStatus = createServerFn({ method: "GET" }).handler(
  async (): Promise<{ configured: boolean }> => ({
    configured: !!process.env.FINNHUB_API_KEY,
  }),
);
