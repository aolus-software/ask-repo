import { Suspense } from "react";

import { NotificationsScreen } from "@/components/notifications/notifications-screen";

/** Suspense is required: the screen reads useSearchParams (navigation.md §6). */
export default function NotificationsPage() {
  return (
    <Suspense>
      <NotificationsScreen />
    </Suspense>
  );
}
