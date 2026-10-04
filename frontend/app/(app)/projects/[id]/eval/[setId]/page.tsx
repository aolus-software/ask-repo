import { EvalSetScreen } from "@/components/eval/eval-set-screen";

/** `params` is async in Next 16 and is always awaited. */
export default async function EvalSetPage({
  params,
}: {
  params: Promise<{ id: string; setId: string }>;
}) {
  const { id, setId } = await params;
  return <EvalSetScreen projectId={id} setId={setId} />;
}
