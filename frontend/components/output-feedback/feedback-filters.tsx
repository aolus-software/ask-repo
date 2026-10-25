"use client";

import { useTranslations } from "next-intl";

import { FilterField } from "@/components/layout/filter-field";
import { FEEDBACK_FEATURES } from "@/components/output-feedback/feedback-summary";
import { REASON_CODES } from "@/components/output-feedback/reason-labels";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  FeedbackFeature,
  FeedbackListParams,
  FeedbackRating,
  FeedbackReasonCode,
} from "@/lib/api/types";

/**
 * "No filter" needs a real option value, the same sentinel every other list screen's
 * filter uses (see `AuditFilters`, `NotificationFilters`): a select whose item value
 * is `""` is indistinguishable from an unset one. It never leaves this file.
 */
const ANY = "any";

export function FeedbackFilters({
  currentFilters,
  onFiltersChange,
}: {
  currentFilters: Partial<FeedbackListParams>;
  onFiltersChange: (filters: Partial<FeedbackListParams>) => void;
}) {
  const t = useTranslations("outputFeedback");

  return (
    <>
      <FilterField
        htmlFor="feedback-filter-feature"
        label={t("filters.filterByFeature")}
      >
        <Select
          value={currentFilters.feature ?? ANY}
          onValueChange={(value: string | null | undefined) =>
            onFiltersChange({
              ...currentFilters,
              feature: !value || value === ANY ? undefined : (value as FeedbackFeature),
            })
          }
        >
          <SelectTrigger id="feedback-filter-feature" className="w-full">
            <SelectValue>
              {(value: string) =>
                value === ANY
                  ? t("filters.allFeatures")
                  : t(`features.${value as FeedbackFeature}`)
              }
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>{t("filters.allFeatures")}</SelectItem>
            {FEEDBACK_FEATURES.map((feature) => (
              <SelectItem key={feature} value={feature}>
                {t(`features.${feature}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FilterField>

      <FilterField htmlFor="feedback-filter-rating" label={t("filters.filterByVote")}>
        <Select
          value={currentFilters.rating ?? ANY}
          onValueChange={(value: string | null | undefined) =>
            onFiltersChange({
              ...currentFilters,
              rating: !value || value === ANY ? undefined : (value as FeedbackRating),
            })
          }
        >
          <SelectTrigger id="feedback-filter-rating" className="w-full">
            <SelectValue>
              {(value: string) =>
                value === ANY
                  ? t("filters.allVotes")
                  : value === "up"
                    ? t("filters.up")
                    : t("filters.down")
              }
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>{t("filters.allVotes")}</SelectItem>
            <SelectItem value="up">{t("filters.up")}</SelectItem>
            <SelectItem value="down">{t("filters.down")}</SelectItem>
          </SelectContent>
        </Select>
      </FilterField>

      <FilterField htmlFor="feedback-filter-reason" label={t("filters.filterByReason")}>
        <Select
          value={currentFilters.reasonCode ?? ANY}
          onValueChange={(value: string | null | undefined) =>
            onFiltersChange({
              ...currentFilters,
              reasonCode:
                !value || value === ANY ? undefined : (value as FeedbackReasonCode),
            })
          }
        >
          <SelectTrigger id="feedback-filter-reason" className="w-full">
            <SelectValue>
              {(value: string) =>
                value === ANY
                  ? t("filters.allReasons")
                  : t(`reasons.${value as FeedbackReasonCode}`)
              }
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>{t("filters.allReasons")}</SelectItem>
            {REASON_CODES.map((code) => (
              <SelectItem key={code} value={code}>
                {t(`reasons.${code}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FilterField>

      <FilterField htmlFor="feedback-filter-from" label={t("filters.fromDate")}>
        <Input
          id="feedback-filter-from"
          type="date"
          className="w-full"
          value={currentFilters.createdFrom?.slice(0, 10) ?? ""}
          onChange={(event) =>
            onFiltersChange({
              ...currentFilters,
              createdFrom: event.target.value || undefined,
            })
          }
        />
      </FilterField>

      <FilterField htmlFor="feedback-filter-to" label={t("filters.toDate")}>
        <Input
          id="feedback-filter-to"
          type="date"
          className="w-full"
          value={currentFilters.createdTo?.slice(0, 10) ?? ""}
          onChange={(event) =>
            onFiltersChange({
              ...currentFilters,
              createdTo: event.target.value || undefined,
            })
          }
        />
      </FilterField>
    </>
  );
}
