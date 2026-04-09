import { useState } from "react";
import { useAdminData } from "../../../hooks/useAdminData";

interface Props {
  onClose: () => void;
  initialBookTitle?: string;
  initialResourceId?: string;
  initialCategory?: string;
  expectedAvailableDate?: string | null;
  availabilityNote?: string;
  mode?: "request" | "borrow" | "reserve";
}

export default function RequestModal({
  onClose,
  initialBookTitle = "",
  initialResourceId,
  initialCategory,
  expectedAvailableDate,
  availabilityNote,
  mode = "request",
}: Props) {
  const { addRequest, addLoan, categories } = useAdminData();
  const [requestMode] = useState(mode);
  const categoryNames = categories.map((category) => category.name);
  const defaultCategory = categoryNames[0] ?? "";
  const [form, setForm] = useState({
    studentName: "",
    studentEmail: "",
    studentPhone: "",
    bookTitle: initialBookTitle,
    category: initialCategory ?? defaultCategory,
    reason: "",
    neededFrom: "",
    neededUntil: "",
  });
  const [submitted, setSubmitted] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [closing, setClosing] = useState(false);
  const copy = {
    request: {
      title: "Request a New Book",
      subtitle: "Use this form to suggest a book that is not currently available in the library collection.",
      button: "Submit Book Request",
      successTitle: "Request Submitted",
      successText: "Our librarians will review your request and consider adding this title to the collection.",
      successSubtitle: "Your new book request has been received successfully.",
      successBadge: "BOOK REQUEST",
      successBadgeClass: "bg-[#F3E9DA] text-[#8A5A14]",
      successIconClass: "ri-bookmark-line text-[#8A5A14]",
      successIconWrapClass: "bg-[#FFF4DD]",
    },
    borrow: {
      title: "Borrow This Book",
      subtitle: "This title is available now. Send your request and the library team can confirm checkout.",
      button: "Submit Borrow Request",
      successTitle: "Borrow Request Received",
      successText: "Your request to borrow this book is now pending library confirmation. We will contact you once your checkout is approved.",
      successSubtitle: "This book is available now and your borrow request has been sent for review.",
      successBadge: "BORROW REQUEST",
      successBadgeClass: "bg-[#E8F7EF] text-[#127A49]",
      successIconClass: "ri-book-open-line text-[#127A49]",
      successIconWrapClass: "bg-emerald-50",
    },
    reserve: {
      title: "Reserve This Book",
      subtitle: "This title is currently unavailable. Join the queue and the library team will contact you.",
      button: "Submit Reservation",
      successTitle: "Added to Reservation Queue",
      successText: "You have been added to the waiting list for this book. We will contact you as soon as a copy becomes available.",
      successSubtitle: "This title is currently unavailable, so your reservation has been placed in the queue.",
      successBadge: "RESERVATION REQUEST",
      successBadgeClass: "bg-[#EEF3FF] text-[#3154A3]",
      successIconClass: "ri-bookmark-line text-[#3154A3]",
      successIconWrapClass: "bg-[#EEF3FF]",
    },
  }[requestMode];
  const expectedDateLabel = expectedAvailableDate
    ? new Date(expectedAvailableDate).toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
    })
    : null;
  const humanizeField = (key: string) => {
    const labels: Record<string, string> = {
      borrowerEmail: "email address",
      borrowerName: "name",
      borrowerPhone: "phone number",
      studentEmail: "email address",
      studentName: "name",
      studentPhone: "phone number",
      neededFrom: "start date",
      neededUntil: "end date",
      book_copy: "book copy",
      resourceId: "book",
      requestedFrom: "reservation start date",
    };
    return labels[key] ?? key;
  };

  const flattenStructuredError = (value: unknown): string | null => {
    if (typeof value === "string") {
      return value;
    }
    if (Array.isArray(value)) {
      const firstString = value.find((item) => typeof item === "string");
      return typeof firstString === "string" ? firstString : null;
    }
    if (value && typeof value === "object") {
      for (const [key, nestedValue] of Object.entries(value)) {
        const nestedMessage = flattenStructuredError(nestedValue);
        if (nestedMessage) {
          return `${humanizeField(key)}: ${nestedMessage}`;
        }
      }
    }
    return null;
  };

  const formatSubmitError = (message: string) => {
    const trimmedMessage = message.trim();
    if (trimmedMessage.startsWith("{")) {
      try {
        const parsed = JSON.parse(trimmedMessage) as unknown;
        const structuredMessage = flattenStructuredError(parsed);
        if (structuredMessage) {
          return formatSubmitError(structuredMessage);
        }
      } catch {
        // Fall back to the raw message below.
      }
    }
    if (trimmedMessage.includes("Enter a valid email address")) {
      return "Please enter a valid email address.";
    }
    if (trimmedMessage.includes("Please enter your full name in the name field")) {
      return "Please enter your full name in the name field.";
    }
    if (trimmedMessage.includes("email address")) {
      return trimmedMessage;
    }
    if (trimmedMessage.includes("active reservation")) {
      return "This copy is already reserved for another student. Please try a different book or contact the librarian.";
    }
    if (trimmedMessage.includes("not currently available to borrow")) {
      return "This book is no longer available to borrow right now. Please refresh the page and try reserving it instead.";
    }
    if (trimmedMessage.includes("Only borrowed books can be reserved")) {
      return "This book is not in a borrowed state right now, so a reservation cannot be placed.";
    }
    if (trimmedMessage.includes("Borrower details are required")) {
      return "Please enter your name and email before submitting.";
    }
    if (trimmedMessage.includes("phone number is required")) {
      return "Please add your phone number so the library team can contact you.";
    }
    if (trimmedMessage.includes("cannot start before")) {
      return trimmedMessage;
    }
    if (trimmedMessage.includes("KBC account sign-in")) {
      return "Please complete the required details before submitting this request.";
    }
    if (trimmedMessage.includes("verified student sign-in")) {
      return "Please complete the required details before continuing.";
    }
    if (trimmedMessage.includes("verify your student email")) {
      return "Please complete the required details before continuing.";
    }
    return trimmedMessage;
  };

  const minNeededFrom = requestMode === "reserve" && expectedAvailableDate
    ? expectedAvailableDate
    : undefined;
  const isGeneralRequest = requestMode === "request";
  const isValidUkPhone = (value: string) => {
    const normalized = value.replace(/[\s()-]/g, "");
    return /^(?:\+44|0)7\d{9}$/.test(normalized) || /^(?:\+44|0)(?:1|2)\d{8,9}$/.test(normalized);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) {
      return;
    }
    setSubmitError("");
    if (form.studentName.includes("@")) {
      setSubmitError("Please enter your full name in the name field.");
      return;
    }
    if (!isValidUkPhone(form.studentPhone)) {
      setSubmitError("Please enter a valid UK phone number, for example 07123 456789 or +44 7123 456789.");
      return;
    }
    setSubmitting(true);
    try {
      if (requestMode === "request") {
        await addRequest({
          studentName: form.studentName,
          studentEmail: form.studentEmail,
          studentPhone: form.studentPhone,
          bookTitle: form.bookTitle,
          category: form.category,
          reason: form.reason,
        });
      } else {
        await addLoan({
          borrowerName: form.studentName,
          borrowerEmail: form.studentEmail,
          borrowerPhone: form.studentPhone,
          resourceId: initialResourceId,
          requestedFrom: form.neededFrom || undefined,
          status: requestMode === "borrow" ? "borrowed" : "reserved",
          dueDate: form.neededUntil || undefined,
          notes: form.reason || undefined,
        });
      }
      setSubmitted(true);
    } catch (error) {
      const rawMessage = error instanceof Error ? error.message : "We could not complete your request right now.";
      setSubmitError(formatSubmitError(rawMessage));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDone = () => {
    if (closing) {
      return;
    }
    setClosing(true);
    window.setTimeout(() => {
      onClose();
    }, 250);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
      <div className="relative bg-white rounded-2xl w-full max-w-lg shadow-xl">
        {submitError && (
          <div className="absolute inset-0 z-10 flex items-center justify-center p-6 bg-white/55 backdrop-blur-[2px] rounded-2xl">
            <div className="w-full max-w-md rounded-2xl border border-amber-200 bg-[#FFF9F0] shadow-2xl">
              <div className="flex items-start gap-3 px-5 py-5">
                <div className="w-10 h-10 flex-none rounded-full bg-amber-100 flex items-center justify-center">
                  <i className="ri-information-line text-amber-700 text-lg" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-[#5C4520] leading-6">{submitError}</p>
                </div>
                <button
                  type="button"
                  onClick={() => setSubmitError("")}
                  className="w-7 h-7 flex items-center justify-center rounded-lg hover:bg-gray-100 cursor-pointer"
                >
                  <i className="ri-close-line text-gray-400" />
                </button>
              </div>
            </div>
          </div>
        )}
        <div className="flex items-center justify-between p-6 border-b border-gray-100">
          <div>
            <h2 className="font-bold text-[#241453] text-lg" style={{ fontFamily: "'Playfair Display', serif" }}>
              {submitted ? copy.successTitle : copy.title}
            </h2>
            <p className="text-gray-400 text-xs mt-0.5">
              {submitted ? copy.successSubtitle : copy.subtitle}
            </p>
            {!submitted && (availabilityNote || expectedDateLabel) && requestMode === "reserve" && (
              <div className="mt-3 rounded-xl border border-amber-200 bg-[#FFF8EC] px-3.5 py-3">
                <div className="flex items-start gap-2">
                  <i className="ri-time-line text-amber-700 mt-0.5" />
                  <div className="min-w-0">
                    {expectedDateLabel && (
                      <p className="text-xs font-semibold text-[#5C4520]">
                        Expected available on {expectedDateLabel}
                      </p>
                    )}
                    {availabilityNote && (
                      <p className="text-xs text-[#7A6240] mt-1 leading-5">{availabilityNote}</p>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
          <button onClick={onClose} disabled={closing} className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-gray-100 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed">
            <i className="ri-close-line text-gray-500" />
          </button>
        </div>

        {submitted ? (
          <div className="p-8 text-center">
            <div className={`w-14 h-14 mx-auto flex items-center justify-center rounded-full mb-4 ${copy.successIconWrapClass}`}>
              <i className={`${copy.successIconClass} text-2xl`} />
            </div>
            <div className={`inline-flex items-center justify-center px-3 py-1 rounded-full text-[11px] font-bold tracking-[0.12em] mb-4 ${copy.successBadgeClass}`}>
              {copy.successBadge}
            </div>
            <p className="text-gray-400 text-sm mb-6">{copy.successText}</p>
            <button
              onClick={handleDone}
              disabled={closing}
              className="inline-flex min-w-28 items-center justify-center gap-2 px-6 py-2.5 bg-[#442F73] text-white text-sm font-semibold rounded-full cursor-pointer disabled:opacity-80 disabled:cursor-not-allowed"
            >
              {closing ? (
                <>
                  <i className="ri-loader-4-line animate-spin" />
                  Closing...
                </>
              ) : (
                "Done"
              )}
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="p-6 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1.5">Your Name</label>
                <input
                  required
                  type="text"
                  name="fullName"
                  autoComplete="name"
                  value={form.studentName}
                  onChange={(e) => setForm({ ...form, studentName: e.target.value })}
                  placeholder="Full name"
                  className="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1.5">Email</label>
                <input
                  required
                  type="email"
                  name="email"
                  autoComplete="email"
                  value={form.studentEmail}
                  onChange={(e) => setForm({ ...form, studentEmail: e.target.value })}
                  placeholder="Enter your email"
                  className="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1.5">Phone Number</label>
                <input
                  required
                  type="tel"
                  name="phone"
                  autoComplete="tel"
                  value={form.studentPhone}
                  onChange={(e) => setForm({ ...form, studentPhone: e.target.value })}
                  placeholder="Enter your phone number"
                  className="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800"
                />
              <p className="mt-1 text-[11px] text-gray-400">Use a UK number like 07123 456789 or +44 7123 456789.</p>
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1.5">Book Title</label>
              <input
                required
                type="text"
                value={form.bookTitle}
                onChange={(e) => setForm({ ...form, bookTitle: e.target.value })}
                placeholder="Enter the book title"
                className="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800"
              />
            </div>

            {!isGeneralRequest && (
              <>
                <div>
                  <label className="block text-xs font-semibold text-gray-600 mb-1.5">Category</label>
                  <select
                    value={form.category}
                    onChange={(e) => setForm({ ...form, category: e.target.value })}
                    className="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl outline-none focus:border-[#442F73] bg-white text-gray-800 cursor-pointer"
                  >
                    {categoryNames.map((category) => (
                      <option key={category}>{category}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-600 mb-1.5">
                    <i className="ri-calendar-line mr-1 text-[#442F73]" />
                    Needed Period (From - To)
                  </label>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <p className="text-[10px] text-gray-400 mb-1">From</p>
                      <input
                        required
                        type="date"
                        value={form.neededFrom}
                        min={minNeededFrom}
                        onChange={(e) => setForm({ ...form, neededFrom: e.target.value })}
                        className="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800 cursor-pointer"
                      />
                    </div>
                    <div>
                      <p className="text-[10px] text-gray-400 mb-1">Until</p>
                      <input
                        required
                        type="date"
                        value={form.neededUntil}
                        min={form.neededFrom || undefined}
                        onChange={(e) => setForm({ ...form, neededUntil: e.target.value })}
                        className="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800 cursor-pointer"
                      />
                    </div>
                  </div>
                  {form.neededFrom && form.neededUntil && new Date(form.neededUntil) > new Date(form.neededFrom) && (
                    <p className="text-xs text-[#442F73] mt-1.5 flex items-center gap-1">
                      <i className="ri-time-line" />
                      {Math.ceil((new Date(form.neededUntil).getTime() - new Date(form.neededFrom).getTime()) / (1000 * 60 * 60 * 24))} days
                    </p>
                  )}
                  {requestMode === "reserve" && expectedDateLabel && (
                    <p className="text-xs text-amber-700 mt-2 leading-5">
                      Reservations can only start on or after {expectedDateLabel}, when this copy is expected back.
                    </p>
                  )}
                </div>
              </>
            )}

            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1.5">Why do you need it?</label>
              <textarea
                value={form.reason}
                onChange={(e) => setForm({ ...form, reason: e.target.value.slice(0, 300) })}
                placeholder="Optional note for the library team..."
                rows={3}
                className="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800 resize-none"
              />
              <p className="text-xs text-gray-400 mt-1 text-right">{form.reason.length}/300</p>
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="w-full py-3 font-semibold text-sm rounded-xl transition-colors duration-200 bg-[#442F73] hover:bg-[#241453] text-white cursor-pointer disabled:opacity-70 disabled:cursor-not-allowed disabled:hover:bg-[#442F73]"
            >
              {submitting ? (
                <span className="inline-flex items-center justify-center gap-2">
                  <i className="ri-loader-4-line animate-spin" />
                  Sending...
                </span>
              ) : (
                copy.button
              )}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
