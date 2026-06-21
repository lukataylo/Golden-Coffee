import type { Metadata } from "next";
import { DashboardClient } from "./dashboard-client";

export const metadata: Metadata = {
  title: "Dashboard",
  description: "Your Caffe Steve command center.",
};

export default function DashboardPage() {
  return <DashboardClient />;
}
