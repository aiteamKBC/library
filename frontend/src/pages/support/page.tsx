import { Link } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import Footer from "../../components/feature/Footer";
import LibrarianContact from "./components/LibrarianContact";

export default function SupportPage() {
  return (
    <div className="min-h-screen bg-white">
      <Navbar />

      <section
        className="relative pt-36 pb-24 md:pb-28 overflow-hidden"
        style={{ background: "linear-gradient(135deg, #241453 0%, #442F73 60%, #644D93 100%)" }}
      >
        <div className="absolute inset-0 opacity-10">
          <div className="absolute top-10 right-20 w-80 h-80 rounded-full bg-white/20 blur-3xl" />
          <div className="absolute bottom-0 left-10 w-60 h-60 rounded-full bg-[#CEA869]/20 blur-3xl" />
        </div>
        <div className="relative z-10 max-w-7xl mx-auto px-4 md:px-6">
          <nav className="flex items-center gap-2 text-white/50 text-xs mb-5">
            <Link to="/" className="hover:text-white transition-colors duration-200 cursor-pointer">Home</Link>
            <i className="ri-arrow-right-s-line" />
            <span className="text-white/80">Support</span>
          </nav>

          <div className="max-w-3xl">
            <div className="inline-flex items-center gap-2 px-3.5 py-1.5 bg-white/10 backdrop-blur-sm border border-white/20 rounded-full mb-5">
              <i className="ri-customer-service-2-line text-[#CEA869] text-xs" />
              <span className="text-white/85 text-xs font-medium">Library Support</span>
            </div>

            <h1
              className="text-4xl md:text-5xl font-bold text-white mb-4 leading-tight"
              style={{ fontFamily: "'Playfair Display', serif" }}
            >
              Need help finding a book?
            </h1>

            <p className="text-white/70 text-base md:text-lg max-w-2xl leading-relaxed">
              Use this page to contact the library team if you cannot find a title in the current collection or need help with the book list.
            </p>

            <div className="flex flex-col sm:flex-row gap-3 mt-8">
              <a
                href="#contact"
                className="flex items-center justify-center gap-2 px-6 py-3 bg-[#CEA869] hover:bg-[#B27715] text-[#241453] font-bold text-sm rounded-full transition-all duration-200 cursor-pointer whitespace-nowrap"
              >
                <i className="ri-mail-line" />
                Contact the Library
              </a>
              <Link
                to="/resources"
                className="flex items-center justify-center gap-2 px-6 py-3 bg-white/10 hover:bg-white/18 border border-white/20 text-white font-semibold text-sm rounded-full transition-all duration-200 cursor-pointer whitespace-nowrap"
              >
                <i className="ri-book-open-line" />
                Browse Books
              </Link>
            </div>
          </div>
        </div>
      </section>

      <div id="contact">
        <LibrarianContact />
      </div>

      <Footer />
    </div>
  );
}
