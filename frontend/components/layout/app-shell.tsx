import { AppBreadcrumbs } from "@/components/layout/app-breadcrumbs";
import { AppNavbar } from "@/components/layout/app-navbar";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { SessionProvider } from "@/components/layout/session-context";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import type { UserResponse } from "@/lib/api/types";

/** Geometry is fixed by `docs/design.md` → Layout and design-system.md §9. */
export function AppShell({
  user,
  children,
}: {
  user: UserResponse;
  children: React.ReactNode;
}) {
  return (
    <SessionProvider user={user}>
      <SidebarProvider>
        <AppNavbar />
        <AppSidebar />
        <SidebarInset>
          <main className="mt-16 p-4 md:p-8">
            <AppBreadcrumbs />
            {children}
          </main>
        </SidebarInset>
      </SidebarProvider>
    </SessionProvider>
  );
}
