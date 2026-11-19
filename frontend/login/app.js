const form = document.querySelector("#voucher-form");
const message = document.querySelector("#message");

form.addEventListener("submit", (event) => {
  event.preventDefault();
  message.textContent = "Voucher sign-in will be enabled in the authentication stage.";
});
