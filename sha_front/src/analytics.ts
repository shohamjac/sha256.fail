declare global {
  interface Window {
    /** Set by the Google Analytics tag in index.html; missing on local dev servers. */
    gtag?: (...args: unknown[]) => void;
  }
}

/**
 * The URL a page view is reported under. GA drops everything after the #, so the route is
 * turned into a path: `#/rules` on `/sha256.fail/` becomes `/sha256.fail/rules`.
 */
export function pageLocation(origin: string, pathname: string, route: string): string {
  return origin + pathname.replace(/\/(index\.html)?$/, '') + (route.replace(/^#/, '') || '/');
}

/** Reports a page view for `route` under the current tab title. */
export function trackPageView(route: string): void {
  window.gtag?.('event', 'page_view', {
    page_location: pageLocation(window.location.origin, window.location.pathname, route),
    page_title: document.title,
  });
}
