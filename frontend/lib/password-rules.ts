import type { PasswordPolicyResponse } from "@/lib/api/types";

export interface PasswordCheck {
  id: "minLength" | "maxBytes";
  label: string;
  passed: boolean;
}

/**
 * The checks a client can honestly make, derived from the policy the API published.
 *
 * Deliberately partial: the backend also rejects common passwords from a wordlist,
 * which is not shipped to the browser (it would be large, and it would be a hint
 * sheet). So every check passing means "nothing local is wrong", **not** "this will
 * be accepted" — the API remains the authority, and its 422 still overrides whatever
 * this said.
 */
export function checkPassword(
  value: string,
  policy: Pick<PasswordPolicyResponse, "minLength" | "maxBytes">,
): PasswordCheck[] {
  const checks: PasswordCheck[] = [
    {
      id: "minLength",
      label: `At least ${policy.minLength} characters`,
      passed: value.length >= policy.minLength,
    },
  ];

  // bcrypt ignores input past its byte limit, so the backend caps bytes rather than
  // characters — a passphrase of emoji or CJK hits it far sooner than its length
  // suggests. Shown only once it is actually exceeded; otherwise it is noise.
  const bytes = new TextEncoder().encode(value).length;
  if (bytes > policy.maxBytes) {
    checks.push({
      id: "maxBytes",
      label: `At most ${policy.maxBytes} bytes (this is ${bytes})`,
      passed: false,
    });
  }

  return checks;
}

/** Every local check satisfied. An empty value never counts. */
export function passwordChecksPass(
  value: string,
  policy: Pick<PasswordPolicyResponse, "minLength" | "maxBytes">,
): boolean {
  return (
    value.length > 0 && checkPassword(value, policy).every((check) => check.passed)
  );
}
