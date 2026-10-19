import { LocaleSelect } from "@/components/auth/locale-select";

/** Shell-less: no sidebar, no navbar. A centred card on the page background. */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-background flex min-h-screen flex-col items-center justify-center gap-4 p-4">
      {children}
      <LocaleSelect />
    </div>
  );
}
