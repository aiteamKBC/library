import { Link } from "react-router-dom";
import { useAdminData } from "../../../../hooks/useAdminData";
import type { Resource } from "../../../../types/library";
import { formatResourceAvailabilityLine, getResourceQueueMetrics } from "../../../../lib/resourceAvailability";

interface Props {
  resources: Resource[];
}

export default function RelatedResources({ resources }: Props) {
  const { categories } = useAdminData();
  const categoryColorMap = Object.fromEntries(categories.map((category) => [category.name, category.color]));
  return (
    <section className="mt-12">
      <div className="flex items-end justify-between mb-6">
        <div>
          <div className="inline-flex items-center gap-2 px-3 py-1.5 bg-[#1B3A6B]/8 border border-[#1B3A6B]/15 rounded-full mb-2">
            <i className="ri-links-line text-[#1B3A6B] text-xs" />
            <span className="text-[#1B3A6B] text-xs font-semibold tracking-wide uppercase">Related Books</span>
          </div>
          <h3 className="text-xl font-bold text-[#0F2447]" style={{ fontFamily: "'Playfair Display', serif" }}>
            Same Category
          </h3>
        </div>
        <Link
          to="/resources"
          className="hidden sm:flex items-center gap-1.5 text-sm font-semibold text-[#1B3A6B] hover:text-[#0F2447] transition-colors duration-200 cursor-pointer whitespace-nowrap group"
        >
          View all <i className="ri-arrow-right-line group-hover:translate-x-1 transition-transform duration-200" />
        </Link>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {resources.map((resource) => {
          const color = categoryColorMap[resource.category] ?? "#442F73";
          const { canBorrow, queueFull } = getResourceQueueMetrics(resource);

          return (
            <Link
              key={resource.id}
              to={`/resources/${resource.id}`}
              className="bg-white rounded-2xl border border-gray-100 hover:border-[#1B3A6B]/20 hover:shadow-md transition-all duration-300 hover:-translate-y-0.5 overflow-hidden group cursor-pointer block p-4"
            >
              <div className="flex items-center gap-3 mb-3">
                <div
                  className="w-10 h-10 flex items-center justify-center rounded-xl"
                  style={{ backgroundColor: `${color}15` }}
                >
                  <i className="ri-book-2-line text-lg" style={{ color }} />
                </div>
                <span
                  className="px-2 py-0.5 rounded-full text-[10px] font-medium"
                  style={{ backgroundColor: `${color}15`, color }}
                >
                  {resource.category}
                </span>
              </div>

              <h4 className="font-semibold text-[#0F2447] text-sm mb-1 line-clamp-2 group-hover:text-[#1B3A6B] transition-colors duration-200 leading-snug">
                {resource.title}
              </h4>
              <p className="text-gray-400 text-xs">{resource.author}</p>
              {resource.edition && (
                <span className="mt-2 inline-flex rounded-full border border-[#E9D9BD] bg-[#FCFAF6] px-2 py-1 text-[10px] font-semibold text-[#6F5B92]">
                  {resource.edition}
                </span>
              )}
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[10px] font-semibold ${
                  queueFull
                    ? "bg-amber-50 text-amber-700"
                    : canBorrow
                    ? "bg-emerald-50 text-emerald-700"
                    : "bg-amber-50 text-amber-700"
                }`}>
                  <i className={canBorrow ? "ri-checkbox-circle-line" : "ri-time-line"} />
                  {formatResourceAvailabilityLine(resource)}
                </span>
              </div>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
