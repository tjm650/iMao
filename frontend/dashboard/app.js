const used = document.querySelector("#used");
const remaining = document.querySelector("#remaining");
const progress = document.querySelector("#progress");
const status = document.querySelector("#status");
const logoutButton = document.querySelector("#logout");

const formatBytes = (bytes) => {
  const mb = bytes / (1024 * 1024);
  return mb >= 100 ? `${Math.round(mb)} MB` : `${mb.toFixed(1)} MB`;
};

async function refreshSession() {
  try {
    const response = await fetch("/api/session", { credentials: "same-origin" });
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
  } catch (error) {
    status.textContent = error.message || "Connection status unavailable";
  }
}

logoutButton.addEventListener("click", async () => {
  logoutButton.disabled = true;
  try {
    await fetch("/api/logout", { method: "POST", credentials: "same-origin" });
    window.location.replace("/");
  } catch {
    status.textContent = "Unable to log out. Please try again.";
    logoutButton.disabled = false;
  }
});

refreshSession();
