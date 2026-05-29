import { useEffect, useRef, useState } from "react";

/** Generic loader for TradingView "embed-widget-*" scripts.
 *  Each widget is initialised by appending a <script src="..."> with a JSON
 *  config payload as its innerText. The widget mounts itself inside the
 *  surrounding .tradingview-widget-container element.
 *
 *  Uses IntersectionObserver to defer mounting until the widget is in view. */
export function TVEmbedWidget({
  scriptSrc,
  config,
  height = 400,
  className,
  lazy = true,
}: {
  scriptSrc: string;
  config: Record<string, unknown>;
  height?: number | string;
  className?: string;
  lazy?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const widgetRef = useRef<HTMLDivElement | null>(null);
  const [shouldMount, setShouldMount] = useState(!lazy);

  useEffect(() => {
    if (shouldMount || !lazy || !containerRef.current) return;
    const el = containerRef.current;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setShouldMount(true);
          io.disconnect();
        }
      },
      { rootMargin: "200px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [shouldMount, lazy]);

  useEffect(() => {
    if (!shouldMount || !widgetRef.current) return;
    const host = widgetRef.current;
    host.innerHTML = "";
    const script = document.createElement("script");
    script.src = scriptSrc;
    script.type = "text/javascript";
    script.async = true;
    script.innerHTML = JSON.stringify(config);
    host.appendChild(script);
    return () => { host.innerHTML = ""; };
  }, [shouldMount, scriptSrc, JSON.stringify(config)]);

  return (
    <div
      ref={containerRef}
      className={`tradingview-widget-container ${className ?? ""}`}
      style={{ height: typeof height === "number" ? `${height}px` : height, width: "100%" }}
    >
      <div ref={widgetRef} className="tradingview-widget-container__widget" style={{ height: "100%", width: "100%" }} />
    </div>
  );
}
