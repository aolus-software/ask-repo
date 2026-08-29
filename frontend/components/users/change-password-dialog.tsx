"use client";

interface ChangePasswordDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Placeholder. The real dialog lands in Task 16, where the change-password field set
 * and its mutation are built; the account menu links to it now so the shell is
 * complete without waiting.
 */
export function ChangePasswordDialog(props: ChangePasswordDialogProps) {
  return props.open ? null : null;
}
