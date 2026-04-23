import { Link } from "react-router-dom";
import type { Resource } from "../../../../types/library";
import { useLibrarySession } from "../../../../hooks/useLibrarySession";
import { getResourceQueueMetrics } from "../../../../lib/resourceAvailability";

interface Props {
  resource: Resource;
  onRequestBook: () => void;
}

export default function ResourceSidebar({ resource, onRequestBook }: Props) {
  const { user } = useLibrarySession();
  const { availableCopies, borrowableCopies, pendingBorrowRequests, queueFull, canBorrow } = getResourceQueueMetrics(resource);
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
      text: pendingBorrowRequests > 0
        ? `${borrowableCopies} cop${borrowableCopies === 1 ? "y remains" : "ies remain"} available to borrow, with ${pendingBorrowRequests} pending request${pendingBorrowRequests === 1 ? "" : "s"} already in the queue.`
        : availableCopies > 0
          ? `${availableCopies} cop${availableCopies === 1 ? "y is" : "ies are"} currently on the shelf and available to request.`
          : "A copy is currently on the shelf and available to request.",
    },
    queueFull: {
      badge: "bg-amber-500/15 text-amber-100 border border-amber-300/20",
      panel: "bg-amber-500/10 border border-amber-300/15",
      text: "All copies currently on the shelf are already covered by pending requests. You may register for an availability alert and we will email you if a borrowing slot becomes free.",
    },
    borrowed: {
      badge: "bg-amber-500/15 text-amber-100 border border-amber-300/20",
      panel: "bg-amber-500/10 border border-amber-300/15",
      text: "No copies are currently available. Please register for an availability alert and we will email you when one is returned.",
    },
    reserved: {
      badge: "bg-sky-500/15 text-sky-100 border border-sky-300/20",
      panel: "bg-sky-500/10 border border-sky-300/15",
      text: "All copies are presently reserved. Please register for an availability alert and we will email you if availability changes.",
    },
    maintenance: {
      badge: "bg-gray-500/15 text-gray-100 border border-gray-300/20",
      panel: "bg-gray-500/10 border border-gray-300/15",
      text: "This title is temporarily unavailable while it is being processed by the library team.",
    },
    lost: {
      badge: "bg-rose-500/15 text-rose-100 border border-rose-300/20",
      panel: "bg-rose-500/10 border border-rose-300/15",
      text: "This title is currently unavailable for borrowing.",
    },
  };

  const availability = queueFull ? "queueFull" : (resource.availabilityStatus ?? "lost");
  const availabilityStyle = availabilityStyles[availability] ?? availabilityStyles.lost;
  const badgeLabel = queueFull
    ? "Queue at Capacity"
    : canBorrow && pendingBorrowRequests > 0
      ? "Limited Availability"
      : resource.availabilityStatus === "available"
        ? "Available on Shelf"
        : resource.availabilityStatus === "borrowed"
          ? "Currently on Loan"
          : resource.availabilityStatus === "reserved"
            ? "Reserved"
            : resource.availabilityStatus === "maintenance"
              ? "Temporarily Unavailable"
              : "Unavailable";
  const notifyStatuses = ["borrowed", "reserved"];
  const canNotify = queueFull || notifyStatuses.includes(resource.availabilityStatus ?? "");
  const canRequest = canBorrow || canNotify;
  const primaryActionLabel = !user && canBorrow
    ? "Sign In to Borrow"
    : !user && canNotify
      ? "Sign In for Alerts"
      : canBorrow
        ? "Request to Borrow"
        : canNotify
          ? queueFull
            ? "Set Availability Alert"
            : "Set Availability Alert"
          : "Unavailable";
  const primaryActionDisabled = !canRequest;

  return (
    <div className="space-y-5 sticky top-24">
      <div className="bg-[#241453] rounded-2xl p-5">
        <h3 className="font-bold text-white text-base mb-1" style={{ fontFamily: "'Playfair Display', serif" }}>
          Library Record
        </h3>
        <div className={`mt-4 rounded-xl p-3 ${availabilityStyle.panel}`}>
          <div className={`inline-flex px-2.5 py-1 rounded-full text-[11px] font-semibold ${availabilityStyle.badge}`}>
            {badgeLabel}
          </div>
          <p className="mt-2 text-xs leading-5 text-white/75">{availabilityStyle.text}</p>
          {expectedAvailableText && (resource.availabilityStatus === "borrowed" || queueFull) && (
            <div className="mt-3 inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1.5 text-[11px] font-medium text-white/90">
              <i className="ri-calendar-event-line text-[#CEA869]" />
              Next copy expected back on {expectedAvailableText}
            </div>
          )}
        </div>
        <div className="mt-4 grid grid-cols-3 gap-2">
          <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-3">
            <p className="text-[10px] uppercase tracking-wide text-white/45">Copies on Shelf</p>
            <p className="mt-1 text-lg font-bold text-white">{availableCopies}</p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-3">
            <p className="text-[10px] uppercase tracking-wide text-white/45">Available to Borrow</p>
            <p className="mt-1 text-lg font-bold text-white">{borrowableCopies}</p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-3">
            <p className="text-[10px] uppercase tracking-wide text-white/45">Pending Requests</p>
            <p className="mt-1 text-lg font-bold text-white">{pendingBorrowRequests}</p>
          </div>
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
            <i className={canBorrow ? "ri-book-open-line" : canNotify ? "ri-notification-3-line" : "ri-close-circle-line"} />
            {primaryActionLabel}
          </button>
          <Link
            to="/resources"
            className="w-full flex items-center justify-center gap-2 py-3 bg-white/10 hover:bg-white/15 border border-white/15 text-white font-semibold text-sm rounded-xl transition-colors duration-200 cursor-pointer whitespace-nowrap"
          >
            <i className="ri-arrow-left-line" />
            Back to Catalogue
          </Link>
        </div>
      </div>
    </div>
  );
}
