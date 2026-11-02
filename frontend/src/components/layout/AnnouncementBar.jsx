import { useState } from "react";

// Brent's wording (2 Nov 2026). The website adds "Click to get started!" because
// its bar links here; on the app there is nothing further to click through to.
const MESSAGE = "Primble is in Beta and welcomes new users. Additional features and upgrades publish weekly.";
const DISMISSED_KEY = "primble_announcement_dismissed";

function wasDismissed() {
  try {
    return sessionStorage.getItem(DISMISSED_KEY) === "1";
  } catch {
    return false;
  }
}

export default function AnnouncementBar() {
  const [dismissed, setDismissed] = useState(wasDismissed);
  if (dismissed) return null;

  const dismiss = () => {
    setDismissed(true);
    try {
      sessionStorage.setItem(DISMISSED_KEY, "1");
    } catch {
      // The bar stays closed until the page reloads.
    }
  };

  return (
    <div className="announcement-bar" role="region" aria-label="Announcement">
      {MESSAGE}
      <button type="button" className="announcement-bar-close" onClick={dismiss} aria-label="Close announcement">×</button>
    </div>
  );
}
