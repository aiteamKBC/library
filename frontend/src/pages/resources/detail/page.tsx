import { useMemo, useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import Navbar from "../../../components/feature/Navbar";
import Footer from "../../../components/feature/Footer";
import ResourceSidebar from "./components/ResourceSidebar";
import RelatedResources from "./components/RelatedResources";
import { useAdminData } from "../../../hooks/useAdminData";
import RequestModal from "../components/RequestModal";

export default function ResourceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { books, categories, loading } = useAdminData();
  const [requestOpen, setRequestOpen] = useState(false);

  const resource = useMemo(() => books.find((r) => r.id === id), [books, id]);

  const related = useMemo(() => {
    if (!resource) return [];
    return books.filter((r) => r.id !== resource.id && r.categoryId === resource.categoryId).slice(0, 4);
  }, [books, resource]);

  const handleRequestBook = () => {
    if (!resource) {
      return;
    }
    setRequestOpen(true);
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-white">
        <Navbar />
        <section className="relative pt-28 pb-12 overflow-hidden" style={{ background: "linear-gradient(135deg, #241453 0%, #442F73 60%, #644D93 100%)" }}>
          <div className="relative z-10 max-w-7xl mx-auto px-4 md:px-6 animate-pulse">
            <div className="h-4 w-40 rounded bg-white/10 mb-5" />
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 items-start">
              <div className="lg:col-span-2">
                <div className="flex gap-2 mb-4">
                  <div className="h-8 w-36 rounded-full bg-white/10" />
                  <div className="h-8 w-20 rounded-full bg-white/10" />
                </div>
                <div className="h-10 w-3/4 rounded bg-white/10 mb-4" />
                <div className="h-4 w-48 rounded bg-white/10 mb-3" />
                <div className="h-4 w-full max-w-2xl rounded bg-white/10 mb-2" />
                <div className="h-4 w-full max-w-xl rounded bg-white/10" />
              </div>
              <div className="hidden lg:flex justify-end">
                <div className="w-52 h-64 rounded-2xl bg-white/10" />
              </div>
            </div>
          </div>
        </section>
        <section className="py-12 bg-[#F9F4EC]">
          <div className="max-w-7xl mx-auto px-4 md:px-6">
            <div className="flex flex-col lg:flex-row gap-8 items-start">
              <main className="flex-1 min-w-0">
                <div className="bg-white rounded-2xl border border-[#E9D9BD] p-6 md:p-8 animate-pulse">
                  <div className="h-6 w-40 rounded bg-[#F1E3CB] mb-5" />
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    {Array.from({ length: 6 }).map((_, index) => (
                      <div key={index} className="rounded-xl bg-[#F9F4EC] border border-[#F1E3CB] px-4 py-3">
                        <div className="h-3 w-16 rounded bg-[#F1E3CB] mb-2" />
                        <div className="h-4 w-3/4 rounded bg-[#E9D9BD]" />
                      </div>
                    ))}
                  </div>
                </div>
              </main>
              <aside className="w-full lg:w-72 flex-none">
                <div className="space-y-5 animate-pulse">
                  <div className="bg-[#241453] rounded-2xl p-5">
                    <div className="h-5 w-28 rounded bg-white/10 mb-5" />
                    <div className="h-24 rounded-xl bg-white/10 mb-4" />
                    <div className="space-y-3">
                      <div className="h-11 rounded-xl bg-white/10" />
                      <div className="h-11 rounded-xl bg-white/10" />
                      <div className="h-11 rounded-xl bg-white/10" />
                    </div>
                  </div>
                  <div className="bg-white rounded-2xl border border-[#E9D9BD] p-5">
                    <div className="h-5 w-28 rounded bg-[#F1E3CB] mb-4" />
                    <div className="space-y-3">
                      {Array.from({ length: 5 }).map((_, index) => (
                        <div key={index} className="flex items-start gap-3">
                          <div className="w-7 h-7 rounded-lg bg-[#F9F4EC]" />
                          <div className="flex-1">
                            <div className="h-3 w-16 rounded bg-[#F1E3CB] mb-2" />
                            <div className="h-4 w-3/4 rounded bg-[#E9D9BD]" />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </aside>
            </div>
          </div>
        </section>
        <Footer />
      </div>
    );
  }

  if (!resource) {
    return (
      <div className="min-h-screen bg-white">
        <Navbar />
        <div className="flex flex-col items-center justify-center min-h-[60vh] text-center px-4">
          <div className="w-20 h-20 flex items-center justify-center rounded-full bg-[#F3E9DA] mb-5">
            <i className="ri-file-unknow-line text-4xl text-[#B27715]/50" />
          </div>
          <h1 className="text-2xl font-bold text-[#241453] mb-2">Book Not Found</h1>
          <p className="text-gray-500 text-sm mb-6">The book you&apos;re looking for doesn&apos;t exist or has been removed.</p>
          <button
            onClick={() => navigate("/resources")}
            className="px-6 py-3 bg-[#442F73] text-white text-sm font-semibold rounded-full cursor-pointer hover:bg-[#241453] transition-colors duration-200 whitespace-nowrap"
          >
            Back to Books
          </button>
        </div>
        <Footer />
      </div>
    );
  }

  const color = categories.find((category) => category.name === resource.category)?.color ?? "#442F73";

  return (
    <div className="min-h-screen bg-white">
      <Navbar />

      <section className="relative pt-28 pb-12 overflow-hidden" style={{ background: "linear-gradient(135deg, #241453 0%, #442F73 60%, #644D93 100%)" }}>
        <div className="absolute inset-0 opacity-10">
          <div className="absolute top-10 right-20 w-96 h-96 rounded-full bg-white/20 blur-3xl" />
          <div className="absolute bottom-0 left-10 w-72 h-72 rounded-full bg-[#CEA869]/20 blur-3xl" />
        </div>
        <div className="relative z-10 max-w-7xl mx-auto px-4 md:px-6">
          <nav className="flex items-center gap-2 text-white/50 text-xs mb-5 flex-wrap">
            <Link to="/" className="hover:text-white transition-colors duration-200 cursor-pointer">Home</Link>
            <i className="ri-arrow-right-s-line" />
            <Link to="/resources" className="hover:text-white transition-colors duration-200 cursor-pointer">Books</Link>
            <i className="ri-arrow-right-s-line" />
            <span className="text-white/70 line-clamp-1">{resource.title}</span>
          </nav>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 items-start">
            <div className="lg:col-span-2">
              <div className="flex flex-wrap items-center gap-2 mb-4">
                <span
                  className="px-3 py-1 rounded-full text-xs font-semibold"
                  style={{ backgroundColor: `${color}20`, color: "#fff", border: "1px solid rgba(255,255,255,0.15)" }}
                >
                  {resource.category}
                </span>
                <span className="px-3 py-1 rounded-full text-xs font-medium bg-white/10 text-white/80">
                  Book
                </span>
              </div>

              <h1 className="text-3xl md:text-4xl font-bold text-white mb-3 leading-snug" style={{ fontFamily: "'Playfair Display', serif" }}>
                {resource.title}
              </h1>
              <p className="text-white/70 text-sm mb-2">
                <span className="text-white/50">by</span> <span className="text-white/90 font-medium">{resource.author}</span>
              </p>
              {resource.description && (
                <p className="text-[#F3E9DA] text-sm leading-7 max-w-2xl mt-4">
                  {resource.description}
                </p>
              )}
            </div>

            <div className="hidden lg:flex justify-end">
              <div
                className="w-52 h-64 rounded-2xl flex flex-col items-center justify-center relative overflow-hidden"
                style={{ background: `linear-gradient(145deg, ${color}55, ${color})`, border: `1px solid ${color}` }}
              >
                <div className="absolute left-0 top-0 bottom-0 w-6 rounded-l-2xl bg-black/10" />
                {resource.coverImage ? (
                  <div className="relative z-10 flex h-full w-full items-center justify-center bg-white p-4">
                    <img
                      src={resource.coverImage}
                      alt={`Cover of ${resource.title}`}
                      className="h-full w-full object-contain"
                    />
                  </div>
                ) : (
                  <div className="px-8 text-center relative z-10">
                    <i className="ri-book-3-line text-5xl text-white/70 mb-3 block" />
                    <p className="text-white text-xs font-semibold text-center leading-snug line-clamp-3">{resource.title}</p>
                    <p className="text-white/60 text-xs mt-2">{resource.author}</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="py-12 bg-[#F9F4EC]">
        <div className="max-w-7xl mx-auto px-4 md:px-6">
          <div className="flex flex-col lg:flex-row gap-8 items-start">
            <main className="flex-1 min-w-0 space-y-6">
              <div className="bg-white rounded-2xl border border-[#E9D9BD] p-6 md:p-8">
                <h2 className="font-bold text-[#241453] text-lg mb-4 flex items-center gap-2" style={{ fontFamily: "'Playfair Display', serif" }}>
                  <i className="ri-information-line text-[#442F73]" />
                  Book Information
                </h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
                  <div className="rounded-xl bg-[#F9F4EC] border border-[#F1E3CB] px-4 py-3">
                    <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Title</p>
                    <p className="font-semibold text-[#241453] leading-snug">{resource.title}</p>
                  </div>
                  <div className="rounded-xl bg-[#F9F4EC] border border-[#F1E3CB] px-4 py-3">
                    <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Author</p>
                    <p className="font-semibold text-[#241453] leading-snug">{resource.author}</p>
                  </div>
                  <div className="rounded-xl bg-[#F9F4EC] border border-[#F1E3CB] px-4 py-3">
                    <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Category</p>
                    <p className="font-semibold text-[#241453] leading-snug">{resource.category}</p>
                  </div>
                  {resource.publisher && (
                    <div className="rounded-xl bg-[#F9F4EC] border border-[#F1E3CB] px-4 py-3">
                      <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Publisher</p>
                      <p className="font-semibold text-[#241453] leading-snug">{resource.publisher}</p>
                    </div>
                  )}
                  {resource.publicationYear && (
                    <div className="rounded-xl bg-[#F9F4EC] border border-[#F1E3CB] px-4 py-3">
                      <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Published</p>
                      <p className="font-semibold text-[#241453] leading-snug">{resource.publicationYear}</p>
                    </div>
                  )}
                  {resource.pageCount && (
                    <div className="rounded-xl bg-[#F9F4EC] border border-[#F1E3CB] px-4 py-3">
                      <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Pages</p>
                      <p className="font-semibold text-[#241453] leading-snug">{resource.pageCount}</p>
                    </div>
                  )}
                </div>
              </div>

              {related.length > 0 && <RelatedResources resources={related} />}
            </main>

            <aside className="w-full lg:w-72 flex-none">
              <ResourceSidebar resource={resource} onRequestBook={handleRequestBook} />
            </aside>
          </div>
        </div>
      </section>

      {requestOpen && (
        <RequestModal
          onClose={() => setRequestOpen(false)}
          initialBookTitle={resource.title}
          initialResourceId={resource.id}
          initialCategory={resource.category}
          expectedAvailableDate={resource.expectedAvailableDate}
          availabilityNote={resource.availabilityNote}
          mode={resource.availabilityStatus === "available" ? "borrow" : "notify"}
        />
      )}

      <Footer />
    </div>
  );
}
