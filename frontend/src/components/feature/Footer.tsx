import { Link } from "react-router-dom";

const quickLinks = [
  { label: "Home", path: "/" },
  { label: "Categories", path: "/categories" },
  { label: "Browse Books", path: "/resources" },
  { label: "Help & Support", path: "/support" },
];

export default function Footer() {
  const year = new Date().getFullYear();

  return (
    <footer className="bg-[#241453] text-white" >
      <div className="max-w-7xl mx-auto px-4 md:px-6 py-12 md:py-14">
        <div className="grid grid-cols-1 md:grid-cols-[1.2fr_0.8fr] gap-10 md:gap-12">
          <div>
            <div className="flex items-center gap-3 mb-4">
              <img
                src="/assets/kbc-logo.webp"
                alt="Kent Business College logo"
                className="w-11 h-11 object-contain"
              />
              <div>
                <p className="font-bold text-white text-base" style={{ fontFamily: "'Playfair Display', serif" }}>KBC Library</p>
                <p className="text-white/50 text-xs">Digital Resource Portal</p>
              </div>
            </div>
            <p className="text-white/60 text-sm leading-relaxed max-w-sm">
              Browse the current KBC library collection by title, author and category.
            </p>
          </div>

          <div>
            <h4 className="font-semibold text-sm uppercase tracking-wider text-white/80 mb-4 pb-3 border-b border-white/10">
              Quick Links
            </h4>
            <ul className="space-y-2.5">
              {quickLinks.map((link) => (
                <li key={link.label}>
                  <Link
                    to={link.path}
                    className="text-white/60 hover:text-white text-sm transition-colors duration-200 cursor-pointer flex items-center gap-1.5 group"
                  >
                    <i className="ri-arrow-right-s-line text-white/30 group-hover:text-white/70 transition-colors duration-200" />
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      <div className="border-t border-white/10">
        <div className="max-w-7xl mx-auto px-4 md:px-6 py-4 flex flex-col sm:flex-row items-center justify-between gap-3">
          <p className="text-white/40 text-xs">
            &copy; {year} KBC Digital Library. All rights reserved.
          </p>
          <div className="flex items-center gap-4">
            <Link to="/support" className="text-white/40 hover:text-white/70 text-xs transition-colors duration-200 cursor-pointer">Support</Link>
            <Link to="/resources" className="text-white/40 hover:text-white/70 text-xs transition-colors duration-200 cursor-pointer">Books</Link>
            <Link to="/support#contact" className="text-white/40 hover:text-white/70 text-xs transition-colors duration-200 cursor-pointer">Contact</Link>
          </div>
        </div>
      </div>
    </footer>
  );
}
