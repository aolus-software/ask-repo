"use client";

import { FEATURE_LABELS } from "@/components/output-feedback/feedback-summary";
import { REASON_LABELS } from "@/components/output-feedback/reason-labels";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { FeedbackFeature, FeedbackListParams, FeedbackRating, FeedbackReasonCode } from "@/lib/api/types";

/**
 * "No filter" needs a real option value, the same sentinel every other list screen's
 * filter uses (see `AuditFilters`, `NotificationFilters`): a select whose item value
 * is `""` is indistinguishable from an unset one. It never leaves this file.
 */
const ANY = "any";

const ALL_FEATURES = "All features";
const ALL_VOTES = "All votes";
const ALL_REASONS = "All reasons";

const FEATURE_OPTIONS = Object.keys(FEATURE_LABELS) as FeedbackFeature[];
const REASON_OPTIONS = Object.keys(REASON_LABELS) as FeedbackReasonCode[];

export function FeedbackFilters({
  currentFilters,
  onFiltersChange,
}: {
  currentFilters: Partial<FeedbackListParams>;
  onFiltersChange: (filters: Partial<FeedbackListParams>) => void;
}) {
  return (
    <>
      <div>
        <Select
          value={currentFilters.feature ?? ANY}
          onValueChange={(value: string | null | undefined) =>
            onFiltersChange({
              ...currentFilters,
              feature: !value || value === ANY ? undefined : (value as FeedbackFeature),
            })
          }
        >
          <SelectTrigger className="w-full" aria-label="Filter by feature">
            <SelectValue>
              {(value: string) =>
                value === ANY ? ALL_FEATURES : FEATURE_LABELS[value as FeedbackFeature]
              }
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>{ALL_FEATURES}</SelectItem>
            {FEATURE_OPTIONS.map((feature) => (
              <SelectItem key={feature} value={feature}>
                {FEATURE_LABELS[feature]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div>
        <Select
          value={currentFilters.rating ?? ANY}
          onValueChange={(value: string | null | undefined) =>
            onFiltersChange({
              ...currentFilters,
              rating: !value || value === ANY ? undefined : (value as FeedbackRating),
            })
          }
        >
          <SelectTrigger className="w-full" aria-label="Filter by vote">
            <SelectValue>
              {(value: string) =>
                value === ANY ? ALL_VOTES : value === "up" ? "Up" : "Down"
              }
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>{ALL_VOTES}</SelectItem>
            <SelectItem value="up">Up</SelectItem>
            <SelectItem value="down">Down</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div>
        <Select
          value={currentFilters.reasonCode ?? ANY}
          onValueChange={(value: string | null | undefined) =>
            onFiltersChange({
              ...currentFilters,
              reasonCode: !value || value === ANY ? undefined : (value as FeedbackReasonCode),
            })
          }
        >
          <SelectTrigger className="w-full" aria-label="Filter by reason">
            <SelectValue>
              {(value: string) =>
                value === ANY ? ALL_REASONS : REASON_LABELS[value as FeedbackReasonCode]
              }
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>{ALL_REASONS}</SelectItem>
            {REASON_OPTIONS.map((code) => (
              <SelectItem key={code} value={code}>
                {REASON_LABELS[code]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div>
        <Input
          type="date"
          className="w-full"
          value={currentFilters.createdFrom?.slice(0, 10) ?? ""}
          onChange={(event) =>
            onFiltersChange({
              ...currentFilters,
              createdFrom: event.target.value || undefined,
            })
          }
          aria-label="From date"
        />
      </div>

      <div>
        <Input
          type="date"
          className="w-full"
          value={currentFilters.createdTo?.slice(0, 10) ?? ""}
          onChange={(event) =>
            onFiltersChange({
              ...currentFilters,
              createdTo: event.target.value || undefined,
            })
          }
          aria-label="To date"
        />
      </div>
    </>
  );
}
