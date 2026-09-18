"use client";

import { useEffect, useState, type RefObject } from "react";

/**
 * Reports whether an element has entered the viewport. Latches to true on first sighting:
 * page grids use it to decide when to render a thumbnail, and once rendered there is no
 * reason to unrender it.
 */
export function useInView(
  ref: RefObject<HTMLElement | null>,
  rootMargin = "600px 0px",
): boolean {
  // Without an observer there is no way to know, so assume visible and render everything.
  const [inView, setInView] = useState(() => typeof IntersectionObserver === "undefined");

  useEffect(() => {
    const element = ref.current;
    if (!element || inView) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setInView(true);
          observer.disconnect();
        }
      },
      { rootMargin },
    );

    observer.observe(element);
    return () => observer.disconnect();
  }, [ref, rootMargin, inView]);

  return inView;
}
