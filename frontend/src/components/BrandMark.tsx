import { useId } from "react";

/** The ShopFlow mark: a coin whose edge flows into an upward stroke. Decorative. */
export function BrandMark({ className = "" }: { className?: string }) {
  const gradient = useId(); // unique, so two marks on a page never share an id
  return (
    <svg viewBox="0 0 40 40" aria-hidden="true" className={className}>
      <defs>
        <linearGradient id={gradient} x1="6" y1="4" x2="34" y2="36" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#6ee7b7" />
          <stop offset="1" stopColor="#059669" />
        </linearGradient>
      </defs>
      <rect width="40" height="40" rx="11" fill={`url(#${gradient})`} />
      <circle cx="20" cy="20" r="10.5" fill="none" stroke="#04211b" strokeWidth="2.6" strokeOpacity="0.9" />
      <path d="M14.5 23.5l4-4 3 3 5-5.5" fill="none" stroke="#04211b" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
