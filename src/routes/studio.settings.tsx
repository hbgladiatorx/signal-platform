import { createFileRoute } from "@tanstack/react-router";
import SettingsImpl from "./app.settings";

export const Route = createFileRoute("/studio/settings")({
  head: () => ({ meta: [{ title: "Settings — Bayn Studio" }] }),
  component: () => <SettingsImpl />,
});

// SettingsImpl is the same component used in trader Settings — single shared component.
