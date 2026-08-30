"use client";

import { Loader2 } from "lucide-react";

import { FormError } from "@/components/form/form-error";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export interface FormShellProps {
  title: string;
  description?: string;
  submitLabel: string;
  isPending: boolean;
  error: unknown;
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
  children: React.ReactNode;
}

/**
 * Width is a size, never a class: the generated DialogContent defaults to
 * `sm:max-w-sm`, which is too cramped for a labelled form (`forms.md` §3).
 */
const SIZES = { sm: "sm:max-w-md", md: "sm:max-w-xl", lg: "sm:max-w-3xl" } as const;

export function FormDialog({
  open,
  onOpenChange,
  size = "md",
  title,
  description,
  submitLabel,
  isPending,
  error,
  onSubmit,
  children,
}: FormShellProps & {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  size?: keyof typeof SIZES;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(SIZES[size])}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description ? <DialogDescription>{description}</DialogDescription> : null}
        </DialogHeader>

        <form onSubmit={onSubmit} noValidate>
          <FormError error={error} />
          <div className="space-y-4">{children}</div>
          <DialogFooter className="mt-6 gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={isPending}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isPending}>
              {isPending ? <Loader2 className="size-4 animate-spin" /> : null}
              {submitLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
