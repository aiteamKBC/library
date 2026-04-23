import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAdminData } from "../../../hooks/useAdminData";
import { getResourceQueueMetrics } from "../../../lib/resourceAvailability";
import { rankResources } from "../../../lib/search";

export default function HeroSection() {
  const [searchQuery, setSearchQuery] = useState("");
  const navigate = useNavigate();
  const { books, loading } = useAdminData();
  const totalBorrowableCopies = useMemo(
    () => books.reduce((sum, book) => sum + getResourceQueueMetrics(book).borrowableCopies, 0),
    [books],
  );

  const suggestions = useMemo(
    () => (searchQuery.trim() ? rankResources(books, searchQuery).slice(0, 5) : []),
    [books, searchQuery],
  );

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    navigate(`/resources${searchQuery ? `?q=${encodeURIComponent(searchQuery)}` : ""}`);
  };

  return (
    <section className="relative min-h-screen flex flex-col justify-center overflow-hidden">
      <div className="absolute inset-0">
        <img
          src="https://readdy.ai/api/search-image?query=grand%20university%20library%20interior%20with%20soaring%20ceilings%2C%20ornate%20wooden%20bookshelves%20floor%20to%20ceiling%2C%20warm%20golden%20reading%20lamps%2C%20polished%20oak%20tables%2C%20classical%20academic%20architecture%2C%20rich%20amber%20and%20mahogany%20tones%2C%20volumetric%20light%20shafts%20through%20tall%20windows%2C%20ultra%20detailed%20photograph&width=1920&height=1080&seq=hero-premium-bg-v2&orientation=landscape"
          alt="KBC Library Interior"
          className="w-full h-full object-cover object-top"
        />
        <div
          className="absolute inset-0"
          style={{
            background:
              "linear-gradient(90deg, rgba(1,2,3,0.9) 0%, rgba(5,7,10,0.82) 30%, rgba(14,10,8,0.58) 62%, rgba(18,12,9,0.32) 100%)",
          }}
        />
        <div className="absolute inset-0 bg-gradient-to-b from-black/16 via-black/12 to-black/46" />
        <div
          className="absolute inset-0"
          style={{
            background:
              "radial-gradient(circle at 86% 26%, rgba(0,0,0,0.42) 0%, rgba(0,0,0,0.16) 24%, transparent 48%)",
          }}
        />
        <div className="absolute inset-0 opacity-5" style={{ backgroundImage: "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")" }} />
      </div>

      <div className="relative z-10 max-w-7xl mx-auto px-4 md:px-6 pt-28 pb-24 w-full">
        <div className="max-w-3xl">
          <div className="inline-flex items-center gap-2.5 px-4 py-2 bg-white/8 backdrop-blur-md border border-white/15 rounded-full mb-7">
            <div className="w-5 h-5 rounded-full bg-[#CEA869] flex items-center justify-center flex-none">
              <i className="ri-building-2-line text-[10px] text-[#203042]" />
            </div>
            <span className="text-white/85 text-xs font-medium tracking-wide">Kent Business College Library</span>
          </div>

          <h1
            className="text-5xl sm:text-6xl lg:text-[68px] font-bold text-white leading-[1.08] mb-5 tracking-tight"
            style={{ fontFamily: "'Playfair Display', serif" }}
          >
            Your 
            <span className="relative inline-block">
              <span className="text-[#CEA869]">Library</span>
              <svg className="absolute -bottom-2 left-0 w-full" height="6" viewBox="0 0 240 6" fill="none" preserveAspectRatio="none">
                <path d="M0 3 Q60 0 120 3 Q180 6 240 3" stroke="#CEA869" strokeWidth="2" strokeOpacity="0.5" fill="none" />
              </svg>
            </span>
            {" "}&amp; Resource Hub
          </h1>

          <p className="mb-6 max-w-2xl text-sm leading-7 text-white/70 sm:text-base">
            {loading
              ? "Browse the current library collection and check live availability."
              : `${totalBorrowableCopies} copies are currently open to borrow across ${books.length} library titles.`}
          </p>

          <form onSubmit={handleSearch} className="mb-8 max-w-2xl">
            <div className="relative">
              <div className="flex items-center gap-0 bg-white rounded-2xl overflow-hidden p-1.5 border-2 border-white/60 focus-within:border-[#CEA869]/80 focus-within:ring-4 focus-within:ring-[#CEA869]/15 transition-all duration-200">
              <div className="w-10 h-10 flex items-center justify-center flex-none">
                <i className="ri-search-line text-gray-400 text-lg" />
              </div>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search books by title or author..."
                className="flex-1 pr-2 py-2 text-sm text-gray-800 placeholder-gray-400 outline-none bg-transparent"
              />
              <button
                type="submit"
                className="flex items-center gap-2 px-5 py-2.5 bg-[#131a22] hover:bg-[#0d1218] text-white text-sm font-semibold rounded-xl transition-colors duration-200 cursor-pointer whitespace-nowrap"
              >
                <span className="hidden sm:inline">Search</span>
                <i className="ri-arrow-right-line" />
              </button>
              </div>

              {searchQuery.trim() && !loading && suggestions.length > 0 && (
                <div className="absolute left-0 right-0 top-[calc(100%+10px)] z-20 rounded-2xl border border-white/15 bg-white shadow-2xl overflow-hidden">
                  {suggestions.map((book) => (
                    <button
                      key={book.id}
                      type="button"
                      onClick={() => navigate(`/resources/${book.id}`)}
                      className="w-full flex items-start justify-between gap-3 px-4 py-3 text-left hover:bg-[#F9F4EC] transition-colors cursor-pointer border-b border-[#F3E9DA] last:border-b-0"
                    >
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-[#203042] truncate">{book.title}</p>
                        <p className="text-xs text-gray-500 truncate">by {book.author}</p>
                      </div>
                      <span className="flex-none text-[10px] font-semibold text-[#2C3A4B] bg-[#F3E9DA] px-2 py-1 rounded-full">
                        {book.category}
                      </span>
                    </button>
                  ))}
                  <button
                    type="submit"
                    className="w-full px-4 py-3 bg-[#F9F4EC] text-[#2C3A4B] text-sm font-semibold hover:bg-[#F3E9DA] transition-colors cursor-pointer"
                  >
                    View all results for "{searchQuery.trim()}"
                  </button>
                </div>
              )}

              {searchQuery.trim() && !loading && suggestions.length === 0 && (
                <div className="absolute left-0 right-0 top-[calc(100%+10px)] z-20 rounded-2xl border border-white/15 bg-white shadow-2xl px-4 py-3">
                  <p className="text-sm text-gray-500">No close matches found yet.</p>
                </div>
              )}
            </div>
          </form>

          <div className="flex flex-wrap items-center gap-3">
            <Link
              to="/resources"
              className="flex items-center gap-2 px-7 py-3.5 bg-[#CEA869] hover:bg-[#B27715] text-[#182430] font-bold text-sm rounded-full transition-all duration-200 cursor-pointer whitespace-nowrap"
            >
              <i className="ri-book-open-line" />
              Browse Books
            </Link>
            <Link
              to="/categories"
              className="flex items-center gap-2 px-7 py-3.5 bg-white/10 hover:bg-white/18 backdrop-blur-sm text-white font-semibold text-sm rounded-full border border-white/25 hover:border-white/45 transition-all duration-200 cursor-pointer whitespace-nowrap"
            >
              <i className="ri-grid-2-line" />
              Explore Categories
            </Link>
          </div>
        </div>
      </div>

      <div className="absolute bottom-7 left-1/2 -translate-x-1/2 flex flex-col items-center gap-1.5">
        <span className="text-white/30 text-[10px] tracking-widest uppercase">Scroll</span>
        <div className="w-5 h-8 border border-white/20 rounded-full flex items-start justify-center p-1">
          <div className="w-1 h-1.5 bg-white/50 rounded-full animate-bounce" />
        </div>
      </div>
    </section>
  );
}
