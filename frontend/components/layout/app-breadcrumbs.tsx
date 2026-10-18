"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
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
import { useBreadcrumbLabels } from "@/components/layout/breadcrumb-labels";
import { useSession } from "@/hooks/use-session";
import { resolveBreadcrumbs } from "@/lib/nav";

export function AppBreadcrumbs() {
  const t = useTranslations("nav.items");
  const user = useSession();
  const pathname = usePathname();
  const labels = useBreadcrumbLabels();
  const trail = resolveBreadcrumbs(pathname, user, labels);

  if (trail.length === 0) return null;

  const text = (crumb: (typeof trail)[number]) =>
    crumb.labelKey ? t(crumb.labelKey) : crumb.label;

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
                  <BreadcrumbPage>{text(crumb)}</BreadcrumbPage>
                ) : (
                  <BreadcrumbLink render={<Link href={crumb.href} />}>
                    {text(crumb)}
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
