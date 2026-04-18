import { Link } from "react-router-dom";

export default function BenefitsSection() {
  return (
    <section className="py-16 bg-[#F9F4EC]">
      <div className="max-w-7xl mx-auto px-4 md:px-6">
        <div className="rounded-3xl overflow-hidden bg-[#241453]">
          <div className="flex flex-col lg:flex-row items-center justify-between gap-8 px-8 md:px-12 py-12">
            <div className="max-w-2xl">
              <div className="inline-flex items-center gap-2 px-3.5 py-1.5 bg-white/10 border border-white/15 rounded-full mb-4">
                <i className="ri-book-open-line text-[#CEA869] text-xs" />
                <span className="text-white/75 text-xs font-semibold tracking-widest uppercase">Simple access to your library</span>
              </div>

              <h2
                className="text-3xl md:text-4xl font-bold text-white mb-3 leading-snug"
                style={{ fontFamily: "'Playfair Display', serif" }}
              >
                Find a resource, open it,
                <span className="text-[#CEA869]"> and start studying.</span>
              </h2>

              <p className="text-white/60 text-sm md:text-base leading-relaxed">
                We kept the experience simple: browse categories, open books, or contact the library team when you need help.
              </p>
            </div>

            <div className="flex flex-col sm:flex-row gap-3 flex-none">
              <Link
                to="/resources"
                className="flex items-center justify-center gap-2 px-8 py-3.5 bg-[#CEA869] hover:bg-[#B27715] text-[#182430] font-bold text-sm rounded-full transition-all duration-200 cursor-pointer whitespace-nowrap"
              >
                <i className="ri-book-open-line" />
                Browse Books
              </Link>

              <Link
                to="/support"
                className="flex items-center justify-center gap-2 px-8 py-3.5 bg-white/10 hover:bg-white/18 border border-white/20 text-white font-semibold text-sm rounded-full transition-all duration-200 cursor-pointer whitespace-nowrap"
              >
                <i className="ri-customer-service-line" />
                Get Support
              </Link>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
