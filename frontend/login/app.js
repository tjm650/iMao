const form = document.querySelector("#voucher-form");
const message = document.querySelector("#message");
const submitButton = form.querySelector("button");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  message.textContent = "";
  submitButton.disabled = true;
  submitButton.textContent = "Connecting…";

  try {
    const response = await fetch("/api/auth/voucher", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ code: form.elements.voucher.value.trim() })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Unable to validate voucher");

    message.classList.add("success");
    message.textContent = "Voucher accepted. Your session is active.";
    form.reset();
    window.location.assign("/connected");
  } catch (error) {
    message.classList.remove("success");
    message.textContent = error.message || "Unable to connect. Please try again.";
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "Connect to internet";
  }
});
