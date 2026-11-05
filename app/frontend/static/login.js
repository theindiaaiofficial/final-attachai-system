import { api } from "./api.js";

document.getElementById("login-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  const error = document.getElementById("login-error");
  const field = form.elements.api_key;
  button.disabled = true; button.textContent = "Signing in…"; error.hidden = true;
  try {
    await api("/admin/auth/login", { method: "POST", body: { api_key: field.value } });
    field.value = "";
    location.replace("/admin#overview");
  } catch (failure) {
    field.value = ""; error.textContent = failure.message; error.hidden = false;
  } finally { button.disabled = false; button.textContent = "Sign in to Orbit →"; }
});
