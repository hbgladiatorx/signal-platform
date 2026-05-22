import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge Tailwind classes intelligently, deduplicating conflicting utilities.
 * Used throughout the UI components.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
