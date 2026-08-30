"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

import { Button } from "@/components/ui/button";

/**
 * Both icons are rendered and CSS picks one, rather than gating on a mounted flag.
 *
 * The usual `useEffect(() => setMounted(true), [])` pattern exists because the server
 * cannot know the resolved theme — but it sets state inside an effect, which this
 * project's lint rejects (and `.claude/rules/forms.md` §6 endorses that rule). Toggling
 * `display` under the `dark` variant needs no client state at all, so there is nothing
 * to hydrate and nothing to mismatch. `dark:` is legal here because it drives a
 * non-colour property (`design-system.md` §3).
 *
 * The label stays state-independent for the same reason: a label derived from theme
 * would read wrong for the first paint.
 */
export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label="Toggle theme"
      onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
    >
      <Sun className="hidden size-5 dark:block" />
      <Moon className="size-5 dark:hidden" />
    </Button>
  );
}
