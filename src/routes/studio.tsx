import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/layout/AppShell";
import { AuthGate } from "@/components/AuthGate";

export const Route = createFileRoute("/studio")({
  component: () => (
    <AuthGate>
      <AppShell mode="studio" />
    </AuthGate>
  ),
});
