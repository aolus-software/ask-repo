"use client";

import { ArrowLeft, Loader2 } from "lucide-react";
import Link from "next/link";

import type { FormShellProps } from "@/components/form/form-dialog";
import { FormError } from "@/components/form/form-error";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * `width` defaults to the app-page size (`docs/design.md` → Layout's `max-w-3xl` for
 * forms and prose). A form mounted on the shell-less auth background — the forced
 * password change, next to the narrow sign-in card it follows — passes `"narrow"`
 * instead, so the two screens do not double in width between them
 * (`docs/ui-audit-findings.md` §U5.3).
 */
const WIDTHS = { default: "max-w-3xl", narrow: "max-w-sm" } as const;

/** Same props as FormDialog, so moving a form between shells is a swap (forms.md §2). */
export function FormPage({
  backHref,
  title,
  description,
  submitLabel,
  isPending,
  error,
  onSubmit,
  children,
  width = "default",
}: FormShellProps & { backHref?: string; width?: keyof typeof WIDTHS }) {
  return (
    <div className={cn("mx-auto w-full", WIDTHS[width])}>
      {backHref ? (
        <Button
          variant="ghost"
          size="sm"
          className="mb-4"
          nativeButton={false}
          render={<Link href={backHref} />}
        >
          <ArrowLeft className="size-4" />
          Back
        </Button>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="text-xl font-semibold">{title}</CardTitle>
          {description ? <CardDescription>{description}</CardDescription> : null}
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} noValidate>
            <FormError error={error} />
            <div className="space-y-4">{children}</div>
            <div className="mt-6 flex justify-end gap-2">
              <Button type="submit" disabled={isPending}>
                {isPending ? <Loader2 className="size-4 animate-spin" /> : null}
                {submitLabel}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
