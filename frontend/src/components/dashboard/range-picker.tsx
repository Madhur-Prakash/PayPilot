"use client";

import { CalendarRange } from "lucide-react";
import * as React from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/overlays";
import { DATE_RANGES } from "@/lib/constants/config";
import { formatShortDate } from "@/lib/utils";

export function RangePicker({
  days,
  onChange,
  period,
}: {
  days: number;
  onChange: (days: number) => void;
  period?: { current: { start: string; end: string }; previous: { start: string; end: string } };
}) {
  return (
    <div className="flex items-center gap-2">
      {period && (
        <span className="hidden text-xs text-muted-foreground sm:inline">
          {formatShortDate(period.current.start)} – {formatShortDate(period.current.end)}
          <span className="mx-1.5 text-muted-foreground/50">vs</span>
          {formatShortDate(period.previous.start)} – {formatShortDate(period.previous.end)}
        </span>
      )}
      <Select value={String(days)} onValueChange={(value) => onChange(Number(value))}>
        <SelectTrigger className="w-[128px]">
          <CalendarRange className="h-4 w-4 text-muted-foreground" />
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {DATE_RANGES.map((range) => (
            <SelectItem key={range.value} value={String(range.value)}>
              {range.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

/** Keeps the selected range in the URL so a view can be linked and shared. */
export function useRangeDays(defaultDays = 30): [number, (days: number) => void] {
  const [days, setDays] = React.useState(defaultDays);

  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const fromUrl = Number(params.get("days"));
    if (fromUrl && fromUrl >= 7 && fromUrl <= 180) setDays(fromUrl);
  }, []);

  const update = React.useCallback((next: number) => {
    setDays(next);
    const url = new URL(window.location.href);
    url.searchParams.set("days", String(next));
    window.history.replaceState({}, "", url.toString());
  }, []);

  return [days, update];
}
