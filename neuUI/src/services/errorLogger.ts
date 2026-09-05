/**
 * Error Logger Service
 * Centralized error tracking and reporting
 */

interface ErrorLogEntry {
  timestamp: number;
  message: string;
  stack?: string;
  componentStack?: string;
  userAgent?: string;
  url?: string;
}

class ErrorLogger {
  private logs: ErrorLogEntry[] = [];
  private maxLogs = 100;
  private listeners: ((error: ErrorLogEntry) => void)[] = [];

  init() {
    // Capture global errors
    if (typeof window !== 'undefined') {
      window.onerror = (message, source, lineno, colno, error) => {
        this.log({
          message: String(message),
          stack: error?.stack,
          url: source,
        });
        return false;
      };

      // Capture unhandled promise rejections
      window.addEventListener('unhandledrejection', (event) => {
        this.log({
          message: `Unhandled Promise Rejection: ${event.reason}`,
          stack: event.reason?.stack,
        });
      });

      // Capture React errors
      window.addEventListener('error', (event) => {
        if (event.message.includes('Minified React Error')) {
          this.log({
            message: event.message,
            componentStack: (event as ErrorEvent).error?.componentStack,
          });
        }
      });
    }

    console.info('[ErrorLogger] Initialized');
  }

  log(entry: Partial<ErrorLogEntry>) {
    const fullEntry: ErrorLogEntry = {
      timestamp: Date.now(),
      message: entry.message || 'Unknown error',
      stack: entry.stack,
      componentStack: entry.componentStack,
      userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : undefined,
      url: typeof window !== 'undefined' ? window.location.href : undefined,
    };

    this.logs.push(fullEntry);

    // Keep only recent logs
    if (this.logs.length > this.maxLogs) {
      this.logs.shift();
    }

    // Notify listeners
    this.listeners.forEach((listener) => listener(fullEntry));

    // Log to console in development
    if (import.meta.env.DEV) {
      console.error('[ErrorLogger]', fullEntry);
    }

    // Send to server if configured
    this.sendToServer(fullEntry);
  }

  onError(listener: (error: ErrorLogEntry) => void) {
    this.listeners.push(listener);
    return () => {
      this.listeners = this.listeners.filter((l) => l !== listener);
    };
  }

  getLogs(): ErrorLogEntry[] {
    return [...this.logs];
  }

  clearLogs() {
    this.logs = [];
  }

  private async sendToServer(entry: ErrorLogEntry) {
    try {
      // Only send in production or if explicitly configured
      if (!import.meta.env.PROD && !import.meta.env.VITE_ERROR_REPORTING_URL) {
        return;
      }

      const url = import.meta.env.VITE_ERROR_REPORTING_URL || '/api/errors';
      await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(entry),
        // Don't wait for response
      }).catch(() => {
        // Silently fail - don't create recursive errors
      });
    } catch {
      // Ignore errors in error reporting
    }
  }
}

// Export singleton instance
export const errorLogger = new ErrorLogger();
export default errorLogger;

// Helper function for init
export function initErrorLogger() {
  errorLogger.init();
}
