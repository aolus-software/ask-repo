import { endpoints } from "@/lib/api/endpoints";
import { forwardPublic } from "@/lib/auth/public-forward";

/** Public: the reset form's live checklist reads this with no session. */
export function GET(request: Request): Promise<Response> {
  return forwardPublic(request, endpoints.auth.passwordPolicy);
}
