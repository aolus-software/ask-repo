"use client";

import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
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
import { useErrorText } from "@/lib/i18n/error-text";
import { useState } from "react";

const COUNT_OPTIONS = [5, 10, 25, 50] as const;

export function GenerateMockDataControl({
  moduleId,
  blockedBecause,
  disabled = false,
}: {
  moduleId: string;
  blockedBecause: string | null;
  /** Disables the control without a reason, e.g. while permissions are not yet known. */
  disabled?: boolean;
}) {
  const t = useTranslations("mockData.generateControl");
  const errorText = useErrorText();
  const [count, setCount] = useState<number>(10);
  const generate = useGenerateMockData(moduleId);

  const button = (
    <Button
      disabled={generate.isPending || blockedBecause !== null || disabled}
      onClick={() =>
        generate.mutate(count, {
          onSuccess: () => toast.success(t("started")),
          onError: (error) => toast.error(errorText(error)),
        })
      }
    >
      <Sparkles className="size-4" />
      {t("generate")}
    </Button>
  );

  return (
    <div className="flex items-center gap-2">
      <Select value={String(count)} onValueChange={(value) => setCount(Number(value))}>
        <SelectTrigger className="w-24" aria-label={t("countAria")}>
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
