"use client";

import {
  createChart,
  ColorType,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

interface PriceChartProps {
  /** Initial historical points (oldest first) */
  history: { ts: string; mid: string | null }[];
  /** Live updates appended in real time */
  liveMidPrice: { ts: string; mid: number } | null;
  /** Connection status badge */
  isLive: boolean;
}

/**
 * Mid-price line chart powered by TradingView lightweight-charts.
 *
 * - Renders the historical points on first mount
 * - Appends each `liveMidPrice` update as it arrives
 * - Reacts to container resize by extending the chart to fill width
 */
export function PriceChart({
  history,
  liveMidPrice,
  isLive,
}: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const initializedRef = useRef(false);

  // Initialize the chart once
  useEffect(() => {
    if (!containerRef.current || initializedRef.current) return;
    initializedRef.current = true;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 320,
      layout: {
        background: { type: ColorType.Solid, color: "#ffffff" },
        textColor: "#374151",
        fontFamily: "Inter, system-ui, sans-serif",
      },
      grid: {
        vertLines: { color: "#f3f4f6" },
        horzLines: { color: "#f3f4f6" },
      },
      crosshair: { mode: 0 },
      rightPriceScale: { borderColor: "#e5e7eb" },
      timeScale: {
        borderColor: "#e5e7eb",
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const series = chart.addLineSeries({
      color: "#1e2761",
      lineWidth: 2,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });

    chartRef.current = chart;
    seriesRef.current = series;

    // Resize observer
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        chart.applyOptions({ width: entry.contentRect.width });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      initializedRef.current = false;
    };
  }, []);

  // Push history into the chart on first render or when history changes
  useEffect(() => {
    if (!seriesRef.current) return;
    const points: LineData[] = [];
    for (const p of history) {
      if (p.mid === null) continue;
      const mid = Number.parseFloat(p.mid);
      if (!Number.isFinite(mid)) continue;
      points.push({
        time: (new Date(p.ts).getTime() / 1000) as Time,
        value: mid,
      });
    }
    // Deduplicate timestamps (lightweight-charts requires strictly increasing)
    const seen = new Set<number>();
    const deduped = points.filter((p) => {
      const t = p.time as number;
      if (seen.has(t)) return false;
      seen.add(t);
      return true;
    });
    seriesRef.current.setData(deduped);
    if (chartRef.current && deduped.length > 0) {
      chartRef.current.timeScale().fitContent();
    }
  }, [history]);

  // Append live updates
  useEffect(() => {
    if (!seriesRef.current || !liveMidPrice) return;
    seriesRef.current.update({
      time: (new Date(liveMidPrice.ts).getTime() / 1000) as Time,
      value: liveMidPrice.mid,
    });
  }, [liveMidPrice]);

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium uppercase tracking-wide text-gray-500">
            Mid price (last hour, live)
          </h3>
        </div>
        <span
          className={
            isLive
              ? "inline-flex items-center gap-1.5 rounded-full bg-green-50 px-2.5 py-0.5 text-xs font-medium text-green-700"
              : "inline-flex items-center gap-1.5 rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-500"
          }
        >
          <span
            className={
              isLive
                ? "h-1.5 w-1.5 animate-pulse rounded-full bg-green-500"
                : "h-1.5 w-1.5 rounded-full bg-gray-400"
            }
          />
          {isLive ? "Live" : "Disconnected"}
        </span>
      </div>
      <div ref={containerRef} className="w-full" />
    </div>
  );
}
