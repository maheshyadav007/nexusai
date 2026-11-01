import { AgentScreen } from "@/ui/features/sessions/AgentScreen";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AgentScreen key={id} id={id} />;
}
