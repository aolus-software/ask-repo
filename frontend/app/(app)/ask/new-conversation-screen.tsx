"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Composer } from "@/components/ask/composer";
import { ProjectPicker } from "@/components/ask/project-picker";
import { FormError } from "@/components/form/form-error";
import { useCreateConversation } from "@/hooks/use-conversations";
import { setPendingQuestion } from "@/lib/ask/pending";

export function NewConversationScreen() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [projectId, setProjectId] = useState<string | null>(searchParams.get("projectId"));
  const create = useCreateConversation();

  function handleAsk(question: string) {
    if (!projectId) return;

    create.mutate(
      { projectId },
      {
        onSuccess: (conversation) => {
          // Two calls with a navigation between them: create, then ask. The question
          // travels in a module-level map, and `replace` means Back does not return
          // to a composer that has already fired (design spec §9.3).
          setPendingQuestion(conversation.id, question);
          router.replace(`/ask/${conversation.id}`);
        },
      },
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Ask</h1>
        <p className="text-muted-foreground mt-1 text-base">
          Questions are answered from the indexed code, with citations. Only you can see them.
        </p>
      </div>

      <FormError error={create.error} />

      <ProjectPicker value={projectId} onChange={setProjectId} />

      <Composer
        onSubmit={handleAsk}
        disabled={!projectId || create.isPending}
        placeholder={
          projectId ? "How does the withdrawal calculation work?" : "Choose a project first"
        }
      />
    </div>
  );
}
