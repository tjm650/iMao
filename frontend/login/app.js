const form = document.querySelector("#voucher-form");
const message = document.querySelector("#message");
const voucherInput = form.elements.voucher;
const submitButton = form.querySelector("button");

voucherInput.addEventListener("input", () => {
  const raw = voucherInput.value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 16);
  voucherInput.value = raw.match(/.{1,4}/g)?.join("-") || "";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  message.classList.remove("success");
  message.textContent = "";
  submitButton.disabled = true;
  submitButton.textContent = "Verifying voucher…";
  try {
    const response = await fetch("/api/auth/voucher", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      cache: "no-store",
      body: JSON.stringify({ code: voucherInput.value.replace(/-/g, "") })
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || "We couldn't verify that voucher. Please try again.");
    message.classList.add("success");
    message.textContent = "Voucher verified. Preparing your connection…";
    window.location.assign("/connected");
  } catch (error) {
    message.textContent = error instanceof TypeError
      ? "Connection interrupted. Check that you're connected to the wiMao Wi-Fi network and try again."
      : (error.message || "Unable to connect. Please try again.");
    voucherInput.focus();
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "Connect to internet";
  }
});
