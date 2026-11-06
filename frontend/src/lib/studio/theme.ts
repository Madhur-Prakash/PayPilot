/**
 * AG Studio, dressed in PayPilot's design system.
 *
 * Studio's theme drives both its DOM (panels, widgets, grids) and its charts, which
 * AG Charts draws on a canvas - and a canvas cannot resolve CSS variables. So the app's
 * tokens (`--card`, `--foreground`, `--primary` ... HSL triples) are resolved to
 * concrete rgb() strings at runtime and handed to `studioTheme.withParams`. The canvas
 * re-themes whenever the app switches between light and dark.
 */

import { studioTheme } from "ag-studio";

export interface StudioTokens {
  dark: boolean;
  font: string;
  background: string;
  card: string;
  foreground: string;
  muted: string;
  mutedForeground: string;
  border: string;
  primary: string;
  success: string;
  warning: string;
  destructive: string;
}

const TOKEN_NAMES = [
  "background", "card", "foreground", "muted", "muted-foreground", "border",
  "primary", "success", "warning", "destructive",
] as const;

/** One categorical palette for every chart - readable in both themes. */
const PALETTE = [
  "#2563eb", "#10b981", "#8b5cf6", "#f59e0b", "#06b6d4",
  "#ef4444", "#14b8a6", "#ec4899", "#84cc16", "#64748b",
];

/** Resolve `hsl(var(--token))` to the rgb() the browser computes for it. */
function resolve(probe: HTMLElement, token: string, alpha?: number): string {
  probe.style.color = alpha === undefined ? `hsl(var(--${token}))` : `hsl(var(--${token}) / ${alpha})`;
  return getComputedStyle(probe).color || "#000000";
}

export function readTokens(): StudioTokens {
  const probe = document.createElement("span");
  probe.style.display = "none";
  document.body.appendChild(probe);
  try {
    const [background, card, foreground, muted, mutedForeground, border, primary, success, warning, destructive] =
      TOKEN_NAMES.map((name) => resolve(probe, name));
    return {
      dark: document.documentElement.classList.contains("dark"),
      font: getComputedStyle(document.body).fontFamily || "Inter, system-ui, sans-serif",
      background: background!, card: card!, foreground: foreground!, muted: muted!,
      mutedForeground: mutedForeground!, border: border!, primary: primary!, success: success!,
      warning: warning!, destructive: destructive!,
    };
  } finally {
    probe.remove();
  }
}

export function buildStudioTheme(t: StudioTokens) {
  const palette = Object.fromEntries(
    PALETTE.flatMap((color, i) => [
      [`chartPaletteFills${i + 1}Color`, color],
      [`chartPaletteStrokes${i + 1}Color`, color],
    ]),
  );
  return studioTheme.withParams({
    // shared
    fontFamily: t.font,
    fontSize: 13,
    backgroundColor: t.card,
    textColor: t.foreground,
    borderColor: t.border,
    // canvas: the same surface as Studio's root and panels (one background, no seams);
    // widgets read as bordered cards on it
    studioCanvasBackgroundColor: t.card,
    studioCanvasFontFamily: t.font,
    studioPanelWidth: 240,
    studioToggleButtonActiveBackgroundColor: t.primary,
    studioToggleButtonActiveBorderColor: t.primary,
    studioToggleButtonActiveColor: t.primary,
    // widgets
    studioWidgetBackgroundColor: t.card,
    studioWidgetBorder: [1, t.border],
    studioWidgetBorderRadius: 12,
    studioWidgetPadding: 10,
    studioWidgetTitleFontFamily: t.font,
    studioWidgetTitleFontSize: 15,
    studioWidgetTitleFontWeight: "600",
    studioWidgetTitleTextColor: t.foreground,
    studioWidgetSubtitleFontFamily: t.font,
    studioWidgetSubtitleFontSize: 12,
    studioWidgetSubtitleTextColor: t.mutedForeground,
    studioWidgetCaptionFontFamily: t.font,
    studioWidgetCaptionFontSize: 11,
    studioWidgetCaptionTextColor: t.mutedForeground,
    studioValueWidgetFontSize: 24,
    studioTextWidgetFontSize: 16,
    // grid widget
    gridRowHeight: 36,
    gridRowBorder: [1, t.border],
    gridHeaderRowBorder: [1, t.border],
    valueChangeUpColor: t.success,
    valueChangeDownColor: t.destructive,
    // charts (canvas - concrete colours only)
    chartFontFamily: t.font,
    chartFontSize: 11,
    chartTextColor: t.foreground,
    chartSubtleTextColor: t.mutedForeground,
    chartAxisLabelFontFamily: t.font,
    chartAxisLabelFontSize: 11,
    chartAxisLabelColor: t.mutedForeground,
    chartAxisTitleFontFamily: t.font,
    chartAxisTitleColor: t.mutedForeground,
    chartAxisLineColor: t.border,
    chartGridLineColor: t.border,
    chartSeriesLabelFontFamily: t.font,
    chartSeriesLabelOutsideTextColor: t.foreground,
    ...palette,
  } as Parameters<typeof studioTheme.withParams>[0]);
}
