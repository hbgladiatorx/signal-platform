import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/layout/AppShell";
import { AuthGate } from "@/components/AuthGate";
import { StudioGate } from "@/components/StudioGate";

export const Route = createFileRoute("/studio")({
  component: () => (
    <AuthGate>
      <StudioGate>
        <AppShell mode="studio" />
      </StudioGate>
    </AuthGate>
  ),
});
