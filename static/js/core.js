(function () {
  document.addEventListener("input", function (event) {
    const target = event.target;
    if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) return;
    if (
      target.type === "email" ||
      target.type === "password" ||
      target.type === "file" ||
      target.type === "checkbox" ||
      target.type === "hidden" ||
      target.type === "number" ||
      target.type === "tel" ||
      target.type === "date"
    ) {
      return;
    }
    const forceUpper =
      target.classList.contains("uppercase-input") || Boolean(target.closest("[data-grade-form]"));
    if (!forceUpper) return;
    const upper = target.value.toUpperCase();
    if (upper === target.value) return;
    if (typeof target.selectionStart === "number") {
      const start = target.selectionStart;
      const end = target.selectionEnd;
      target.value = upper;
      try {
        target.setSelectionRange(start, end);
      } catch (error) {}
    } else {
      target.value = upper;
    }
  });

  document.addEventListener("click", function (event) {
    const button = event.target.closest(".password-toggle");
    if (!button) return;
    const wrap = button.closest(".password-input");
    const input = wrap ? wrap.querySelector("input") : button.previousElementSibling;
    if (!(input instanceof HTMLInputElement)) return;
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    button.classList.toggle("is-visible", show);
    button.setAttribute("aria-pressed", show ? "true" : "false");
    button.setAttribute("aria-label", show ? "Hide password" : "Show password");
  });
})();
