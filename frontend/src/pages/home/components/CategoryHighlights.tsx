import { Link } from "react-router-dom";
import { useAdminData } from "../../../hooks/useAdminData";

export default function CategoryHighlights() {
  const { books, categories, loading } = useAdminData();

  const categoryCards = categories.slice(0, 4).map((category) => ({
    ...category,
    count: books.filter((book) => book.categoryId === category.slug).length,
  }));
  const skeletonItems = Array.from({ length: 4 }, (_, index) => index);

  return (
    <section className="py-20 bg-[#F9F4EC]">
      <div className="max-w-7xl mx-auto px-4 md:px-6">
        <div className="flex flex-col sm:flex-row items-start sm:items-end justify-between gap-5 mb-10">
          <div>
            <div className="inline-flex items-center gap-2 px-3.5 py-1.5 bg-[#2C3A4B]/10 border border-[#2C3A4B]/15 rounded-full mb-4">
              <i className="ri-layout-grid-fill text-[#2C3A4B] text-xs" />
              <span className="text-[#2C3A4B] text-xs font-semibold tracking-widest uppercase">Browse by Category</span>
            </div>
            <h2
              className="text-3xl md:text-4xl font-bold text-[#203042] leading-tight"
              style={{ fontFamily: "'Playfair Display', serif" }}
            >
              Explore the Library
            </h2>
          </div>

          <Link
            to="/categories"
            className="flex-none flex items-center gap-2 px-5 py-2.5 border border-[#2C3A4B]/25 text-[#2C3A4B] hover:bg-[#2C3A4B] hover:text-white text-sm font-semibold rounded-full transition-all duration-200 cursor-pointer whitespace-nowrap"
          >
            All Categories
            <i className="ri-arrow-right-line" />
          </Link>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
          {loading
            ? skeletonItems.map((index) => (
              <div key={index} className="bg-white rounded-2xl border border-[#E9D9BD] p-5 animate-pulse">
                <div className="flex items-center justify-between mb-4">
                  <div className="w-12 h-12 rounded-xl bg-[#F3E9DA]" />
                  <div className="h-6 w-10 rounded-full bg-[#F3E9DA]" />
                </div>
                <div className="h-5 w-3/4 rounded bg-[#E9D9BD]" />
                <div className="flex items-center justify-between pt-4 mt-4 border-t border-[#E9D9BD]">
                  <div className="h-3 w-16 rounded bg-[#F1E3CB]" />
                  <div className="h-3 w-12 rounded bg-[#F1E3CB]" />
                </div>
              </div>
            ))
            : categoryCards.map((cat) => (
            <Link
              key={cat.id}
              to={`/resources?category=${encodeURIComponent(cat.name)}`}
              className="group bg-white rounded-2xl border border-[#E9D9BD] hover:border-[#2C3A4B]/20 hover:shadow-lg transition-all duration-300 cursor-pointer block p-5"
            >
              <div className="flex items-center justify-between mb-4">
                <div
                  className="w-12 h-12 flex-none flex items-center justify-center rounded-xl"
                  style={{ backgroundColor: `${cat.color}18` }}
                >
                  <i className={`${cat.icon} text-xl`} style={{ color: cat.color }} />
                </div>
                <span
                  className="text-xs font-bold px-2.5 py-1 rounded-full"
                  style={{ backgroundColor: `${cat.color}12`, color: cat.color }}
                >
                  {cat.count}
                </span>
              </div>

              <h3 className="font-bold text-[#203042] text-base leading-tight group-hover:text-[#2C3A4B] transition-colors duration-200">
                {cat.name}
              </h3>

              <div className="flex items-center justify-between pt-4 mt-4 border-t border-[#E9D9BD]">
                <span className="text-xs text-gray-400">{cat.count} books</span>
                <span
                  className="flex items-center gap-1 text-xs font-semibold group-hover:gap-2 transition-all duration-200"
                  style={{ color: cat.color }}
                >
                  Open <i className="ri-arrow-right-line" />
                </span>
              </div>
            </Link>
            ))}
        </div>
      </div>
    </section>
  );
}
