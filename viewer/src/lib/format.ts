import type { Site } from '$lib/types';

/** Shared display helpers used across routes and components. */

export function siteLabel(site: Site): string {
  return site.label || `${site.family}:${site.code}`;
}

export function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short'
  }).format(new Date(value));
}

export function lineCount(value: string): number {
  if (!value) return 0;
  return value.split('\n').length;
}
