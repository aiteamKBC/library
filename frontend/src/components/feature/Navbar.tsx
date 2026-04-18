import { useState, useEffect, useRef } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

const navLinks = [
  { label: "Home", path: "/" },
  { label: "Categories", path: "/categories" },
  { label: "Resources", path: "/resources" },
  { label: "Support", path: "/support" },
];

const adminLink = { label: "Library Admin", path: "/libraryadmin" };

export default function Navbar() {
  const [scrolled, setScrolled] = useState(() => window.scrollY > 30);
  const [menuOpen, setMenuOpen] = useState(false);
  const [mobileSearch, setMobileSearch] = useState("");
  const location = useLocation();
  const navigate = useNavigate();
  const headerRef = useRef<HTMLElement | null>(null);

  const submitSearch = (query: string) => {
    const trimmedQuery = query.trim();
    navigate(`/resources${trimmedQuery ? `?q=${encodeURIComponent(trimmedQuery)}` : ""}`);
  };

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 30);
    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    setMenuOpen(false);
    setScrolled(window.scrollY > 30);
  }, [location.pathname]);

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (!headerRef.current?.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, []);

  const isAdminActive =
    location.pathname === adminLink.path ||
    (adminLink.path !== "/" && location.pathname.startsWith(adminLink.path));

  return (
    <header ref={headerRef} className="fixed top-0 left-0 right-0 z-50">
      <nav
        className={`transition-all duration-300 ${
          scrolled
            ? "bg-white border-b border-gray-200 shadow-sm"
            : "bg-transparent"
        }`}
      >
        <div className="max-w-7xl mx-auto px-4 md:px-6 h-[96px] flex items-center justify-between">
          <Link to="/" className="flex items-center cursor-pointer whitespace-nowrap">
            <div className="flex h-[72px] w-[112px] md:h-[88px] md:w-[138px] items-center justify-center transition-all duration-300">
              <img
                src="/assets/kbc-logo.webp"
                alt="Kent Business College logo"
                className="block h-full w-full object-contain"
              />
            </div>
          </Link>

          <ul className="hidden md:flex items-center gap-0.5">
            {navLinks.map((link) => {
              const isActive = location.pathname === link.path || (link.path !== "/" && location.pathname.startsWith(link.path));
              return (
                <li key={link.path}>
                  <Link
                    to={link.path}
                    className={`relative px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 cursor-pointer whitespace-nowrap group ${
                      isActive
                        ? scrolled
                          ? "text-[#182028] bg-[#F3E9DA]"
                          : "text-white"
                        : scrolled
                          ? "text-gray-700 hover:text-[#182028] hover:bg-[#F9F4EC]"
                          : "text-white/75 hover:text-white"
                    }`}
                  >
                    {link.label}
                    <span
                      className={`absolute bottom-0.5 left-4 right-4 h-0.5 rounded-full transition-all duration-200 ${
                        isActive
                          ? "bg-[#CEA869] opacity-100"
                          : "bg-[#CEA869] opacity-0 group-hover:opacity-30"
                      }`}
                    />
                  </Link>
                </li>
              );
            })}
          </ul>

          <div className="flex items-center gap-2 md:gap-3">
            <Link
              to={adminLink.path}
              className={`hidden md:flex items-center gap-1.5 px-4 py-2 rounded-full text-sm font-semibold transition-all duration-200 cursor-pointer whitespace-nowrap ${
                isAdminActive
                  ? scrolled
                    ? "bg-[#241453] text-white ring-2 ring-[#CEA869]/25"
                    : "bg-white/22 backdrop-blur-sm text-white border border-white/30"
                  : scrolled
                    ? "bg-[#241453] text-white hover:bg-[#0d1218]"
                    : "bg-white/15 backdrop-blur-sm text-white hover:bg-white/25 border border-white/25"
              }`}
            >
              <i className="ri-shield-keyhole-line text-xs" />
              {adminLink.label}
            </Link>

            <button
              onClick={() => setMenuOpen(!menuOpen)}
              className={`md:hidden w-9 h-9 flex items-center justify-center rounded-lg transition-all duration-200 cursor-pointer ${
                scrolled ? "text-[#182028]" : "text-white"
              }`}
            >
              <i className={`text-xl ${menuOpen ? "ri-close-line" : "ri-menu-3-line"}`} />
            </button>
          </div>
        </div>
      </nav>

      {menuOpen && (
        <div className="md:hidden bg-white border-b border-gray-100 shadow-lg px-4 pb-5 pt-3">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submitSearch(mobileSearch);
            }}
            className="relative mb-4"
          >
            <i className="ri-search-line absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm" />
            <input
              type="text"
              value={mobileSearch}
              onChange={(e) => setMobileSearch(e.target.value)}
              placeholder="Search books..."
              className="w-full pl-9 pr-4 py-2.5 text-sm bg-[#F9F4EC] border border-[#E9D9BD] rounded-xl outline-none focus:border-[#182028] text-gray-800 placeholder-gray-400"
            />
          </form>
          <ul className="space-y-0.5">
            {navLinks.map((link) => {
              const isActive = location.pathname === link.path || (link.path !== "/" && location.pathname.startsWith(link.path));
              return (
                <li key={link.path}>
                  <Link
                    to={link.path}
                    className={`flex items-center gap-2.5 px-4 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 cursor-pointer ${
                      isActive
                        ? "text-[#182028] bg-[#F3E9DA] font-semibold"
                        : "text-gray-600 hover:text-[#182028] hover:bg-[#F9F4EC]"
                    }`}
                  >
                    {link.label}
                    {isActive && <span className="ml-auto w-1.5 h-1.5 rounded-full bg-[#CEA869]" />}
                  </Link>
                </li>
              );
            })}
          </ul>
          <div className="mt-4 pt-4 border-t border-gray-100 space-y-2.5">
            <Link
              to={adminLink.path}
              className={`flex items-center gap-2.5 px-4 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 cursor-pointer ${
                isAdminActive
                  ? "text-[#182028] bg-[#F3E9DA] font-semibold"
                  : "text-gray-600 hover:text-[#182028] hover:bg-[#F9F4EC]"
              }`}
            >
              <i className="ri-shield-keyhole-line" />
              {adminLink.label}
              {isAdminActive && <span className="ml-auto w-1.5 h-1.5 rounded-full bg-[#CEA869]" />}
            </Link>
            <Link
              to="/resources"
              className="flex items-center justify-center gap-2 w-full py-3 rounded-full text-sm font-semibold bg-[#131a22] text-white cursor-pointer whitespace-nowrap"
            >
              <i className="ri-book-open-line" />
              Browse All Books
            </Link>
          </div>
        </div>
      )}
    </header>
  );
}
