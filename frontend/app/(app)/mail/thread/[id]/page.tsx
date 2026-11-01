import { ThreadScreen } from "@/ui/features/mail/ThreadScreen";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ThreadScreen key={id} id={Number(id)} />;
}
