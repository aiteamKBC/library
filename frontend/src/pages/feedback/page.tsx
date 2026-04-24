import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Footer from "../../components/feature/Footer";
import Navbar from "../../components/feature/Navbar";
import { api } from "../../lib/api";
import type { BookFeedback, BookFeedbackSubmissionPayload, FeedbackContext } from "../../types/library";

type FeedbackForm = {
  learnedSomething: "" | BookFeedbackSubmissionPayload["learnedSomething"];
  wouldRecommend: "" | BookFeedbackSubmissionPayload["wouldRecommend"];
  contentQuality: "" | BookFeedbackSubmissionPayload["contentQuality"];
  starRating: 0 | 1 | 2 | 3 | 4 | 5;
  comment: string;
};

const learnedOptions = [
  { value: "yes", label: "Yes", description: "It gave me useful knowledge or ideas." },
  { value: "somewhat", label: "Somewhat", description: "It helped a little, but not fully." },
  { value: "no", label: "No", description: "It did not really help me learn." },
] as const;

const recommendOptions = [
  { value: "yes", label: "Yes", description: "I would suggest it to other students." },
  { value: "maybe", label: "Maybe", description: "It may suit some students or courses." },
  { value: "no", label: "No", description: "I would not recommend it right now." },
] as const;

const qualityOptions = [
  { value: "excellent", label: "Excellent" },
  { value: "good", label: "Good" },
  { value: "fair", label: "Fair" },
  { value: "poor", label: "Poor" },
] as const;

function extractErrorMessage(message: string) {
  const trimmed = message.trim();
  if (trimmed.startsWith("{")) {
    try {
      const parsed = JSON.parse(trimmed) as Record<string, unknown>;
      const firstValue = Object.values(parsed)[0];
      if (typeof firstValue === "string") {
        return firstValue;
      }
      if (Array.isArray(firstValue) && typeof firstValue[0] === "string") {
        return firstValue[0];
      }
    } catch {
      return trimmed;
    }
  }
  return trimmed || "We could not load this feedback form right now.";
}

function formatDate(date?: string | null) {
  if (!date) return null;
  const parsed = new Date(date);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function readChoiceLabel(value?: string) {
  const labels: Record<string, string> = {
    yes: "Yes",
    somewhat: "Somewhat",
    no: "No",
    maybe: "Maybe",
    excellent: "Excellent",
    good: "Good",
    fair: "Fair",
    poor: "Poor",
  };
  return value ? labels[value] ?? value : "-";
}

function StarRating({
  value,
  onChange,
  disabled = false,
}: {
  value: number;
  onChange?: (next: 1 | 2 | 3 | 4 | 5) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {[1, 2, 3, 4, 5].map((star) => {
        const filled = star <= value;
        return (
          <button
            key={star}
            type="button"
            disabled={disabled}
            onClick={() => onChange?.(star as 1 | 2 | 3 | 4 | 5)}
            className={`flex h-11 w-11 items-center justify-center rounded-2xl border transition-all ${
              filled
                ? "border-[#CEA869] bg-[#FFF8E8] text-[#B27715]"
                : "border-gray-200 bg-white text-gray-300"
            } ${disabled ? "cursor-default" : "cursor-pointer hover:border-[#CEA869] hover:text-[#B27715]"}`}
            aria-label={`Rate ${star} star${star === 1 ? "" : "s"}`}
          >
            <i className={`${filled ? "ri-star-fill" : "ri-star-line"} text-xl`} />
          </button>
        );
      })}
      <span className="text-sm text-gray-500">{value > 0 ? `${value}/5` : "Choose a rating"}</span>
    </div>
  );
}

function FeedbackSummary({ feedback }: { feedback: BookFeedback }) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <div className="rounded-2xl border border-[#E9D9BD] bg-[#FCFAF6] p-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-400">Learned Something</p>
        <p className="mt-2 text-sm font-semibold text-[#241453]">{readChoiceLabel(feedback.learnedSomething)}</p>
      </div>
      <div className="rounded-2xl border border-[#E9D9BD] bg-[#FCFAF6] p-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-400">Would Recommend</p>
        <p className="mt-2 text-sm font-semibold text-[#241453]">{readChoiceLabel(feedback.wouldRecommend)}</p>
      </div>
      <div className="rounded-2xl border border-[#E9D9BD] bg-[#FCFAF6] p-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-400">Content Quality</p>
        <p className="mt-2 text-sm font-semibold text-[#241453]">{readChoiceLabel(feedback.contentQuality)}</p>
      </div>
      <div className="rounded-2xl border border-[#E9D9BD] bg-[#FCFAF6] p-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-400">Overall Rating</p>
        <div className="mt-2">
          <StarRating value={feedback.starRating} disabled />
        </div>
      </div>
      {feedback.comment && (
        <div className="rounded-2xl border border-[#E9D9BD] bg-[#FCFAF6] p-4 md:col-span-2">
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-400">Optional Comment</p>
          <p className="mt-2 text-sm leading-6 text-gray-700">{feedback.comment}</p>
        </div>
      )}
    </div>
  );
}

export default function FeedbackPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [context, setContext] = useState<FeedbackContext | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submittedFeedback, setSubmittedFeedback] = useState<BookFeedback | null>(null);
  const [form, setForm] = useState<FeedbackForm>({
    learnedSomething: "",
    wouldRecommend: "",
    contentQuality: "",
    starRating: 0,
    comment: "",
  });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      if (!token) {
        setError("This feedback link is incomplete. Please use the link from your library email.");
        setLoading(false);
        return;
      }

      setLoading(true);
      setError("");
      try {
        const nextContext = await api.getFeedbackContext(token);
        if (cancelled) return;
        setContext(nextContext);
        if (nextContext.feedback) {
          setSubmittedFeedback(nextContext.feedback);
        }
      } catch (loadError) {
        if (cancelled) return;
        const rawMessage = loadError instanceof Error ? loadError.message : "We could not load this feedback form right now.";
        setError(extractErrorMessage(rawMessage));
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [token]);

  const returnDateLabel = useMemo(() => formatDate(context?.returnedAt), [context?.returnedAt]);
  const activeFeedback = submittedFeedback ?? context?.feedback ?? null;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (submitting) return;
    if (!form.learnedSomething || !form.wouldRecommend || !form.contentQuality || form.starRating < 1) {
      setError("Please answer all required questions before sending your feedback.");
      return;
    }

    setSubmitting(true);
    setError("");
    try {
      const created = await api.submitFeedback({
        token,
        learnedSomething: form.learnedSomething,
        wouldRecommend: form.wouldRecommend,
        contentQuality: form.contentQuality,
        starRating: form.starRating,
        comment: form.comment.trim() || undefined,
      });
      setSubmittedFeedback(created);
      setContext((previous) => previous ? { ...previous, alreadySubmitted: true, feedback: created } : previous);
    } catch (submitError) {
      const rawMessage = submitError instanceof Error ? submitError.message : "We could not save your feedback right now.";
      setError(extractErrorMessage(rawMessage));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#F9F4EC]">
      <Navbar />

      <section className="relative overflow-hidden bg-[#241453] pb-16 pt-24 md:pb-20 md:pt-28">
        <div className="absolute inset-0 opacity-15">
          <div className="absolute left-8 top-10 h-72 w-72 rounded-full bg-white/20 blur-3xl" />
          <div className="absolute bottom-0 right-16 h-80 w-80 rounded-full bg-[#CEA869]/20 blur-3xl" />
        </div>
        <div className="relative z-10 mx-auto max-w-3xl px-4 md:px-6 text-center">
          <span className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-white/80">
            <i className="ri-chat-smile-2-line text-[#CEA869]" />
            KBC Library Feedback
          </span>
          <h1
            className="mt-4 text-[1.6rem] font-bold leading-[1.2] text-white md:text-[2.35rem] md:leading-[1.1]"
            style={{ fontFamily: "'Playfair Display', serif" }}
          >
            Tell Us How This Book Helped You
          </h1>
          <p className="mx-auto mt-4 max-w-xl text-sm leading-7 text-white/70 md:text-[15px]">
            A short response helps the library team understand which books support students best and what to improve next.
          </p>
        </div>
      </section>

      <section className="pb-16 pt-8 md:pb-20 md:pt-10">
        <div className="mx-auto max-w-3xl px-4 md:px-6">
          <div className="rounded-[30px] border border-[#E9D9BD] bg-white p-6 shadow-[0_16px_40px_rgba(36,20,83,0.08)] md:p-8">
            {loading ? (
              <div className="space-y-5 animate-pulse">
                <div className="h-6 w-52 rounded bg-[#E9D9BD]" />
                <div className="h-4 w-72 rounded bg-[#F1E3CB]" />
                <div className="grid gap-4 md:grid-cols-2">
                  {Array.from({ length: 4 }).map((_, index) => (
                    <div key={index} className="rounded-2xl border border-[#F1E3CB] bg-[#FCFAF6] p-4">
                      <div className="h-3 w-32 rounded bg-[#E9D9BD]" />
                      <div className="mt-3 h-10 rounded-xl bg-[#F1E3CB]" />
                    </div>
                  ))}
                </div>
              </div>
            ) : error ? (
              <div className="rounded-3xl border border-rose-200 bg-rose-50 p-6 text-center">
                <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-white text-rose-500">
                  <i className="ri-error-warning-line text-2xl" />
                </div>
                <h2 className="text-xl font-bold text-[#241453]" style={{ fontFamily: "'Playfair Display', serif" }}>
                  Feedback Link Unavailable
                </h2>
                <p className="mx-auto mt-3 max-w-xl text-sm leading-7 text-rose-700">{error}</p>
                <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
                  <Link
                    to="/resources"
                    className="inline-flex items-center justify-center rounded-full bg-[#442F73] px-5 py-3 text-sm font-semibold text-white transition-colors hover:bg-[#241453]"
                  >
                    Browse Books
                  </Link>
                  <Link
                    to="/support"
                    className="inline-flex items-center justify-center rounded-full border border-[#E9D9BD] bg-white px-5 py-3 text-sm font-semibold text-[#442F73] transition-colors hover:border-[#442F73]/30 hover:text-[#241453]"
                  >
                    Contact Support
                  </Link>
                </div>
              </div>
            ) : activeFeedback ? (
              <div className="space-y-6">
                <div className="rounded-3xl border border-emerald-200 bg-[#F2FBF6] p-6 md:p-7">
                  <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                    <div>
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-emerald-700">Feedback Received</p>
                      <h2 className="mt-2 text-[1.7rem] font-bold leading-[1.15] text-[#241453] md:text-[2rem]" style={{ fontFamily: "'Playfair Display', serif" }}>
                        Thank you for sharing your feedback
                      </h2>
                      <p className="mt-2 text-sm leading-7 text-gray-600">
                        Your response for <span className="font-semibold text-[#241453]">{context?.bookTitle}</span> has been saved successfully.
                      </p>
                    </div>
                    <div className="rounded-2xl border border-emerald-200 bg-white px-5 py-4 text-center shadow-sm">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-400">Overall Rating</p>
                      <p className="mt-2 text-3xl font-bold text-[#241453]">{activeFeedback.starRating}/5</p>
                    </div>
                  </div>
                </div>

                <div>
                  <h3 className="text-lg font-bold text-[#241453]" style={{ fontFamily: "'Playfair Display', serif" }}>
                    Your Response
                  </h3>
                  <p className="mt-1 text-sm text-gray-500">
                    {context?.alreadySubmitted ? "This feedback has already been recorded for this returned book." : "Your answers are now stored in the library system."}
                  </p>
                </div>

                <FeedbackSummary feedback={activeFeedback} />

                <div className="flex flex-wrap items-center gap-3">
                  {context?.resourceId && (
                    <Link
                      to={`/resources/${context.resourceId}`}
                      className="inline-flex items-center justify-center rounded-full bg-[#442F73] px-5 py-3 text-sm font-semibold text-white transition-colors hover:bg-[#241453]"
                    >
                      Back to This Book
                    </Link>
                  )}
                  <Link
                    to="/resources"
                    className="inline-flex items-center justify-center rounded-full border border-[#E9D9BD] bg-white px-5 py-3 text-sm font-semibold text-[#442F73] transition-colors hover:border-[#442F73]/30 hover:text-[#241453]"
                  >
                    Browse More Books
                  </Link>
                </div>
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-6">
                <div className="flex flex-col gap-5 rounded-3xl border border-[#E9D9BD] bg-[#FCFAF6] p-5 md:flex-row md:items-start md:justify-between md:p-6">
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#9B8AB8]">Returned Book Feedback</p>
                    <h2
                      className="mt-2 text-[1.7rem] font-bold leading-[1.15] text-[#241453] md:text-[2rem]"
                      style={{ fontFamily: "'Playfair Display', serif" }}
                    >
                      {context?.bookTitle}
                    </h2>
                    <p className="mt-2 text-sm leading-7 text-gray-600">
                      {context?.borrowerName ? `Hi ${context.borrowerName}, ` : ""}
                      this should only take a few seconds.
                    </p>
                  </div>
                  <div className="rounded-2xl border border-[#E9D9BD] bg-white px-4 py-3 shadow-sm">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-400">Returned On</p>
                    <p className="mt-1 text-sm font-semibold text-[#241453]">{returnDateLabel ?? "Recently returned"}</p>
                  </div>
                </div>

                {error && (
                  <div className="rounded-2xl border border-amber-200 bg-[#FFF9F0] px-4 py-3 text-sm text-[#7A6240]">
                    {error}
                  </div>
                )}

                <div className="space-y-3">
                  <div>
                    <p className="text-sm font-semibold text-[#241453]">Did you learn something valuable from this book?</p>
                    <p className="mt-1 text-xs text-gray-500">Choose the answer that best reflects your experience.</p>
                  </div>
                  <div className="grid gap-3 md:grid-cols-3">
                    {learnedOptions.map((option) => {
                      const selected = form.learnedSomething === option.value;
                      return (
                        <button
                          key={option.value}
                          type="button"
                          onClick={() => setForm((previous) => ({ ...previous, learnedSomething: option.value }))}
                          className={`rounded-2xl border p-4 text-left transition-all ${
                            selected
                              ? "border-[#442F73] bg-[#F7F2FF] shadow-sm"
                              : "border-gray-200 bg-white hover:border-[#442F73]/20 hover:bg-[#FCFAFF]"
                          }`}
                        >
                          <p className="text-sm font-semibold text-[#241453]">{option.label}</p>
                          <p className="mt-2 text-xs leading-5 text-gray-500">{option.description}</p>
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="space-y-3">
                  <div>
                    <p className="text-sm font-semibold text-[#241453]">Would you recommend this book to other students?</p>
                    <p className="mt-1 text-xs text-gray-500">This helps us understand which titles are worth promoting.</p>
                  </div>
                  <div className="grid gap-3 md:grid-cols-3">
                    {recommendOptions.map((option) => {
                      const selected = form.wouldRecommend === option.value;
                      return (
                        <button
                          key={option.value}
                          type="button"
                          onClick={() => setForm((previous) => ({ ...previous, wouldRecommend: option.value }))}
                          className={`rounded-2xl border p-4 text-left transition-all ${
                            selected
                              ? "border-[#442F73] bg-[#F7F2FF] shadow-sm"
                              : "border-gray-200 bg-white hover:border-[#442F73]/20 hover:bg-[#FCFAFF]"
                          }`}
                        >
                          <p className="text-sm font-semibold text-[#241453]">{option.label}</p>
                          <p className="mt-2 text-xs leading-5 text-gray-500">{option.description}</p>
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="space-y-3">
                  <div>
                    <p className="text-sm font-semibold text-[#241453]">How would you rate the content quality?</p>
                    <p className="mt-1 text-xs text-gray-500">Think about clarity, usefulness, and overall quality.</p>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    {qualityOptions.map((option) => {
                      const selected = form.contentQuality === option.value;
                      return (
                        <button
                          key={option.value}
                          type="button"
                          onClick={() => setForm((previous) => ({ ...previous, contentQuality: option.value }))}
                          className={`rounded-2xl border px-4 py-4 text-sm font-semibold transition-all ${
                            selected
                              ? "border-[#442F73] bg-[#F7F2FF] text-[#241453] shadow-sm"
                              : "border-gray-200 bg-white text-gray-600 hover:border-[#442F73]/20 hover:text-[#241453]"
                          }`}
                        >
                          {option.label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="space-y-3">
                  <div>
                    <p className="text-sm font-semibold text-[#241453]">Overall, how would you rate this book?</p>
                    <p className="mt-1 text-xs text-gray-500">Give it a quick star rating from 1 to 5.</p>
                  </div>
                  <StarRating
                    value={form.starRating}
                    onChange={(next) => setForm((previous) => ({ ...previous, starRating: next }))}
                  />
                </div>

                <div>
                  <label className="block text-sm font-semibold text-[#241453]">Optional comment</label>
                  <textarea
                    value={form.comment}
                    onChange={(event) => setForm((previous) => ({ ...previous, comment: event.target.value.slice(0, 500) }))}
                    rows={4}
                    placeholder="Anything else you want the library team to know?"
                    className="mt-2 w-full rounded-2xl border border-gray-200 px-4 py-3 text-sm text-gray-800 outline-none transition-colors focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 resize-none"
                  />
                  <p className="mt-1 text-right text-xs text-gray-400">{form.comment.length}/500</p>
                </div>

                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-xs leading-5 text-gray-500">
                    Your answers will be used by the library team to improve future borrowing recommendations and collection planning.
                  </p>
                  <button
                    type="submit"
                    disabled={submitting}
                    className="inline-flex items-center justify-center gap-2 rounded-full bg-[#442F73] px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-[#241453] disabled:cursor-not-allowed disabled:opacity-70"
                  >
                    {submitting ? (
                      <>
                        <i className="ri-loader-4-line animate-spin" />
                        Sending...
                      </>
                    ) : (
                      "Submit Feedback"
                    )}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      </section>

      <Footer />
    </div>
  );
}
