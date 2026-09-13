"use client";

import { ChevronDown, ChevronUp, User } from "lucide-react";
import { useState } from "react";

import { Answer } from "@/components/ask/answer";
import { AssistantTurn } from "@/components/ask/assistant-turn";
import { Sources } from "@/components/ask/sources";
import { Button } from "@/components/ui/button";
import type { MessageResponse } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * Not a "bubble" UI on both sides — neither Claude.ai nor ChatGPT bubbles the
 * assistant's reply either. A small role icon anchors each turn instead, the user's
 * question keeps a light background block, and the assistant's answer gets room
 * around it rather than floating with nothing to mark whose turn it is.
 */
function UserTurn({ content }: { content: string }) {
  // Local and per-message: collapsing one long question must not touch any other
  // turn, and nothing here needs to survive a remount.
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="flex items-start gap-3">
      <div className="bg-muted text-muted-foreground flex size-7 shrink-0 items-center justify-center rounded-full">
        <User className="size-4" aria-hidden />
      </div>
      <div className="bg-muted min-w-0 flex-1 rounded-lg p-4">
        <div className="flex items-start gap-2">
          <p
            className={cn(
              "min-w-0 flex-1 text-base font-medium",
              collapsed ? "truncate" : "whitespace-pre-wrap",
            )}
          >
            {content}
          </p>
          <Button
            variant="ghost"
            size="icon-sm"
            className="shrink-0"
            aria-label={collapsed ? "Show full message" : "Collapse message"}
            onClick={() => setCollapsed((current) => !current)}
          >
            {collapsed ? (
              <ChevronDown className="size-4" />
            ) : (
              <ChevronUp className="size-4" />
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}

function AssistantMessage({ message }: { message: MessageResponse }) {
  return (
    <AssistantTurn>
      <Answer content={message.content} />
      <Sources citations={message.citations ?? []} citedIndexes={[]} />
      {message.finishReason && message.finishReason !== "stop" ? (
        <p className="text-muted-foreground mt-2 text-xs">
          {message.finishReason === "disconnected"
            ? "This answer was interrupted. What arrived is kept."
            : `This answer ended early (${message.finishReason}).`}
        </p>
      ) : null}
    </AssistantTurn>
  );
}

export function MessageList({ messages }: { messages: MessageResponse[] }) {
  return (
    <div className="space-y-8">
      {messages.map((message) =>
        message.role === "user" ? (
          <UserTurn key={message.id} content={message.content} />
        ) : (
          <AssistantMessage key={message.id} message={message} />
        ),
      )}
    </div>
  );
}
