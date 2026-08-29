"use client";

import { SendHorizonal } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export function Composer({
  onSubmit,
  disabled,
  placeholder,
}: {
  onSubmit: (question: string) => void;
  disabled: boolean;
  placeholder: string;
}) {
  const [question, setQuestion] = useState("");

  function submit() {
    const trimmed = question.trim();
    if (!trimmed || disabled) return;
    setQuestion("");
    onSubmit(trimmed);
  }

  return (
    <form
      className="border-border bg-card rounded-md border p-2"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <Textarea
        className="min-h-20 resize-none border-0 shadow-none focus-visible:ring-0"
        placeholder={placeholder}
        value={question}
        aria-label="Your question"
        onChange={(event) => setQuestion(event.target.value)}
        onKeyDown={(event) => {
          // Enter sends, Shift+Enter breaks the line.
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
      />
      <div className="flex justify-end">
        <Button type="submit" size="sm" disabled={disabled || !question.trim()}>
          <SendHorizonal className="size-4" />
          Ask
        </Button>
      </div>
    </form>
  );
}
