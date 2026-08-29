"use client";

import { ArrowLeft, Loader2 } from "lucide-react";
import Link from "next/link";

import type { FormShellProps } from "@/components/form/form-dialog";
import { FormError } from "@/components/form/form-error";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

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
}: FormShellProps & { backHref?: string }) {
  return (
    <div className="mx-auto w-full max-w-3xl">
      {backHref ? (
        <Button variant="ghost" size="sm" className="mb-4" render={<Link href={backHref} />}>
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
