import { Link } from "react-router-dom";
import type { Resource } from "../../../../types/library";

interface Props {
  resource: Resource;
  onRequestBook: () => void;
}

export default function ResourceSidebar({ resource, onRequestBook }: Props) {
  const expectedAvailableText = resource.expectedAvailableDate
    ? new Date(resource.expectedAvailableDate).toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
    })
    : null;
  const availabilityStyles: Record<string, { badge: string; panel: string; text: string }> = {
    available: {
      badge: "bg-emerald-500/15 text-emerald-100 border border-emerald-300/20",
      panel: "bg-emerald-500/10 border border-emerald-300/15",
      text: "This copy is currently on the shelf and ready to borrow.",
    },
    borrowed: {
      badge: "bg-amber-500/15 text-amber-100 border border-amber-300/20",
      panel: "bg-amber-500/10 border border-amber-300/15",
      text: "The only copy is currently borrowed, so the next student should reserve it.",
    },
    reserved: {
      badge: "bg-sky-500/15 text-sky-100 border border-sky-300/20",
      panel: "bg-sky-500/10 border border-sky-300/15",
      text: "The only copy is already reserved and not available for a new loan right now.",
    },
    maintenance: {
      badge: "bg-gray-500/15 text-gray-100 border border-gray-300/20",
      panel: "bg-gray-500/10 border border-gray-300/15",
      text: "This copy is temporarily unavailable while it is being handled by the library team.",
    },
    lost: {
      badge: "bg-rose-500/15 text-rose-100 border border-rose-300/20",
      panel: "bg-rose-500/10 border border-rose-300/15",
      text: "This copy is currently unavailable and cannot be borrowed.",
    },
  };
  const availability = resource.availabilityStatus ?? "lost";
  const availabilityStyle = availabilityStyles[availability] ?? availabilityStyles.lost;
  const primaryActionLabel = resource.canBorrow
    ? "Borrow This Book"
    : resource.canReserve
      ? "Reserve This Book"
      : "Unavailable Right Now";
  const primaryActionDisabled = !resource.canBorrow && !resource.canReserve;
  return (
    <div className="space-y-5 sticky top-24">
      <div className="bg-[#241453] rounded-2xl p-5">
        <h3 className="font-bold text-white text-base mb-1" style={{ fontFamily: "'Playfair Display', serif" }}>
          Library Record
        </h3>
        <div className={`mt-4 rounded-xl p-3 ${availabilityStyle.panel}`}>
          <div className={`inline-flex px-2.5 py-1 rounded-full text-[11px] font-semibold ${availabilityStyle.badge}`}>
            {resource.availabilityLabel ?? "Unavailable"}
          </div>
          <p className="mt-2 text-xs leading-5 text-white/75">{availabilityStyle.text}</p>
          {resource.availabilityNote && (
            <p className="mt-2 text-xs leading-5 text-[#F9F4EC]">
              {resource.availabilityNote}
            </p>
          )}
          {expectedAvailableText && resource.availabilityStatus === "borrowed" && (
            <div className="mt-3 inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1.5 text-[11px] font-medium text-white/90">
              <i className="ri-calendar-event-line text-[#CEA869]" />
              Expected available on {expectedAvailableText}
            </div>
          )}
        </div>
        <div className="space-y-3 mt-5">
          <button
            onClick={onRequestBook}
            disabled={primaryActionDisabled}
            className={`w-full flex items-center justify-center gap-2 py-3 text-sm rounded-xl transition-colors duration-200 whitespace-nowrap ${
              primaryActionDisabled
                ? "bg-white/10 text-white/40 cursor-not-allowed"
                : "bg-[#CEA869] hover:bg-[#B27715] text-[#241453] font-bold cursor-pointer"
            }`}
          >
            <i className={resource.canBorrow ? "ri-book-open-line" : "ri-bookmark-line"} />
            {primaryActionLabel}
          </button>
          <Link
            to="/resources"
            className="w-full flex items-center justify-center gap-2 py-3 bg-white/10 hover:bg-white/15 border border-white/15 text-white font-semibold text-sm rounded-xl transition-colors duration-200 cursor-pointer whitespace-nowrap"
          >
            <i className="ri-arrow-left-line" />
            Back to Books
          </Link>
        </div>
      </div>
    </div>
  );
}
