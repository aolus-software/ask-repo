"use client";

import type { LucideIcon } from "lucide-react";
import {
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  useState,
} from "react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

/** 48rem -- the fixed `sm:max-w-3xl` the drag handle replaced. */
const DEFAULT_WIDTH = 768;
/** Below this the chat composer and the change-set table both wrap badly. */
const MIN_WIDTH = 360;
/** Gap kept between the drawer's left edge and the viewport's. */
const VIEWPORT_MARGIN = 32;
const KEYBOARD_STEP = 32;
const STORAGE_PREFIX = "askrepo.drawer-width.";

/**
 * `localStorage` throws rather than returning null in a few configurations
 * (Safari's private mode historically, an iframe with third-party storage
 * blocked). A drawer that cannot remember its width is a lesser problem than a
 * drawer that cannot open, so both accessors swallow the failure.
 */
function readStoredWidth(key: string): number | null {
  if (typeof window === "undefined") return null;
  try {
    const stored = Number(window.localStorage.getItem(STORAGE_PREFIX + key));
    return Number.isFinite(stored) && stored >= MIN_WIDTH ? stored : null;
  } catch {
    return null;
  }
}

function storeWidth(key: string, width: number): void {
  try {
    window.localStorage.setItem(STORAGE_PREFIX + key, String(width));
  } catch {
    // Width simply will not persist; the drawer still works this session.
  }
}

function clampWidth(width: number): number {
  const ceiling = Math.max(MIN_WIDTH, window.innerWidth - VIEWPORT_MARGIN);
  return Math.min(Math.max(width, MIN_WIDTH), ceiling);
}

/**
 * A button and the side drawer it opens. Used twice per tab: once for the
 * refinement chat, once for the pending proposal.
 *
 * **Why these moved off the page.** The change-set panel used to render above the
 * grid and the chat that produced it below, so accepting a proposal meant
 * scrolling back past the entire checklist — and the composer disabled itself for
 * a reason (one pending change set per module) that was off-screen, which reads as
 * the UI being broken rather than as a rule. Behind buttons in the action row,
 * both are one click from anywhere on the page and the grid keeps the full width.
 *
 * **Why two drawers rather than one.** They answer different questions and are
 * wanted at different moments: "what is being proposed, and do I accept it?" is a
 * review task with a table to read, while "ask for something else" is a
 * conversation. Sharing one surface would mean scrolling past a proposal to reach
 * the composer, which is the problem this change exists to remove.
 *
 * **Closing mid-answer stops that answer, and that is the designed behaviour.**
 * `SheetContent` unmounts its children on close, so the stream disconnects. The
 * server treats a disconnect as the ordinary case (`stream_turn`'s shielded write,
 * `.claude/rules/rag.md`): the partial reply is persisted, reappears in history on
 * reopen, and is labelled as interrupted. Keeping it alive would mean patching the
 * CLI-managed `components/ui/sheet.tsx` to pass `keepMounted` to the portal — a
 * divergence to take deliberately if the abort proves annoying, not by default.
 *
 * **Why a drag handle rather than `components/ui/resizable.tsx`.** That component
 * models a panel *group* — two or more siblings dividing a fixed extent, each
 * giving up what the other takes. A drawer has one movable edge and a viewport on
 * the other side of it, so there is no second panel to trade against. Installing
 * the CLI component to use a tenth of it would also add a row to
 * `docs/design.md`'s inventory for a dependency nothing else wants.
 *
 * **Width persists in `localStorage`, per drawer.** Phase 1 has no user-preference
 * store (`docs/PRD.md` §2.1 carries the per-user persona that would introduce
 * one), and component state resets on every navigation — which makes a drag worth
 * doing exactly once per page view. Each drawer keys its own entry because the
 * review table and the chat want different widths. When phase 2 lands a real
 * preference store, this is one function to change.
 */
interface RefinementDrawerProps {
  label: string;
  icon: LucideIcon;
  /** `default` for a proposal waiting on someone, `outline` for the chat. */
  variant?: "default" | "outline";
  title: string;
  description: string;
  /**
   * Stable identity for this drawer's remembered width. Derive it from the
   * surface, never from `title` — copy changes would silently orphan the entry.
   */
  storageKey: string;
  children: ReactNode;
}

export function RefinementDrawer({
  label,
  icon: Icon,
  variant = "outline",
  title,
  description,
  storageKey,
  children,
}: RefinementDrawerProps) {
  const [open, setOpen] = useState(false);
  // Read during initialisation rather than from an effect: the popup is not
  // mounted while closed, so the server's default and the client's stored value
  // never both reach the DOM and there is nothing to mismatch on hydration.
  const [width, setWidth] = useState(() => {
    const stored = readStoredWidth(storageKey);
    // A width dragged on a wide monitor must not survive onto a narrow one as a
    // number the drawer reports but cannot honour. `readStoredWidth` returns
    // null on the server, so a non-null value means `window` is safe to measure.
    return stored === null ? DEFAULT_WIDTH : clampWidth(stored);
  });
  const [dragStart, setDragStart] = useState<{
    pointerX: number;
    width: number;
  } | null>(null);

  function beginDrag(event: ReactPointerEvent<HTMLDivElement>) {
    // Capture so the drag survives the pointer leaving the 8px handle, which it
    // does immediately at any real dragging speed.
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragStart({ pointerX: event.clientX, width });
  }

  function continueDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (dragStart === null) return;
    // The drawer is anchored to the right edge, so a falling clientX widens it.
    setWidth(clampWidth(dragStart.width - (event.clientX - dragStart.pointerX)));
  }

  function endDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (dragStart === null) return;
    event.currentTarget.releasePointerCapture(event.pointerId);
    setDragStart(null);
    storeWidth(storageKey, width);
  }

  function resizeByKey(event: ReactKeyboardEvent<HTMLDivElement>) {
    const step =
      event.key === "ArrowLeft"
        ? KEYBOARD_STEP
        : event.key === "ArrowRight"
          ? -KEYBOARD_STEP
          : 0;
    if (step === 0) return;
    event.preventDefault();
    const next = clampWidth(width + step);
    setWidth(next);
    storeWidth(storageKey, next);
  }

  return (
    <>
      <Button variant={variant} onClick={() => setOpen(true)}>
        <Icon className="size-4" />
        {label}
      </Button>

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent
          side="right"
          // The width override has to carry the same `data-[side=right]:` variant
          // the generated component uses. `SheetContent` ships
          // `data-[side=right]:w-3/4`, and a bare `sm:w-*` loses to it on
          // specificity -- the class would be present in the DOM and simply not
          // apply, which is the kind of silent no-op that survives review. With
          // the variant it ties on specificity and wins on source order, because
          // Tailwind emits the `sm:` block after the unprefixed one.
          //
          // The width arrives as a custom property rather than an inline `width`
          // so it can be scoped to `sm:`. An inline style applies at every
          // breakpoint, which would hand a 900px drawer to a 400px phone; below
          // `sm` the generated three-quarter width is what should win, and the
          // handle is hidden there anyway.
          className="flex w-full flex-col gap-0 data-[side=right]:sm:w-[var(--drawer-width)]"
          style={
            {
              "--drawer-width": `${width}px`,
              // `max-width` is the one that cannot be a class. Beating the
              // generated `data-[side=right]:sm:max-w-sm` needs equal specificity
              // *and* later source order, and Tailwind emits arbitrary values
              // ahead of the named scale -- so the same override written as an
              // arbitrary max-width utility renders and then loses to a 24rem
              // cap. (The fixed width this replaced named the 3xl step, which
              // worked only because it sorts after sm in the ascending container
              // scale.) An inline style beats any class whatever the order, and
              // below `sm` it is inert: it is only a ceiling, and the mobile
              // width is 75vw.
              //
              // Do not write the utility form in this comment either -- the
              // class scanner reads comments and would emit the dead rule.
              maxWidth: "calc(100vw - 2rem)",
            } as CSSProperties
          }
        >
          {/* The ARIA window-splitter pattern: a focusable `separator` with a
              value, so the drawer is resizable without a pointer. */}
          <div
            role="separator"
            aria-label="Resize drawer"
            aria-orientation="vertical"
            aria-valuenow={width}
            aria-valuemin={MIN_WIDTH}
            tabIndex={0}
            onPointerDown={beginDrag}
            onPointerMove={continueDrag}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
            onKeyDown={resizeByKey}
            className="group absolute inset-y-0 left-0 z-10 hidden w-2 cursor-col-resize touch-none items-center justify-center outline-none sm:flex"
          >
            <span
              data-dragging={dragStart !== null || undefined}
              className="h-8 w-0.5 rounded-full bg-transparent transition-colors group-hover:bg-border group-focus-visible:bg-ring data-dragging:bg-ring"
            />
          </div>

          <SheetHeader className="border-border border-b">
            <SheetTitle>{title}</SheetTitle>
            <SheetDescription>{description}</SheetDescription>
          </SheetHeader>
          {/* `min-h-0` or this flex child refuses to shrink and the drawer scrolls
              as a whole, taking the header with it. */}
          <div
            // Text selection follows the pointer across the whole popup during a
            // drag, which looks like the panel is glitching. Suppressing it on
            // the scroll region covers everything the pointer can reach.
            data-dragging={dragStart !== null || undefined}
            className="min-h-0 flex-1 space-y-6 overflow-y-auto p-4 data-dragging:select-none"
          >
            {children}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}
