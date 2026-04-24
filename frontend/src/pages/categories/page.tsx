import { Link } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import Footer from "../../components/feature/Footer";
import { useAdminData } from "../../hooks/useAdminData";
import { getResourceQueueMetrics } from "../../lib/resourceAvailability";

export default function CategoriesPage() {
  const { books, categories, loading } = useAdminData();

  const categoryCards = categories.map((category) => ({
    ...category,
    count: books.filter((book) => book.categoryId === category.slug).length,
    borrowableCopies: books
      .filter((book) => book.categoryId === category.slug)
      .reduce((sum, book) => sum + getResourceQueueMetrics(book).borrowableCopies, 0),
  }));
  const categorySkeletons = Array.from({ length: 5 }, (_, index) => index);
  const totalResources = books.length;
  const totalBorrowableCopies = books.reduce((sum, book) => sum + getResourceQueueMetrics(book).borrowableCopies, 0);

  return (
    <div className="min-h-screen bg-white">
      <Navbar />

      <section className="relative overflow-hidden bg-[#241453] pt-32 pb-16">
        <div className="absolute inset-0 opacity-10">
          <div className="absolute top-10 right-20 w-80 h-80 rounded-full bg-white/20 blur-3xl" />
          <div className="absolute bottom-0 left-10 w-60 h-60 rounded-full bg-[#CEA869]/20 blur-3xl" />
        </div>
        <div className="relative z-10 max-w-7xl mx-auto px-4 md:px-6">
          <div className="flex flex-col md:flex-row items-start md:items-end justify-between gap-6">
            <div>
              <nav className="flex items-center gap-2 text-white/50 text-sm mb-4">
                <Link to="/" className="hover:text-white transition-colors duration-200 cursor-pointer">Home</Link>
                <i className="ri-arrow-right-s-line" />
                <span className="text-white/80">Categories</span>
              </nav>
              <h1
                className="text-3xl md:text-4xl font-bold text-white mb-3"
                style={{ fontFamily: "'Playfair Display', serif" }}
              >
                Resource Categories
              </h1>
              <p className="text-white/70 text-base max-w-lg leading-relaxed">
                Browse the current library books organised by category.
              </p>
            </div>
            <div className="flex items-center gap-6 flex-wrap">
              <div className="text-center">
                {loading ? <div className="h-8 w-10 rounded bg-white/15 animate-pulse mx-auto mb-1" /> : <p className="text-3xl font-bold text-white">{categories.length}</p>}
                <p className="text-white/50 text-xs">Subject Areas</p>
              </div>
              <div className="w-px h-10 bg-white/20" />
              <div className="text-center">
                {loading ? <div className="h-8 w-10 rounded bg-white/15 animate-pulse mx-auto mb-1" /> : <p className="text-3xl font-bold text-white">{totalResources}</p>}
                <p className="text-white/50 text-xs">Total Books</p>
              </div>
              <div className="w-px h-10 bg-white/20" />
              <div className="text-center">
                {loading ? <div className="h-8 w-12 rounded bg-white/15 animate-pulse mx-auto mb-1" /> : <p className="text-3xl font-bold text-white">{totalBorrowableCopies}</p>}
                <p className="text-white/50 text-xs">Open to Borrow</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="py-16 bg-[#F9F4EC]">
        <div className="max-w-7xl mx-auto px-4 md:px-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {loading
              ? categorySkeletons.map((index) => (
                <div key={index} className="bg-white rounded-2xl overflow-hidden border border-[#E9D9BD] p-6 animate-pulse">
                  <div className="h-2 w-full bg-[#E9D9BD] rounded-full mb-6" />
                  <div className="flex items-start justify-between mb-4">
                    <div className="w-12 h-12 rounded-xl bg-[#F3E9DA]" />
                    <div className="h-6 w-10 rounded-full bg-[#F3E9DA]" />
                  </div>
                  <div className="h-5 w-3/4 rounded bg-[#E9D9BD] mb-5" />
                  <div className="flex items-center justify-between pt-4 border-t border-[#E9D9BD]">
                    <div className="h-3 w-20 rounded bg-[#F1E3CB]" />
                    <div className="h-3 w-12 rounded bg-[#F1E3CB]" />
                  </div>
                </div>
              ))
              : categoryCards.map((cat) => (
                <Link
                  key={cat.id}
                  to={`/resources?category=${encodeURIComponent(cat.name)}`}
                  className="group bg-white rounded-2xl overflow-hidden border border-[#E9D9BD] hover:border-transparent hover:shadow-lg transition-all duration-300 hover:-translate-y-1 cursor-pointer block"
                >
                  <div
                    className="h-2 w-full transition-all duration-300 group-hover:h-3"
                    style={{ backgroundColor: cat.color }}
                  />

                  <div className="p-6">
                    <div className="flex items-start justify-between mb-4">
                      <div
                        className="w-12 h-12 flex items-center justify-center rounded-xl"
                        style={{ backgroundColor: `${cat.color}15` }}
                      >
                        <i className={`${cat.icon} text-2xl`} style={{ color: cat.color }} />
                      </div>
                      <span
                        className="text-xs font-bold px-2.5 py-1 rounded-full"
                        style={{ backgroundColor: `${cat.color}12`, color: cat.color }}
                      >
                        {cat.count}
                      </span>
                    </div>

                    <h3 className="font-semibold text-[#241453] text-base mb-5 group-hover:text-[#442F73] transition-colors duration-200">
                      {cat.name}
                    </h3>

                    <div className="flex items-center justify-between pt-4 border-t border-[#E9D9BD]">
                      <span className="text-xs text-gray-400">{cat.count} books | {cat.borrowableCopies} open to borrow</span>
                      <span
                        className="flex items-center gap-1 text-xs font-semibold group-hover:gap-2 transition-all duration-200"
                        style={{ color: cat.color }}
                      >
                        Browse <i className="ri-arrow-right-line" />
                      </span>
                    </div>
                  </div>
                </Link>
              ))}
          </div>
        </div>
      </section>

      <section className="py-16 bg-white">
        <div className="max-w-7xl mx-auto px-4 md:px-6">
          <div className="bg-gradient-to-r from-[#241453] to-[#644D93] rounded-3xl p-8 md:p-10 flex flex-col md:flex-row items-center justify-between gap-6">
            <div>
              <h3 className="text-2xl font-bold text-white mb-2" style={{ fontFamily: "'Playfair Display', serif" }}>
                Can&apos;t find what you&apos;re looking for?
              </h3>
              <p className="text-white/70 text-sm max-w-md">
                Our librarians are here to help if you need a book or want support.
              </p>
            </div>
            <div className="flex flex-col sm:flex-row gap-3">
              <Link
                to="/resources"
                className="flex items-center gap-2 px-5 py-2.5 bg-[#CEA869] hover:bg-[#B27715] text-[#241453] font-bold text-sm rounded-full transition-all duration-200 cursor-pointer whitespace-nowrap"
              >
                <i className="ri-book-open-line" />
                Browse All Books
              </Link>
              <Link
                to="/support#contact"
                className="flex items-center gap-2 px-5 py-2.5 bg-white/10 hover:bg-white/20 text-white font-semibold text-sm rounded-full border border-white/20 transition-all duration-200 cursor-pointer whitespace-nowrap"
              >
                <i className="ri-mail-line" />
                Contact a Librarian
              </Link>
            </div>
          </div>
        </div>
      </section>

      <Footer />
    </div>
  );
}
