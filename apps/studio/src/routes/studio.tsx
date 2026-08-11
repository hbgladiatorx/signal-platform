import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/layout/AppShell";
import { AuthGate } from "@/components/AuthGate";
import { StudioGate } from "@/components/StudioGate";
import { ServerHealthWidget } from "@/components/common/ServerHealthWidget";

export const Route = createFileRoute("/studio")({
  component: () => (
    <AuthGate>
      <StudioGate>
        <AppShell mode="studio" />
        <ServerHealthWidget />
      </StudioGate>
    </AuthGate>
  ),
});
