import { Answer } from "@/components/ask/answer";
import { Sources } from "@/components/ask/sources";
import type { MessageResponse } from "@/lib/api/types";

export function MessageList({ messages }: { messages: MessageResponse[] }) {
  return (
    <div className="space-y-8">
      {messages.map((message) =>
        message.role === "user" ? (
          <div key={message.id} className="bg-muted rounded-md p-4">
            <p className="text-base font-medium">{message.content}</p>
          </div>
        ) : (
          <div key={message.id}>
            <Answer
              content={message.content}
              messageId={message.id}
              finishReason={message.finishReason}
            />
            <Sources citations={message.citations ?? []} citedIndexes={[]} />
            {message.finishReason && message.finishReason !== "stop" ? (
              <p className="text-muted-foreground mt-2 text-xs">
                {message.finishReason === "disconnected"
                  ? "This answer was interrupted. What arrived is kept."
                  : `This answer ended early (${message.finishReason}).`}
              </p>
            ) : null}
          </div>
        ),
      )}
    </div>
  );
}
