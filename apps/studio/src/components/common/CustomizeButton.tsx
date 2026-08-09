import { Link } from "@tanstack/react-router";
import { Sliders } from "lucide-react";
import { Button } from "@/components/ui/button";

/** Small "Customize" pill that appears in the home headers of both
 *  trader and studio. Opens the corresponding customize surface. */
export function CustomizeButton({ mode }: { mode: "trader" | "studio" }) {
  if (mode === "trader") {
    return (
      <Button asChild variant="outline" size="sm" className="border-cyan/40 text-cyan hover:bg-cyan/10">
        <Link to="/app/customize" search={{ tab: "markets" }}>
          <Sliders className="mr-1.5 size-3.5" /> Customize
        </Link>
      </Button>
    );
  }
  return (
    <Button asChild variant="outline" size="sm" className="border-violet/40 text-violet hover:bg-violet/10">
      <Link to="/studio/settings">
        <Sliders className="mr-1.5 size-3.5" /> Customize Studio
      </Link>
    </Button>
  );
}
