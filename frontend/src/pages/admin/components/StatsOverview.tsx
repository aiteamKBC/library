import { useAdminData } from "../../../hooks/useAdminData";

interface Props {
  onNavigate: (tab: string) => void;
}

export default function StatsOverview({ onNavigate }: Props) {
  const { books, loans, supportMessages, loading } = useAdminData();

  const categories = [...new Set(books.map((book) => book.category))];
  const authors = [...new Set(books.map((book) => book.author))];
  const uncategorisedCount = books.filter((book) => !book.categoryId || !book.category).length;
  const activeLoansCount = loans.filter((loan) => ["requested", "borrowed", "reserved", "overdue"].includes(loan.status)).length;
  const openSupportCount = supportMessages.filter((message) => message.status !== "resolved").length;

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
    <div className="space-y-8 max-w-6xl">
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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-2xl border border-gray-200 p-6">
          <h3 className="font-bold text-gray-900 text-sm mb-5">Books by Category</h3>
          {loading ? (
            <div className="space-y-3">
              {Array.from({ length: 4 }).map((_, index) => (
                <div key={index}>
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="h-4 w-32 rounded bg-gray-100" />
                    <div className="h-4 w-6 rounded bg-gray-100" />
                  </div>
                  <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden" />
                </div>
              ))}
            </div>
          ) : categoryBreakdown.length === 0 ? (
            <p className="text-sm text-gray-400">No books available yet.</p>
          ) : (
            <div className="space-y-3">
              {categoryBreakdown.map((category) => (
                <div key={category.name}>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-sm text-gray-700 truncate flex-1 mr-3">{category.name}</span>
                    <span className="text-xs font-bold text-gray-500 flex-none">{category.count}</span>
                  </div>
                  <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-[#442F73] rounded-full transition-all duration-500"
                      style={{ width: `${(category.count / maxCount) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="bg-white rounded-2xl border border-gray-200 p-6">
          <div className="flex items-center justify-between mb-5">
            <h3 className="font-bold text-gray-900 text-sm">Current Scope</h3>
            <button
              onClick={() => onNavigate("books")}
              className="text-xs text-[#442F73] font-semibold hover:underline cursor-pointer"
            >
              Manage books
            </button>
          </div>
          <div className="space-y-3 text-sm text-gray-600">
            <div className="p-4 bg-gray-50 rounded-xl">
              The admin overview now reads only from the real library books and their category assignments.
            </div>
            <div className="p-4 bg-gray-50 rounded-xl">
              Student requests stay empty unless they are submitted through the site or returned from the backend.
            </div>
            <div className="p-4 bg-gray-50 rounded-xl">
              Support page messages now appear in the Support Inbox for the library team to triage and resolve.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
