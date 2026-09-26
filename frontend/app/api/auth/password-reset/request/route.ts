import { endpoints } from "@/lib/api/endpoints";
import { forwardPublic } from "@/lib/auth/public-forward";

export function POST(request: Request): Promise<Response> {
  return forwardPublic(request, endpoints.auth.passwordResetRequest);
}
