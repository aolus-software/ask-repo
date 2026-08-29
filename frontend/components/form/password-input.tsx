"use client";

import { Eye, EyeOff } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/**
 * A password field with a reveal toggle.
 *
 * `type` is owned here, not by the caller — that is the whole point of the component,
 * and letting a call site pass its own would let one field silently ship as plain
 * text. Everything else forwards to `Input`, so `autoComplete`, `aria-invalid` and
 * the field wiring behave exactly as they did before.
 *
 * The toggle is `type="button"`: inside a form, a button with no explicit type
 * submits, so revealing the password would fire the submit handler.
 */
export function PasswordInput({
  className,
  ...props
}: Omit<React.ComponentProps<typeof Input>, "type">) {
  const [visible, setVisible] = useState(false);

  return (
    <div className="relative">
      <Input
        {...props}
        type={visible ? "text" : "password"}
        // Room for the toggle, in logical units so an RTL locale flips with it.
        className={cn("pe-10", className)}
      />
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        // The label states what pressing it DOES, which is what a screen reader
        // announces; aria-pressed carries the current state separately.
        aria-label={visible ? "Hide password" : "Show password"}
        aria-pressed={visible}
        className="absolute inset-y-0 end-1 my-auto"
        onClick={() => setVisible((current) => !current)}
      >
        {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </Button>
    </div>
  );
}
