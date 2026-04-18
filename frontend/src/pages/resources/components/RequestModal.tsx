import { useState } from "react";
import { useAdminData } from "../../../hooks/useAdminData";

interface Props {
  onClose: () => void;
  initialBookTitle?: string;
  initialResourceId?: string;
  initialCategory?: string;
  expectedAvailableDate?: string | null;
  availabilityNote?: string;
  mode?: "request" | "borrow" | "notify";
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
  const today = new Date().toISOString().split("T")[0];
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
      subtitle: "Complete the form and a member of the library team will contact you.",
      button: "Submit Borrow Request",
      successTitle: "Borrow Request Received",
      successText: "Your request is now with the library team. A confirmation message will be sent to the email address you provided, and we will follow up once a copy is confirmed for you.",
      successSubtitle: "Check your email for a confirmation shortly.",
      successBadge: "BORROW REQUEST",
      successBadgeClass: "bg-[#E8F7EF] text-[#127A49]",
      successIconClass: "ri-book-open-line text-[#127A49]",
      successIconWrapClass: "bg-emerald-50",
    },
    notify: {
      title: "Notify Me When Available",
      subtitle: "This book is currently unavailable. Leave your details and we will send a notification to the email address you provide as soon as a copy is free.",
      button: "Register for Notification",
      successTitle: "You're on the List",
      successText: "You will receive an email notification at the address you provided as soon as this book becomes available. No further action is needed from your side.",
      successSubtitle: "Keep an eye on your inbox.",
      successBadge: "AVAILABILITY ALERT",
      successBadgeClass: "bg-[#EEF3FF] text-[#3154A3]",
      successIconClass: "ri-notification-3-line text-[#3154A3]",
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
      return "This book is not available right now. Please try again later or contact the library team.";
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
    return trimmedMessage;
  };

  const isGeneralRequest = requestMode === "request";
  const showDates = requestMode === "borrow";

  const isValidUkPhone = (value: string) => {
    const normalized = value.replace(/[\s()-]/g, "");
    return /^(?:\+44|0)7\d{9}$/.test(normalized) || /^(?:\+44|0)(?:1|2)\d{8,9}$/.test(normalized);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
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
          status: "requested",
          loanType: requestMode === "notify" ? "notify" : "borrow",
          // Only include dates for the borrow mode; notify mode is a pure availability alert.
          requestedFrom: showDates ? (form.neededFrom || undefined) : undefined,
          dueDate: showDates ? (form.neededUntil || undefined) : undefined,
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
    if (closing) return;
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
          <div className="min-w-0 flex-1">
            <h2 className="font-bold text-[#241453] text-lg" style={{ fontFamily: "'Playfair Display', serif" }}>
              {submitted ? copy.successTitle : copy.title}
            </h2>
            <p className="text-gray-400 text-xs mt-0.5">
              {submitted ? copy.successSubtitle : copy.subtitle}
            </p>

            {/* Notify mode: availability info banner */}
            {!submitted && requestMode === "notify" && (availabilityNote || expectedDateLabel) && (
              <div className="mt-3 rounded-xl border border-sky-200 bg-sky-50/60 px-3.5 py-3">
                <div className="flex items-start gap-2">
                  <i className="ri-notification-3-line text-sky-700 mt-0.5" />
                  <div className="min-w-0">
                    {expectedDateLabel && (
                      <p className="text-xs font-semibold text-sky-800">
                        Expected back on {expectedDateLabel}
                      </p>
                    )}
                    {availabilityNote && (
                      <p className="text-xs text-sky-700 mt-1 leading-5">{availabilityNote}</p>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Borrow mode: timing info banner */}
            {!submitted && requestMode === "borrow" && (availabilityNote || expectedDateLabel) && (
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
          <button
            onClick={onClose}
            disabled={closing}
            className="w-8 h-8 flex-none ml-3 flex items-center justify-center rounded-lg hover:bg-gray-100 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
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
            {/* Name + Email */}
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

            {/* Phone */}
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

            {/* Book Title */}
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1.5">Book Title</label>
              <input
                required
                type="text"
                value={form.bookTitle}
                readOnly={!!initialBookTitle}
                onChange={(e) => setForm({ ...form, bookTitle: e.target.value })}
                placeholder="Enter the book title"
                className={`w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl outline-none text-gray-800 ${
                  initialBookTitle
                    ? "bg-gray-50 text-gray-500 cursor-default"
                    : "focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10"
                }`}
              />
            </div>

            {/* Category + Dates — only for general request (category) or borrow (category + dates) */}
            {isGeneralRequest && (
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
            )}

            {showDates && (
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
                      min={today}
                      onChange={(e) => setForm({ ...form, neededFrom: e.target.value, neededUntil: "" })}
                      className="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800 cursor-pointer"
                    />
                  </div>
                  <div>
                    <p className="text-[10px] text-gray-400 mb-1">Until</p>
                    <input
                      required
                      type="date"
                      value={form.neededUntil}
                      min={form.neededFrom || today}
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
              </div>
            )}

            {/* Optional note */}
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1.5">
                {requestMode === "notify" ? "Any additional note?" : "Why do you need it?"}
              </label>
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
