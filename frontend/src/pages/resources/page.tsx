import { useState, useMemo, useEffect, useDeferredValue } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import Footer from "../../components/feature/Footer";
import { useAdminData } from "../../hooks/useAdminData";
import RequestModal from "./components/RequestModal";
import { formatResourceAvailabilityLine, getResourceQueueMetrics } from "../../lib/resourceAvailability";
import { rankResources } from "../../lib/search";

export default function ResourcesPage() {
  const { books, categories, loading } = useAdminData();
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedCategory, setSelectedCategory] = useState(searchParams.get("category") ?? "All Categories");
  const [searchQuery, setSearchQuery] = useState(searchParams.get("q") ?? "");
  const [requestOpen, setRequestOpen] = useState(false);
  const deferredSearchQuery = useDeferredValue(searchQuery);

  const categoryNames = useMemo(() => ["All Categories", ...categories.map((category) => category.name)], [categories]);
  const categoryColorMap = useMemo(
    () => Object.fromEntries(categories.map((category) => [category.name, category.color])),
    [categories],
  );
  const availableBooksCount = useMemo(
    () => books.filter((book) => getResourceQueueMetrics(book).canBorrow).length,
    [books],
  );

  useEffect(() => {
    setSelectedCategory(searchParams.get("category") ?? "All Categories");
    setSearchQuery(searchParams.get("q") ?? "");
  }, [searchParams]);

  const updateSearchParams = (nextCategory: string, nextQuery: string) => {
    const params = new URLSearchParams();

    if (nextCategory !== "All Categories") {
      params.set("category", nextCategory);
    }

    if (nextQuery.trim()) {
      params.set("q", nextQuery.trim());
    }

    setSearchParams(params, { replace: true });
  };

  const filtered = useMemo(() => {
    const categoryMatched = books.filter((b) => {
      const matchCat = selectedCategory === "All Categories" || b.category === selectedCategory;
      return matchCat;
    });

    return rankResources(categoryMatched, deferredSearchQuery);
  }, [books, selectedCategory, deferredSearchQuery]);

  return (
    <div className="min-h-screen bg-[#F9F4EC]">
      <Navbar />

      <div className="bg-[#241453] pt-28 pb-12">
        <div className="max-w-7xl mx-auto px-4 md:px-6">
          <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
            <div>
              <div className="inline-flex items-center gap-2 px-3.5 py-1.5 bg-white/10 border border-white/15 rounded-full mb-4">
                <i className="ri-book-3-line text-[#CEA869] text-xs" />
                <span className="text-white/70 text-xs font-semibold tracking-widest uppercase">KBC Digital Library</span>
              </div>
              <h1 className="text-3xl md:text-4xl font-bold text-white" style={{ fontFamily: "'Playfair Display', serif" }}>
                Library Books
              </h1>
              {loading ? (
                <div className="mt-3 h-4 w-64 rounded-full bg-white/15 animate-pulse" />
              ) : (
                <p className="text-white/50 text-sm mt-2">
                  {availableBooksCount} books are open to borrow right now out of {books.length} titles across {categories.length} categories
                </p>
              )}
            </div>

            <div className="relative w-full md:w-80">
              <i className="ri-search-line absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 text-sm" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => {
                  const nextQuery = e.target.value;
                  setSearchQuery(nextQuery);
                  updateSearchParams(selectedCategory, nextQuery);
                }}
                placeholder="Search book title, author, or close match..."
                className="w-full pl-10 pr-4 py-3 bg-white rounded-xl text-sm text-gray-800 placeholder-gray-400 outline-none focus:ring-2 focus:ring-[#CEA869]/30"
              />
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 md:px-6 py-8">
        <div className="mb-5 overflow-x-auto pb-2">
          <div className="flex gap-2 w-max md:w-auto md:flex-wrap">
            {loading
              ? Array.from({ length: 5 }).map((_, index) => (
                <div key={index} className="h-10 w-36 rounded-full bg-white border border-[#E9D9BD] animate-pulse" />
              ))
              : categoryNames.map((cat) => (
                <button
                  key={cat}
                  onClick={() => {
                    setSelectedCategory(cat);
                    updateSearchParams(cat, searchQuery);
                  }}
                  className={`flex-none px-4 py-2 rounded-full text-sm font-medium transition-all duration-200 cursor-pointer whitespace-nowrap ${
                    selectedCategory === cat
                      ? "bg-[#442F73] text-white"
                      : "bg-white text-gray-600 border border-[#E9D9BD] hover:border-[#442F73]/30 hover:text-[#442F73]"
                  }`}
                >
                  {cat}
                </button>
              ))}
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 mb-8">
          {loading ? (
            <div className="h-4 w-32 rounded-full bg-[#E9D9BD] animate-pulse" />
          ) : (
            <span className="text-sm text-gray-500">
              Showing <strong className="text-[#241453]">{filtered.length}</strong> books
            </span>
          )}
          <button
            onClick={() => setRequestOpen(true)}
            className="flex items-center gap-1.5 px-4 py-2 bg-[#442F73] text-white text-xs font-semibold rounded-full transition-all duration-200 hover:bg-[#241453] cursor-pointer whitespace-nowrap"
          >
            <i className="ri-add-line" />
            Request a New Book
          </button>
        </div>

        {loading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
            {Array.from({ length: 8 }).map((_, index) => (
              <div key={index} className="bg-white rounded-2xl border border-[#E9D9BD] p-5 animate-pulse">
                <div className="mb-4 rounded-2xl border border-[#E9D9BD] bg-[#F3E9DA] aspect-[4/3]" />
                <div className="h-5 w-4/5 rounded bg-[#E9D9BD] mb-3" />
                <div className="h-4 w-2/3 rounded bg-[#F1E3CB] mb-5" />
                <div className="pt-4 border-t border-[#E9D9BD] flex items-center justify-between">
                  <div className="flex flex-col gap-2">
                    <div className="h-3 w-24 rounded bg-[#F1E3CB]" />
                    <div className="h-5 w-20 rounded-full bg-[#E9D9BD]" />
                  </div>
                  <div className="h-3 w-12 rounded bg-[#F1E3CB]" />
                </div>
              </div>
            ))}
          </div>
        ) : filtered.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
            {filtered.map((book) => {
              const color = categoryColorMap[book.category] ?? "#442F73";
              const { queueFull } = getResourceQueueMetrics(book);
              const availabilityBadge = queueFull
                ? "bg-amber-50 text-amber-700 border border-amber-200"
                : {
                available: "bg-emerald-50 text-emerald-700 border border-emerald-200",
                borrowed: "bg-amber-50 text-amber-700 border border-amber-200",
                reserved: "bg-sky-50 text-sky-700 border border-sky-200",
                maintenance: "bg-gray-100 text-gray-600 border border-gray-200",
                lost: "bg-rose-50 text-rose-600 border border-rose-200",
              }[book.availabilityStatus ?? "lost"] ?? "bg-gray-100 text-gray-600 border border-gray-200";

              return (
                <Link
                  key={book.id}
                  to={`/resources/${book.id}`}
                  className="group bg-white rounded-2xl overflow-hidden border border-[#E9D9BD] hover:border-[#442F73]/25 hover:shadow-lg transition-all duration-300 hover:-translate-y-0.5 flex flex-col p-5"
                >
                  <div className="relative mb-4 overflow-hidden rounded-2xl border border-[#E9D9BD] bg-[#F9F4EC] aspect-[4/3]">
                    {book.coverImage ? (
                      <div className="flex h-full w-full items-center justify-center bg-white p-4">
                        <img
                          src={book.coverImage}
                          alt={`Cover of ${book.title}`}
                          className="h-full w-full object-contain transition-transform duration-300 group-hover:scale-[1.03]"
                        />
                      </div>
                    ) : (
                      <div
                        className="flex h-full w-full items-center justify-center"
                        style={{ background: `linear-gradient(145deg, ${color}18, ${color}35)` }}
                      >
                        <div
                          className="w-16 h-16 flex items-center justify-center rounded-2xl"
                          style={{ backgroundColor: `${color}20` }}
                        >
                          <i className="ri-book-2-line text-3xl" style={{ color }} />
                        </div>
                      </div>
                    )}

                    <div className="absolute inset-x-0 top-0 flex items-start justify-between gap-3 p-3">
                      <div
                        className="w-10 h-10 flex items-center justify-center rounded-xl backdrop-blur-sm"
                        style={{ backgroundColor: "rgba(249, 244, 236, 0.88)" }}
                      >
                        <i className="ri-book-2-line text-lg" style={{ color }} />
                      </div>
                      <span
                        className="inline-block px-2 py-1 text-[10px] font-semibold rounded-full backdrop-blur-sm"
                        style={{ backgroundColor: "rgba(249, 244, 236, 0.92)", color }}
                      >
                        {book.category}
                      </span>
                    </div>
                  </div>

                  <h3 className="font-bold text-[#241453] text-base leading-snug mb-2 line-clamp-3 group-hover:text-[#442F73] transition-colors duration-200">
                    {book.title}
                  </h3>
                  <p className="text-gray-500 text-sm mb-2">by {book.author}</p>
                  {book.edition && (
                    <span className="mb-4 inline-flex w-fit rounded-full border border-[#E9D9BD] bg-[#FCFAF6] px-2.5 py-1 text-[10px] font-semibold text-[#6F5B92]">
                      {book.edition}
                    </span>
                  )}

                  <div className="mt-auto pt-4 border-t border-[#E9D9BD] flex items-center justify-between">
                    <div className="flex flex-col gap-1">
                      <span className="text-xs text-gray-400">{formatResourceAvailabilityLine(book)}</span>
                      <span className={`inline-flex w-fit px-2 py-0.5 text-[10px] font-semibold rounded-full ${availabilityBadge}`}>
                        {book.availabilityLabel ?? "Unavailable"}
                      </span>
                    </div>
                    <span className="flex items-center gap-1 text-xs font-semibold text-[#442F73] group-hover:gap-2 transition-all duration-200">
                      Open <i className="ri-arrow-right-line" />
                    </span>
                  </div>
                </Link>
              );
            })}
          </div>
        ) : (
          <div className="text-center py-20">
            <div className="w-16 h-16 mx-auto flex items-center justify-center bg-[#E9D9BD] rounded-full mb-4">
              <i className="ri-search-line text-[#B27715] text-2xl" />
            </div>
            <p className="text-[#241453] font-semibold mb-1">No books found</p>
            <p className="text-gray-400 text-sm mb-4">Try a different category or search term</p>
            <button
              onClick={() => {
                setSelectedCategory("All Categories");
                setSearchQuery("");
                updateSearchParams("All Categories", "");
              }}
              className="px-5 py-2 bg-[#442F73] text-white text-sm font-semibold rounded-full cursor-pointer"
            >
              Clear Filters
            </button>
          </div>
        )}
      </div>

      {requestOpen && <RequestModal onClose={() => setRequestOpen(false)} />}

      <Footer />
    </div>
  );
}
