(function () {
  "use strict";

  var SUCCESS_DURATION = 1000;
  var toastStack = null;
  var activeErrorModal = null;

  function ensureToastStack() {
    if (toastStack) return toastStack;
    toastStack = document.createElement("div");
    toastStack.className = "edu-toast-stack";
    toastStack.setAttribute("aria-live", "polite");
    toastStack.setAttribute("aria-atomic", "false");
    document.body.appendChild(toastStack);
    return toastStack;
  }

  function normalizeType(tags) {
    var value = String(tags || "success").toLowerCase();
    if (value.indexOf("error") !== -1) return "error";
    if (value.indexOf("warning") !== -1) return "warning";
    if (value.indexOf("success") !== -1) return "success";
    if (value.indexOf("info") !== -1) return "info";
    return "success";
  }

  function iconSvg(type) {
    if (type === "success") {
      return (
        '<svg class="edu-notify-icon-svg" viewBox="0 0 24 24" aria-hidden="true">' +
        '<circle class="edu-notify-icon-ring" cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="1.8"/>' +
        '<path class="edu-notify-icon-mark" d="M8 12.2 10.8 15 16 9.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>' +
        "</svg>"
      );
    }
    if (type === "warning") {
      return (
        '<svg class="edu-notify-icon-svg" viewBox="0 0 24 24" aria-hidden="true">' +
        '<path class="edu-notify-icon-mark" d="M12 3.5 2.5 20h19L12 3.5z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>' +
        '<path d="M12 9v5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>' +
        '<circle cx="12" cy="17" r="1" fill="currentColor"/>' +
        "</svg>"
      );
    }
    return (
      '<svg class="edu-notify-icon-svg" viewBox="0 0 24 24" aria-hidden="true">' +
      '<circle class="edu-notify-icon-ring" cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="1.8"/>' +
      '<path class="edu-notify-icon-mark" d="M8.5 8.5 15.5 15.5M15.5 8.5 8.5 15.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>' +
      "</svg>"
    );
  }

  function dismissToast(toast) {
    if (!toast || toast.classList.contains("is-leaving")) return;
    toast.classList.add("is-leaving");
    window.setTimeout(function () {
      toast.remove();
    }, 280);
  }

  function showSuccess(message) {
    var stack = ensureToastStack();
    var toast = document.createElement("div");
    toast.className = "edu-toast edu-toast-success";
    toast.setAttribute("role", "status");
    toast.innerHTML =
      '<span class="edu-toast-icon" aria-hidden="true">' + iconSvg("success") + "</span>" +
      '<p class="edu-toast-text"></p>';
    toast.querySelector(".edu-toast-text").textContent = message;
    stack.appendChild(toast);
    window.requestAnimationFrame(function () {
      toast.classList.add("is-visible");
    });
    window.setTimeout(function () {
      dismissToast(toast);
    }, SUCCESS_DURATION);
  }

  function closeErrorModal() {
    if (!activeErrorModal) return;
    var modal = activeErrorModal;
    activeErrorModal = null;
    modal.classList.add("is-leaving");
    document.body.classList.remove("modal-open");
    window.setTimeout(function () {
      modal.remove();
    }, 240);
  }

  function showError(message, type) {
    var kind = type === "warning" ? "warning" : "error";
    if (activeErrorModal) closeErrorModal();

    var modal = document.createElement("div");
    modal.className = "edu-notify-modal edu-notify-modal-" + kind;
    modal.setAttribute("role", "alertdialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "edu-notify-title");
    modal.innerHTML =
      '<div class="edu-notify-backdrop" data-edu-notify-close></div>' +
      '<div class="edu-notify-dialog">' +
      '<div class="edu-notify-icon-wrap" aria-hidden="true">' +
      iconSvg(kind) +
      '<span class="edu-notify-pulse"></span>' +
      '<span class="edu-notify-pulse edu-notify-pulse-delay"></span>' +
      "</div>" +
      '<h2 id="edu-notify-title" class="edu-notify-title">' +
      (kind === "warning" ? "Warning" : "Something went wrong") +
      "</h2>" +
      '<p class="edu-notify-message"></p>' +
      '<div class="edu-notify-actions">' +
      '<button type="button" class="ghost-button edu-notify-cancel" data-edu-notify-close>Cancel</button>' +
      "</div>" +
      "</div>";

    modal.querySelector(".edu-notify-message").textContent = message;
    document.body.appendChild(modal);
    activeErrorModal = modal;
    document.body.classList.add("modal-open");

    window.requestAnimationFrame(function () {
      modal.classList.add("is-visible");
    });

    modal.addEventListener("click", function (event) {
      if (event.target.closest("[data-edu-notify-close]")) {
        closeErrorModal();
      }
    });

    document.addEventListener(
      "keydown",
      function onKey(event) {
        if (event.key === "Escape" && activeErrorModal === modal) {
          closeErrorModal();
          document.removeEventListener("keydown", onKey);
        }
      },
      { once: false }
    );
  }

  function notify(message, type) {
    var kind = normalizeType(type);
    if (kind === "success") {
      showSuccess(message);
    } else {
      showError(message, kind);
    }
  }

  function bootFromDom() {
    var flashNode = document.getElementById("app-flash-messages");
    if (flashNode && flashNode.textContent.trim()) {
      try {
        var flashMessages = JSON.parse(flashNode.textContent);
        flashMessages.forEach(function (entry) {
          notify(entry.text, entry.type);
        });
      } catch (error) {}
    }

    document.querySelectorAll("[data-notify-on-load]").forEach(function (node) {
      var text = (node.textContent || "").trim();
      if (!text) return;
      notify(text, node.getAttribute("data-notify-on-load") || "error");
      node.remove();
    });
  }

  window.EduNotify = {
    success: showSuccess,
    error: function (message) {
      showError(message, "error");
    },
    warning: function (message) {
      showError(message, "warning");
    },
    notify: notify,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootFromDom);
  } else {
    bootFromDom();
  }
})();
