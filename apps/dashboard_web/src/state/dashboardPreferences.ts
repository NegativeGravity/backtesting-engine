import { useCallback, useEffect, useState } from "react";
import type { RenderProfile } from "../lib/frameScheduler";

export type LayoutPreset = "focus" | "balanced" | "analysis";

export interface DashboardPreferences {
  inspectorWidth: number;
  dockHeight: number;
  dockCollapsed: boolean;
  metricsVisible: boolean;
  renderProfile: RenderProfile;
  diagnosticsVisible: boolean;
  compactMode: boolean;
}

const STORAGE_KEY = "vex.dashboard.preferences.v1";

export const DEFAULT_DASHBOARD_PREFERENCES: DashboardPreferences = {
  inspectorWidth: 300,
  dockHeight: 220,
  dockCollapsed: false,
  metricsVisible: true,
  renderProfile: "smooth",
  diagnosticsVisible: false,
  compactMode: false
};

export function normalizeDashboardPreferences(
  value: Partial<DashboardPreferences>
): DashboardPreferences {
  return {
    inspectorWidth: clampNumber(value.inspectorWidth, 240, 520, DEFAULT_DASHBOARD_PREFERENCES.inspectorWidth),
    dockHeight: clampNumber(value.dockHeight, 120, 520, DEFAULT_DASHBOARD_PREFERENCES.dockHeight),
    dockCollapsed: Boolean(value.dockCollapsed),
    metricsVisible: value.metricsVisible ?? DEFAULT_DASHBOARD_PREFERENCES.metricsVisible,
    renderProfile: normalizeRenderProfile(value.renderProfile),
    diagnosticsVisible: Boolean(value.diagnosticsVisible),
    compactMode: Boolean(value.compactMode)
  };
}

export function loadDashboardPreferences(): DashboardPreferences {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_DASHBOARD_PREFERENCES;
    return normalizeDashboardPreferences(JSON.parse(raw) as Partial<DashboardPreferences>);
  } catch {
    return DEFAULT_DASHBOARD_PREFERENCES;
  }
}

export function saveDashboardPreferences(value: DashboardPreferences): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(normalizeDashboardPreferences(value)));
  } catch {
    return;
  }
}

export function layoutPreset(
  preset: LayoutPreset,
  current: DashboardPreferences
): DashboardPreferences {
  if (preset === "focus") {
    return normalizeDashboardPreferences({
      ...current,
      dockCollapsed: true,
      metricsVisible: false,
      inspectorWidth: 260,
      compactMode: true
    });
  }
  if (preset === "analysis") {
    return normalizeDashboardPreferences({
      ...current,
      dockCollapsed: false,
      metricsVisible: true,
      dockHeight: 320,
      inspectorWidth: 340,
      compactMode: false
    });
  }
  return normalizeDashboardPreferences({
    ...current,
    dockCollapsed: false,
    metricsVisible: true,
    dockHeight: 220,
    inspectorWidth: 300,
    compactMode: false
  });
}

export function useDashboardPreferences(): [
  DashboardPreferences,
  (patch: Partial<DashboardPreferences>) => void,
  (preset: LayoutPreset) => void
] {
  const [preferences, setPreferences] = useState(loadDashboardPreferences);

  useEffect(() => {
    saveDashboardPreferences(preferences);
  }, [preferences]);

  const update = useCallback((patch: Partial<DashboardPreferences>) => {
    setPreferences(current => normalizeDashboardPreferences({ ...current, ...patch }));
  }, []);

  const applyPreset = useCallback((preset: LayoutPreset) => {
    setPreferences(current => layoutPreset(preset, current));
  }, []);

  return [preferences, update, applyPreset];
}

function normalizeRenderProfile(value: unknown): RenderProfile {
  return value === "balanced" || value === "throughput" ? value : "smooth";
}

function clampNumber(
  value: unknown,
  minimum: number,
  maximum: number,
  fallback: number
): number {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(maximum, Math.max(minimum, Math.round(number)));
}
