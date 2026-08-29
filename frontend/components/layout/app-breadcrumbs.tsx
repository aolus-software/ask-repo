"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Fragment } from "react";

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { useSession } from "@/hooks/use-session";
import { resolveBreadcrumbs } from "@/lib/nav";

export function AppBreadcrumbs() {
  const user = useSession();
  const pathname = usePathname();
  const trail = resolveBreadcrumbs(pathname, user);

  if (trail.length === 0) return null;

  return (
    <Breadcrumb className="mb-4">
      <BreadcrumbList>
        {trail.map((crumb, index) => {
          const isLast = index === trail.length - 1;
          return (
            // The separator is a SIBLING of the item, never a child: both render an
            // <li>, and nesting is invalid HTML that fails hydration in the browser
            // while passing every render assertion (navigation.md §5).
            <Fragment key={crumb.href}>
              <BreadcrumbItem>
                {isLast ? (
                  <BreadcrumbPage>{crumb.label}</BreadcrumbPage>
                ) : (
                  <BreadcrumbLink render={<Link href={crumb.href} />}>
                    {crumb.label}
                  </BreadcrumbLink>
                )}
              </BreadcrumbItem>
              {isLast ? null : <BreadcrumbSeparator />}
            </Fragment>
          );
        })}
      </BreadcrumbList>
    </Breadcrumb>
  );
}
