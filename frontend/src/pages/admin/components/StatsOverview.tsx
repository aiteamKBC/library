import { useAdminData } from "../../../hooks/useAdminData";

interface Props {
  onNavigate: (tab: string) => void;
}

export default function StatsOverview({ onNavigate }: Props) {
  const { books, loans, supportMessages, loading } = useAdminData();

  const categories = [...new Set(books.map((book) => book.category))];
  const activeLoansCount = loans.filter((loan) => ["requested", "borrowed", "reserved", "overdue"].includes(loan.status)).length;
  const openSupportCount = supportMessages.filter((message) => message.status !== "resolved").length;
  const feedbackResponses = books.reduce((sum, book) => sum + (book.feedbackCount ?? 0), 0);
  const totalRatingScore = books.reduce(
    (sum, book) => sum + ((book.feedbackAverageRating ?? 0) * (book.feedbackCount ?? 0)),
    0,
  );
  const recommendResponses = books.reduce((sum, book) => sum + (book.feedbackRecommendCount ?? 0), 0);
  const learnedResponses = books.reduce((sum, book) => sum + (book.feedbackLearnedCount ?? 0), 0);
  const averageFeedbackRating = feedbackResponses > 0 ? totalRatingScore / feedbackResponses : null;
  const recommendRate = feedbackResponses > 0 ? Math.round((recommendResponses / feedbackResponses) * 100) : 0;
  const learnedRate = feedbackResponses > 0 ? Math.round((learnedResponses / feedbackResponses) * 100) : 0;

  const statCards = [
    { label: "Total Books", value: books.length, icon: "ri-book-3-line", color: "#442F73", bg: "#442F73" },
    { label: "Categories", value: categories.length, icon: "ri-layout-grid-line", color: "#B27715", bg: "#B27715" },
    { label: "Active Loans", value: activeLoansCount, icon: "ri-bookmark-3-line", color: "#9D2B2B", bg: "#9D2B2B" },
    { label: "Open Support", value: openSupportCount, icon: "ri-mail-unread-line", color: "#2D6A4F", bg: "#2D6A4F" },
  ];

  const categoryBreakdown = categories
    .map((category) => ({
      name: category,
      count: books.filter((book) => book.category === category).length,
    }))
    .sort((a, b) => b.count - a.count);

  const maxCount = categoryBreakdown[0]?.count ?? 1;

  return (
    <div className="w-full space-y-8">
      <div>
        <h2 className="text-xl font-bold text-gray-900 mb-1" style={{ fontFamily: "'Playfair Display', serif" }}>
          Library Overview
        </h2>
        <p className="text-gray-400 text-sm">Summary based on the current real book list.</p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {(loading ? Array.from({ length: 4 }).map((_, index) => ({ label: index })) : statCards).map((stat) => (
          loading ? (
            <div key={stat.label} className="bg-white rounded-2xl p-5 border border-gray-200 animate-pulse">
              <div className="w-10 h-10 rounded-xl mb-4 bg-gray-100" />
              <div className="h-7 w-14 rounded bg-gray-100 mb-2" />
              <div className="h-4 w-24 rounded bg-gray-100" />
            </div>
          ) : (
          <button
            key={stat.label}
            onClick={() => onNavigate(stat.label === "Active Loans" ? "loans" : stat.label === "Open Support" ? "support" : "books")}
            className="bg-white rounded-2xl p-5 border border-gray-200 hover:border-gray-300 hover:shadow-sm transition-all duration-200 cursor-pointer text-left group"
          >
            <div
              className="w-10 h-10 flex items-center justify-center rounded-xl mb-4"
              style={{ backgroundColor: `${stat.bg}12` }}
            >
              <i className={`${stat.icon} text-lg`} style={{ color: stat.color }} />
            </div>
            <p className="text-2xl font-bold text-gray-900 mb-0.5">{stat.value}</p>
            <p className="text-gray-400 text-xs">{stat.label}</p>
          </button>
          )
        ))}
      </div>

      <div className="bg-white rounded-2xl border border-gray-200 p-6">
        <div className="mb-5 flex items-center justify-between gap-3">
          <div>
            <h3 className="font-bold text-gray-900 text-sm">Reader Feedback Snapshot</h3>
            <p className="mt-1 text-xs text-gray-500">Signals collected after books are returned.</p>
          </div>
          <button
            onClick={() => onNavigate("history")}
            className="text-xs text-[#442F73] font-semibold hover:underline cursor-pointer"
          >
            View history
          </button>
        </div>

        {loading ? (
          <div className="grid gap-4 md:grid-cols-4">
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="rounded-2xl border border-gray-100 bg-[#FCFAF6] p-4 animate-pulse">
                <div className="h-3 w-24 rounded bg-gray-100" />
                <div className="mt-3 h-8 w-16 rounded bg-gray-100" />
                <div className="mt-2 h-3 w-20 rounded bg-gray-100" />
              </div>
            ))}
          </div>
        ) : feedbackResponses > 0 ? (
          <div className="grid gap-4 md:grid-cols-4">
            <div className="rounded-2xl border border-[#E9D9BD] bg-[#FCFAF6] p-4">
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-400">Responses</p>
              <p className="mt-3 text-3xl font-bold text-[#241453]">{feedbackResponses}</p>
              <p className="mt-2 text-xs text-gray-500">Completed book feedback forms.</p>
            </div>
            <div className="rounded-2xl border border-[#E9D9BD] bg-[#FCFAF6] p-4">
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-400">Average Rating</p>
              <p className="mt-3 text-3xl font-bold text-[#241453]">{averageFeedbackRating?.toFixed(1) ?? "-"}</p>
              <p className="mt-2 text-xs text-gray-500">Weighted across all returned-book feedback.</p>
            </div>
            <div className="rounded-2xl border border-[#E9D9BD] bg-[#FCFAF6] p-4">
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-400">Would Recommend</p>
              <p className="mt-3 text-3xl font-bold text-[#241453]">{recommendRate}%</p>
              <p className="mt-2 text-xs text-gray-500">Students who would recommend the book.</p>
            </div>
            <div className="rounded-2xl border border-[#E9D9BD] bg-[#FCFAF6] p-4">
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-400">Learned Something</p>
              <p className="mt-3 text-3xl font-bold text-[#241453]">{learnedRate}%</p>
              <p className="mt-2 text-xs text-gray-500">Said the book helped them learn something valuable.</p>
            </div>
          </div>
        ) : (
          <div className="rounded-2xl border border-dashed border-[#E9D9BD] bg-[#F9F4EC] px-4 py-5">
            <p className="text-sm font-semibold text-[#241453]">No reader feedback yet</p>
            <p className="mt-1 text-xs leading-5 text-gray-500">
              Feedback metrics will appear here after returned-book emails start sending students to the new feedback form.
            </p>
          </div>
        )}
      </div>

      <div className="bg-white rounded-2xl border border-gray-200 p-6">
        <div className="mb-5 flex items-center justify-between gap-3">
          <h3 className="font-bold text-gray-900 text-sm">Books by Category</h3>
          <button
            onClick={() => onNavigate("books")}
            className="text-xs text-[#442F73] font-semibold hover:underline cursor-pointer"
          >
            Manage books
          </button>
        </div>
        {loading ? (
          <div className="space-y-3">
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index}>
                <div className="mb-1.5 flex items-center justify-between">
                  <div className="h-4 w-32 rounded bg-gray-100" />
                  <div className="h-4 w-6 rounded bg-gray-100" />
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-gray-100" />
              </div>
            ))}
          </div>
        ) : categoryBreakdown.length === 0 ? (
          <p className="text-sm text-gray-400">No books available yet.</p>
        ) : (
          <div className="space-y-3">
            {categoryBreakdown.map((category) => (
              <div key={category.name}>
                <div className="mb-1.5 flex items-center justify-between">
                  <span className="mr-3 flex-1 truncate text-sm text-gray-700">{category.name}</span>
                  <span className="flex-none text-xs font-bold text-gray-500">{category.count}</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-gray-100">
                  <div
                    className="h-full rounded-full bg-[#442F73] transition-all duration-500"
                    style={{ width: `${(category.count / maxCount) * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
