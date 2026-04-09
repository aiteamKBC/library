import { Link } from "react-router-dom";
import { useAdminData } from "../../../hooks/useAdminData";

export default function PopularResources() {
  const { books, categories, loading } = useAdminData();
  const popularResources = books.slice(0, 4);
  const categoryColorMap = Object.fromEntries(categories.map((category) => [category.name, category.color]));

  return (
    <section className="py-20 bg-[#241453]">
      <div className="max-w-7xl mx-auto px-4 md:px-6">
        <div className="flex flex-col sm:flex-row items-start sm:items-end justify-between gap-5 mb-10">
          <div>
            <div className="inline-flex items-center gap-2 px-3.5 py-1.5 bg-white/8 border border-white/12 rounded-full mb-4">
              <i className="ri-book-open-line text-[#CEA869] text-xs" />
              <span className="text-white/70 text-xs font-semibold tracking-widest uppercase">Library Selection</span>
            </div>
            <h2 className="text-3xl md:text-4xl font-bold text-white leading-tight" style={{ fontFamily: "'Playfair Display', serif" }}>
              Browse Books by
              <span className="text-[#CEA869]"> Title</span>
            </h2>
            <p className="text-white/40 text-sm mt-2 max-w-md">
              Real books from your current library list, grouped into clear categories.
            </p>
          </div>

          <Link
            to="/resources"
            className="flex-none flex items-center gap-2 px-5 py-2.5 border border-white/15 text-white/70 hover:text-white hover:border-white/35 text-sm font-semibold rounded-full transition-all duration-200 cursor-pointer whitespace-nowrap"
          >
            All Books
            <i className="ri-arrow-right-line" />
          </Link>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {(loading ? Array.from({ length: 4 }).map((_, index) => ({ id: index })) : popularResources).map((resource, i) => {
            if (loading) {
              return (
                <div key={resource.id} className="bg-white/6 border border-white/10 rounded-2xl p-5 animate-pulse">
                  <div className="flex items-start gap-4">
                    <div className="w-12 h-12 rounded-xl bg-white/10 flex-none" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-3 mb-2">
                        <div className="h-5 w-24 rounded-full bg-white/10" />
                        <div className="h-4 w-8 rounded bg-white/10" />
                      </div>
                      <div className="h-5 w-3/4 rounded bg-white/10 mb-2" />
                      <div className="h-4 w-1/2 rounded bg-white/10" />
                    </div>
                  </div>
                </div>
              );
            }
            const color = categoryColorMap[resource.category] ?? "#CEA869";

            return (
              <Link
                key={resource.id}
                to={`/resources/${resource.id}`}
                className="group bg-white/6 hover:bg-white/10 border border-white/10 hover:border-white/20 rounded-2xl p-5 transition-all duration-300 cursor-pointer block"
              >
                <div className="flex items-start gap-4">
                  <div
                    className="w-12 h-12 flex-none flex items-center justify-center rounded-xl"
                    style={{ backgroundColor: `${color}22` }}
                  >
                    <i className="ri-book-2-line text-xl" style={{ color }} />
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-3 mb-2">
                      <span
                        className="px-2 py-0.5 rounded-full text-[10px] font-semibold"
                        style={{ backgroundColor: `${color}18`, color }}
                      >
                        {resource.category}
                      </span>
                      <span className="text-white/25 text-xs font-bold">#{i + 1}</span>
                    </div>

                    <h3 className="font-semibold text-white text-base leading-snug line-clamp-2 group-hover:text-[#DDC398] transition-colors duration-200">
                      {resource.title}
                    </h3>
                    <p className="text-white/45 text-sm mt-1">{resource.author}</p>
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      </div>
    </section>
  );
}
