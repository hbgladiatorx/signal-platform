import { createFileRoute } from "@tanstack/react-router";
import { Card } from "@/components/ui/card";
import { TVMarketOverview } from "@/components/common/TVMarketOverview";
import { NewsTicker } from "@/components/common/NewsTicker";
import { useAssetFilter } from "@/lib/asset-filter";

export const Route = createFileRoute("/app/markets")({
  head: () => ({ meta: [{ title: "Markets — Bayn" }] }),
  component: MarketsPage,
});

function MarketsPage() {
  const { assetClass } = useAssetFilter();
  return (
    <div className="mx-auto max-w-5xl space-y-8 p-4 md:p-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Markets {assetClass !== "all" && <span className="text-muted-foreground">· {assetClass}</span>}
        </h1>
        <p className="text-sm text-muted-foreground">A broad market read and the news wire from your sources.</p>
      </div>

      <section className="space-y-3">
        <h2 className="text-sm font-medium uppercase tracking-[0.16em] text-muted-foreground">News wire</h2>
        <NewsTicker />
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium uppercase tracking-[0.16em] text-muted-foreground">Market overview</h2>
        <Card className="overflow-hidden border-border bg-elevated p-0">
          <TVMarketOverview height={520} />
        </Card>
      </section>
    </div>
  );
}
