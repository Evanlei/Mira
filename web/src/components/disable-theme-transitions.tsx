"use client";

import { useEffect } from "react";

/** On an OS theme change, suspend all transitions for one frame so colors don't smear (better-ui recipe). */
export function DisableThemeTransitions() {
  useEffect(() => {
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = () => {
      const style = document.createElement("style");
      style.append(document.createTextNode("*,*::before,*::after{transition:none !important}"));
      document.head.append(style);
      void document.body.offsetHeight; // force a synchronous style flush
      requestAnimationFrame(() => requestAnimationFrame(() => style.remove()));
    };
    mql.addEventListener("change", handleChange);
    return () => mql.removeEventListener("change", handleChange);
  }, []);
  return null;
}
