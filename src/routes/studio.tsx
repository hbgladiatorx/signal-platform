import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/layout/AppShell";

export const Route = createFileRoute("/studio")({
  component: () => <AppShell mode="studio" />,
});
