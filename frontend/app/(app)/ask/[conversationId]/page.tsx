import { ConversationScreen } from "@/app/(app)/ask/[conversationId]/conversation-screen";

export default async function ConversationPage({
  params,
}: {
  params: Promise<{ conversationId: string }>;
}) {
  const { conversationId } = await params;
  return <ConversationScreen conversationId={conversationId} />;
}
