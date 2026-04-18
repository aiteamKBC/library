import type { CSSProperties } from "react";

interface Props {
  title: string;
  author?: string;
  coverImage?: string;
  accentColor?: string;
  className?: string;
  imageClassName?: string;
  compact?: boolean;
}

function buildGradient(accentColor: string) {
  return `linear-gradient(155deg, ${accentColor}22 0%, ${accentColor}52 58%, ${accentColor}85 100%)`;
}

export default function ResourceCover({
  title,
  author,
  coverImage,
  accentColor = "#2B3A55",
  className = "",
  imageClassName = "",
  compact = false,
}: Props) {
  const frameStyle: CSSProperties = {
    background: coverImage ? "linear-gradient(180deg, #ffffff 0%, #f8f3ea 100%)" : buildGradient(accentColor),
    boxShadow: compact
      ? "0 10px 24px rgba(20, 14, 38, 0.12)"
      : "0 22px 50px rgba(20, 14, 38, 0.16)",
  };

  const innerGlowStyle: CSSProperties = coverImage
    ? { background: `radial-gradient(circle at top, ${accentColor}16 0%, transparent 58%)` }
    : { background: "linear-gradient(180deg, rgba(255,255,255,0.18), rgba(255,255,255,0))" };

  return (
    <div
      className={`relative overflow-hidden rounded-[26px] border border-black/6 ${className}`}
      style={frameStyle}
    >
      <div className="absolute inset-0" style={innerGlowStyle} />
      <div className="absolute left-0 top-0 bottom-0 w-5 bg-black/6" />
      <div className="absolute right-0 top-0 h-16 w-16 rounded-full bg-white/18 blur-2xl" />

      {coverImage ? (
        <div className="relative flex h-full w-full items-center justify-center p-3 sm:p-4">
          <img
            src={coverImage}
            alt={`Cover of ${title}`}
            className={`h-full w-full object-contain drop-shadow-[0_18px_28px_rgba(25,18,39,0.18)] ${imageClassName}`}
          />
        </div>
      ) : (
        <div className="relative flex h-full w-full flex-col justify-between p-4 text-white">
          <div className="flex items-start justify-between gap-3">
            <span className="inline-flex h-10 w-10 items-center justify-center rounded-2xl bg-white/18 backdrop-blur-sm">
              <i className="ri-book-3-line text-lg" />
            </span>
            <span className="rounded-full border border-white/16 bg-white/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-white/80">
              Library Copy
            </span>
          </div>
          <div className="rounded-2xl bg-black/8 p-3 backdrop-blur-[2px]">
            <p className={`font-semibold leading-snug ${compact ? "line-clamp-2 text-sm" : "line-clamp-3 text-base"}`}>
              {title}
            </p>
            {author && (
              <p className="mt-2 line-clamp-2 text-xs text-white/72">
                {author}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
