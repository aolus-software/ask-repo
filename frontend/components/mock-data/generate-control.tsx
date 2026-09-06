"use client";

import { Sparkles } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useGenerateMockData } from "@/hooks/use-mock-data-mutations";
import { isApiError } from "@/lib/api/errors";
import { useState } from "react";

const COUNT_OPTIONS = [5, 10, 25, 50] as const;

export function GenerateMockDataControl({
  moduleId,
  blockedBecause,
}: {
  moduleId: string;
  blockedBecause: string | null;
}) {
  const [count, setCount] = useState<number>(10);
  const generate = useGenerateMockData(moduleId);

  const button = (
    <Button
      disabled={generate.isPending || blockedBecause !== null}
      onClick={() =>
        generate.mutate(count, {
          onSuccess: () =>
            toast.success("Generating. The proposals appear here when it finishes."),
          onError: (error) =>
            toast.error(
              isApiError(error) ? error.message : "That did not start. Try again.",
            ),
        })
      }
    >
      <Sparkles className="size-4" />
      Generate
    </Button>
  );

  return (
    <div className="flex items-center gap-2">
      <Select value={String(count)} onValueChange={(value) => setCount(Number(value))}>
        <SelectTrigger className="w-24" aria-label="Number of records to generate">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {COUNT_OPTIONS.map((option) => (
            <SelectItem key={option} value={String(option)}>
              {option}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {blockedBecause ? (
        <Tooltip>
          <TooltipTrigger render={<span>{button}</span>} />
          <TooltipContent>{blockedBecause}</TooltipContent>
        </Tooltip>
      ) : (
        button
      )}
    </div>
  );
}
