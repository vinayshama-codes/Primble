// Minimal notification service worker.
// Versioned via the comment below — bump to force browsers to detect an update
// (the SW file is byte-compared; any change triggers install of the new worker).
// SW_VERSION: 2026-05-25-3

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

// Pages can postMessage({ type: "SHOW_NOTIFICATION", title, body, tag })
// so the SW shows the toast even if registration.showNotification on the page
// side hit a race condition. Treated as a backup to direct showNotification.
self.addEventListener("message", (event) => {
  const data = event.data || {};
  if (data.type !== "SHOW_NOTIFICATION") return;
  const { title, body, tag, requireInteraction, icon, badge } = data;
  if (!title) return;
  const opts = {
    body: body || "",
    tag: tag || `primble-${Date.now()}`,
    requireInteraction: !!requireInteraction,
    silent: false,
  };
  if (icon) opts.icon = icon;
  if (badge) opts.badge = badge;
  event.waitUntil(self.registration.showNotification(title, opts));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((clientsList) => {
        for (const client of clientsList) {
          if ("focus" in client) return client.focus();
        }
        if (self.clients.openWindow) return self.clients.openWindow("/");
        return undefined;
      })
  );
});
