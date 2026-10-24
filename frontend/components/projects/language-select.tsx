"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ENDONYMS, isLanguage, LANGUAGES, type Language } from "@/lib/i18n/languages";

/** A language picker whose options are endonyms, so a user finds theirs unread. */
export function LanguageSelect({
  id,
  value,
  onChange,
  ariaLabel,
}: {
  id?: string;
  value: Language;
  onChange: (value: Language) => void;
  ariaLabel?: string;
}) {
  return (
    <Select
      value={value}
      onValueChange={(next: string | null) => {
        if (isLanguage(next)) onChange(next);
      }}
    >
      <SelectTrigger id={id} className="w-full" aria-label={ariaLabel}>
        <SelectValue>
          {(current: string) => (isLanguage(current) ? ENDONYMS[current] : "")}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {LANGUAGES.map((code) => (
          <SelectItem key={code} value={code} lang={code}>
            {ENDONYMS[code]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
