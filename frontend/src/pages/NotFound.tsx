import { Link, useLocation } from "react-router-dom";

export default function NotFound() {
  const location = useLocation();

  return (
    <div className="relative flex flex-col items-center justify-center h-screen text-center px-4">
      <h1 className="absolute bottom-0 text-9xl md:text-[12rem] font-black text-gray-50 select-none pointer-events-none z-0">
        404
      </h1>
      <div className="relative z-10">
        <h1 className="text-xl md:text-2xl font-semibold mt-6">Page Not Found</h1>
        <p className="mt-2 text-base text-gray-400 font-mono">{location.pathname}</p>
        <p className="mt-4 text-lg md:text-xl text-gray-500">The page you are looking for does not exist.</p>
        <div className="mt-6 flex flex-col sm:flex-row items-center justify-center gap-3">
          <Link
            to="/"
            className="px-5 py-2.5 bg-[#442F73] text-white text-sm font-semibold rounded-full hover:bg-[#241453] transition-colors duration-200"
          >
            Back Home
          </Link>
          <Link
            to="/resources"
            className="px-5 py-2.5 bg-[#F3E9DA] text-[#442F73] text-sm font-semibold rounded-full hover:bg-[#E9D9BD] transition-colors duration-200"
          >
            Browse Books
          </Link>
        </div>
      </div>
    </div>
  );
}
