import { Suspense } from "react";

import { UsersScreen } from "@/app/(app)/settings/users/users-screen";

/** Suspense is required: the screen reads useSearchParams (navigation.md §6). */
export default function UsersPage() {
  return (
    <Suspense>
      <UsersScreen />
    </Suspense>
  );
}
