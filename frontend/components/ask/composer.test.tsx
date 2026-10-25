import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Composer } from "@/components/ask/composer";

function setup() {
  const onSubmit = vi.fn();
  render(<Composer onSubmit={onSubmit} disabled={false} placeholder="Ask" />);
  const box = screen.getByRole("textbox", { name: "Your question" });
  fireEvent.change(box, { target: { value: "how does login work" } });
  return { box, onSubmit };
}

describe("Composer Enter handling", () => {
  it("sends on a plain Enter", () => {
    const { box, onSubmit } = setup();
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledWith("how does login work");
  });

  it("does not send on Shift+Enter", () => {
    const { box, onSubmit } = setup();
    fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("does not send an Enter that confirms an IME candidate (isComposing)", () => {
    const { box, onSubmit } = setup();
    fireEvent.keyDown(box, { key: "Enter", isComposing: true });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("does not send an Enter reported as keyCode 229 (Safari)", () => {
    const { box, onSubmit } = setup();
    fireEvent.keyDown(box, { key: "Enter", keyCode: 229 });
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
