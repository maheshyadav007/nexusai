import { ThreadScreen } from "@/ui/features/mail/ThreadScreen";

export default async function Page({ params }: { params: Promise<{ thread: string }> }) {
  const { thread } = await params;
  return <ThreadScreen key={thread} id={Number(thread)} />;
}
