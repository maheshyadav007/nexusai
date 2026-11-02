import { redirect } from "next/navigation";

// It became part of the Cockpit, and old links should still get somewhere.
export default function Page() {
  redirect("/cockpit");
}
