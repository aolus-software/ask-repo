"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";

/** Sits inside the same card as the table (`docs/design.md` → Lists). */
export function PaginationFooter({
  page,
  totalPages,
  totalCount,
  onPageChange,
}: {
  page: number;
  totalPages: number;
  totalCount: number;
  onPageChange: (page: number) => void;
}) {
  const t = useTranslations("nav.pagination");

  if (totalPages <= 1) return null;

  return (
    <div className="border-border flex items-center justify-between border-t p-4">
      <p className="text-muted-foreground text-xs">
        {t("summary", { page, totalPages, totalCount })}
      </p>
      <div className="flex gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          {t("previous")}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
        >
          {t("next")}
        </Button>
      </div>
    </div>
  );
}
