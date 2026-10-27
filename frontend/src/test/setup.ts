import "@testing-library/jest-dom/vitest";
import { focusManager } from "@tanstack/react-query";
import { cleanup, configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// Full pages (the detail page loads several queries) can take over the default 1 s to
// render on a busy or slower machine; findBy* still resolves as soon as the element appears.
configure({ asyncUtilTimeout: 5000 });

// jsdom gaps: <dialog> modal methods, scrollIntoView and matchMedia.
if (typeof HTMLDialogElement !== "undefined") {
  if (typeof HTMLDialogElement.prototype.showModal !== "function") {
    HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
      this.setAttribute("open", "");
    };
  }
  if (typeof HTMLDialogElement.prototype.close !== "function") {
    HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
      this.removeAttribute("open");
    };
  }
}

if (typeof Element.prototype.scrollIntoView !== "function") {
  Element.prototype.scrollIntoView = function scrollIntoView() {};
}

if (typeof window.matchMedia !== "function") {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  focusManager.setFocused(undefined);
  localStorage.clear();
  sessionStorage.clear();
  document.documentElement.classList.remove("dark");
});
