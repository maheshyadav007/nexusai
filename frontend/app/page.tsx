import { redirect } from "next/navigation";

// The landing page replaces this in Stage 1.
export default function HomePage() {
  redirect("/today");
}
