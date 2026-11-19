const used = document.querySelector("#used");
const remaining = document.querySelector("#remaining");
const progress = document.querySelector("#progress");
const track = document.querySelector("#usage-track");
const status = document.querySelector("#status");
const updated = document.querySelector("#updated");
const logoutButton = document.querySelector("#logout");

const formatBytes = (bytes) => {
  const mb = bytes / (1024 * 1024);
  return mb >= 100 ? `${Math.round(mb)} MB` : `${mb.toFixed(1)} MB`;
};

async function refreshSession() {
  try {
    const response = await fetch("/api/session", { credentials: "same-origin", cache: "no-store" });
    if (response.status === 401) {
      window.location.replace("/");
      return;
    }
    const session = await response.json();
    if (!response.ok) throw new Error(session.detail || "Unable to load session");
    used.textContent = formatBytes(session.used_bytes);
    remaining.textContent = formatBytes(session.remaining_bytes);
    const percent = session.quota_bytes > 0
      ? Math.min(100, session.used_bytes / session.quota_bytes * 100) : 100;
    progress.style.width = `${percent}%`;
    track.setAttribute("aria-valuenow", String(Math.round(percent)));
    status.textContent = "";
    updated.textContent = "Usage updated just now";
  } catch (error) {
    status.textContent = error.message || "Connection status unavailable";
    updated.textContent = "Waiting to refresh connection details…";
  }
}

logoutButton.addEventListener("click", async () => {
  logoutButton.disabled = true;
  logoutButton.textContent = "Ending session…";
  try {
    const response = await fetch("/api/logout", { method: "POST", credentials: "same-origin" });
    if (!response.ok) throw new Error("Unable to end your session");
    window.location.replace("/");
  } catch {
    status.textContent = "Unable to log out. Please try again.";
    logoutButton.disabled = false;
    logoutButton.textContent = "Log out";
  }
});

refreshSession();
window.setInterval(refreshSession, 5000);
