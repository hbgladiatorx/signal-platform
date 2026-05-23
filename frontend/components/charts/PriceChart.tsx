"use client";

import { useQuery } from "@tanstack/react-query";
import {
  createChart,
  CrosshairMode,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";

import { useApi } from "@/lib/useApi";
import { useWebSocket } from "@/lib/useWebSocket";
import { cn } from "@/lib/utils";
import {
  BAR_RESOLUTIONS,
  RESOLUTION_SECONDS,
  type Bar,
  type BarResolution,
  type BarsResponse,
  type WSServerMessage,
} from "@/lib/types";

interface PriceChartProps {
  canonicalSymbol: string;
}

// Lightweight-charts wants:
//   - candle/volume: { time: UTCTimestamp (seconds), open, high, low, close } / { time, value, color }
//   - line: { time, value }
// Bar timestamps from the API are ISO strings. Convert here.

function isoToUnixSeconds(iso: string): UTCTimestamp {
  return Math.floor(new Date(iso).getTime() / 1000) as UTCTimestamp;
}

function bucketStartSeconds(
  unixSeconds: number,
  resolution: BarResolution,
): UTCTimestamp {
  const intervalSec = RESOLUTION_SECONDS[resolution];
  return (Math.floor(unixSeconds / intervalSec) * intervalSec) as UTCTimestamp;
}

function barToCandlestick(bar: Bar): CandlestickData {
  return {
    time: isoToUnixSeconds(bar.bucket),
    open: parseFloat(bar.open),
    high: parseFloat(bar.high),
    low: parseFloat(bar.low),
    close: parseFloat(bar.close),
  };
}

function barToVolume(bar: Bar): HistogramData {
  const open = parseFloat(bar.open);
  const close = parseFloat(bar.close);
  const isUp = close >= open;
  return {
    time: isoToUnixSeconds(bar.bucket),
    value: parseFloat(bar.volume),
    // Lightweight charts allows per-bar color
    color: isUp ? "rgba(38, 166, 154, 0.5)" : "rgba(239, 83, 80, 0.5)",
  };
}

function barToVwap(bar: Bar): LineData | null {
  if (!bar.vwap) return null;
  return {
    time: isoToUnixSeconds(bar.bucket),
    value: parseFloat(bar.vwap),
  };
}

export function PriceChart({ canonicalSymbol }: PriceChartProps) {
  const api = useApi();
  const [resolution, setResolution] = useState<BarResolution>("1m");
  const [showVwap, setShowVwap] = useState(false);

  // Fetch historical bars
  const barsQuery = useQuery({
    queryKey: ["market", "bars", canonicalSymbol, resolution],
    queryFn: () =>
      api.get<BarsResponse>(
        `/market/bars?symbol=${encodeURIComponent(canonicalSymbol)}&resolution=${resolution}`,
      ),
  });

  // ----- Chart refs -----
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const vwapSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  // The most recent bar's state, so live trade events can update it
  const lastBarRef = useRef<CandlestickData | null>(null);
  const lastVolumeRef = useRef<HistogramData | null>(null);

  // ----- Create chart on mount -----
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 480,
      layout: {
        background: { color: "#ffffff" },
        textColor: "#374151",
      },
      grid: {
        vertLines: { color: "#f3f4f6" },
        horzLines: { color: "#f3f4f6" },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: "#e5e7eb",
      },
      rightPriceScale: {
        borderColor: "#e5e7eb",
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
    });

    const candle = chart.addCandlestickSeries({
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderUpColor: "#26a69a",
      borderDownColor: "#ef5350",
      wickUpColor: "#26a69a",
      wickDownColor: "#ef5350",
    });

    const volume = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "",
      color: "rgba(59, 130, 246, 0.4)",
    });
    // Pin the volume series to the bottom 20% of the chart
    volume.priceScale().applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    chartRef.current = chart;
    candleSeriesRef.current = candle;
    volumeSeriesRef.current = volume;

    // Resize observer
    const ro = new ResizeObserver(() => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
        });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      vwapSeriesRef.current = null;
      lastBarRef.current = null;
      lastVolumeRef.current = null;
    };
  }, []);

  // ----- VWAP series toggle -----
  useEffect(() => {
    if (!chartRef.current) return;
    if (showVwap && !vwapSeriesRef.current) {
      vwapSeriesRef.current = chartRef.current.addLineSeries({
        color: "#f59e0b",
        lineWidth: 2,
        title: "VWAP",
        priceLineVisible: false,
        lastValueVisible: true,
      });
      // Repopulate with current bars
      const data = (barsQuery.data?.bars ?? [])
        .map(barToVwap)
        .filter((p): p is LineData => p !== null);
      vwapSeriesRef.current.setData(data);
    }
    if (!showVwap && vwapSeriesRef.current) {
      chartRef.current.removeSeries(vwapSeriesRef.current);
      vwapSeriesRef.current = null;
    }
  }, [showVwap, barsQuery.data]);

  // ----- Populate chart when bars arrive -----
  useEffect(() => {
    if (!barsQuery.data || !candleSeriesRef.current || !volumeSeriesRef.current) {
      return;
    }
    const bars = barsQuery.data.bars;
    const candles = bars.map(barToCandlestick);
    const volumes = bars.map(barToVolume);
    candleSeriesRef.current.setData(candles);
    volumeSeriesRef.current.setData(volumes);

    if (vwapSeriesRef.current) {
      const vwap = bars.map(barToVwap).filter((p): p is LineData => p !== null);
      vwapSeriesRef.current.setData(vwap);
    }

    lastBarRef.current = candles[candles.length - 1] ?? null;
    lastVolumeRef.current = volumes[volumes.length - 1] ?? null;

    // Fit the view
    chartRef.current?.timeScale().fitContent();
  }, [barsQuery.data]);

  // ----- WebSocket: live trade updates  -----
  const handleMessage = useMemo(
    () => (msg: WSServerMessage) => {
      if (msg.type !== "trade") return;
      if (msg.symbol !== canonicalSymbol) return;
      if (!candleSeriesRef.current || !volumeSeriesRef.current) return;

      const price = parseFloat(msg.data.price);
      const qty = parseFloat(msg.data.quantity);
      const tsSec = Math.floor(new Date(msg.data.ts).getTime() / 1000);
      const bucketSec = bucketStartSeconds(tsSec, resolution);

      const last = lastBarRef.current;
      if (last && last.time === bucketSec) {
        // Update in-progress bar
        const updated: CandlestickData = {
          time: bucketSec,
          open: last.open,
          high: Math.max(last.high, price),
          low: Math.min(last.low, price),
          close: price,
        };
        candleSeriesRef.current.update(updated);
        lastBarRef.current = updated;

        const lastVol = lastVolumeRef.current;
        const updatedVol: HistogramData = {
          time: bucketSec,
          value: (lastVol?.value ?? 0) + qty,
          color:
            updated.close >= updated.open
              ? "rgba(38, 166, 154, 0.5)"
              : "rgba(239, 83, 80, 0.5)",
        };
        volumeSeriesRef.current.update(updatedVol);
        lastVolumeRef.current = updatedVol;
      } else {
        // New bucket: open a new bar
        const newBar: CandlestickData = {
          time: bucketSec,
          open: price,
          high: price,
          low: price,
          close: price,
        };
        candleSeriesRef.current.update(newBar);
        lastBarRef.current = newBar;

        const newVol: HistogramData = {
          time: bucketSec,
          value: qty,
          color: "rgba(38, 166, 154, 0.5)",
        };
        volumeSeriesRef.current.update(newVol);
        lastVolumeRef.current = newVol;
      }
    },
    [canonicalSymbol, resolution],
  );

  const ws = useWebSocket({
    onMessage: handleMessage,
  });

  // Subscribe / unsubscribe to this symbol as it changes
  useEffect(() => {
    if (ws.readyState === "open") {
      ws.send({ type: "subscribe", symbol: canonicalSymbol });
      return () => {
        if (ws.readyState === "open") {
          ws.send({ type: "unsubscribe", symbol: canonicalSymbol });
        }
      };
    }
  }, [ws.readyState, canonicalSymbol, ws]);

  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 px-5 py-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium uppercase tracking-wide text-gray-500">
            Price
          </h3>
          <span className="font-mono text-sm text-gray-700">
            {canonicalSymbol}
          </span>
          {ws.readyState === "open" && (
            <span className="inline-flex items-center gap-1 rounded-full bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-green-500" />
              Live
            </span>
          )}
          {ws.readyState !== "open" && (
            <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-500">
              {ws.readyState}
            </span>
          )}
        </div>

        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-gray-600">
            <input
              type="checkbox"
              checked={showVwap}
              onChange={(e) => setShowVwap(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-gray-300 text-amber-500 focus:ring-amber-400"
            />
            VWAP
          </label>

          <div className="flex items-center rounded-md border border-gray-200 bg-gray-50 p-0.5">
            {BAR_RESOLUTIONS.map((res) => (
              <button
                key={res}
                type="button"
                onClick={() => setResolution(res)}
                className={cn(
                  "rounded px-2.5 py-1 text-xs font-medium font-mono transition-colors",
                  resolution === res
                    ? "bg-navy-600 text-white shadow-sm"
                    : "text-gray-600 hover:text-gray-900",
                )}
              >
                {res}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="p-3">
        {barsQuery.isLoading && (
          <div className="flex h-[480px] items-center justify-center text-sm text-gray-500">
            Loading bars…
          </div>
        )}
        {barsQuery.error && (
          <div className="flex h-[480px] items-center justify-center text-sm text-red-600">
            {(barsQuery.error as Error).message}
          </div>
        )}
        {barsQuery.data && barsQuery.data.bars.length === 0 && (
          <div className="flex h-[480px] items-center justify-center text-sm text-gray-500">
            No bars in this window. Trades may be too sparse on this venue.
          </div>
        )}
        <div ref={containerRef} className="w-full" />
      </div>
    </div>
  );
}
