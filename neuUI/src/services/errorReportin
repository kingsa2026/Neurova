/**
 * Error Reporting Service
 * Utility functions for manual error reporting to Sentry
 */
import { captureException, captureMessage, addBreadcrumb, setUser } from "@sentry/react";
/**
 * Report a handled error with context
 */
export function reportError(error: Error, context?: Record&lt;string, unknown&gt;): void {
  if (import.meta.env.DEV) {
    console.error("[Sentry] Reporting error:", error, context);
  }
  captureException(error, { extra: context });
}
/**
 * Report a custom message
 */
export function reportMessage(
  message: string,
  level: "debug" | "info" | "warning" | "error" = "info"
): void {
  if (import.meta.env.DEV) {
    console.info(`[Sentry] ${level}:`, message);
  }
  captureMessage(message, { level });
}
/**
 * Add a breadcrumb for debugging
 */
export function addErrorBreadcrumb(
  message: string,
  category: string = "custom",
  data?: Record&lt;string, unknown&gt;
): void {
  addBreadcrumb({
    message,
    category,
    data,
    timestamp: Date.now(),
  });
}
/**
 * Set user context for error tracking
 */
export function setErrorUser(user: {
  id: string;
  username?: string;
  email?: string;
}): void {
  setUser(user);
}
/**
 * Clear user context (e.g., on logout)
 */
export function clearErrorUser(): void {
  setUser(null);
}
/**
 * API Error wrapper
 * Automatically reports API errors to Sentry
 */
export async function reportApiError(
  url: string,
  method: string,
  status: number,
  response?: unknown
): Promise&lt;void&gt; {
  const error = new Error(`API Error: ${method} ${url} - ${status}`);
  (error as Error &amp; { status: number }).status = status;
  reportError(error, {
    url,
    method,
    status,
    response: typeof response === "string" ? response.slice(0, 500) : response,
  });
}
&nbsp;