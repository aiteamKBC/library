import { Suspense, lazy } from "react";
import type { RouteObject } from "react-router-dom";
import { Navigate } from "react-router-dom";

const NotFound = lazy(() => import("../pages/NotFound"));
const Home = lazy(() => import("../pages/home/page"));
const Categories = lazy(() => import("../pages/categories/page"));
const Resources = lazy(() => import("../pages/resources/page"));
const ResourceDetail = lazy(() => import("../pages/resources/detail/page"));
const Support = lazy(() => import("../pages/support/page"));
const Admin = lazy(() => import("../pages/admin/page"));

function withSuspense(element: React.ReactNode) {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-[#F9F4EC] flex items-center justify-center">
          <div className="flex items-center gap-3 rounded-full border border-[#E9D9BD] bg-white px-5 py-3 shadow-sm">
            <div className="h-2.5 w-2.5 rounded-full bg-[#442F73] animate-pulse" />
            <p className="text-sm font-medium text-[#241453]">Loading page...</p>
          </div>
        </div>
      }
    >
      {element}
    </Suspense>
  );
}

const routes: RouteObject[] = [
  {
    path: "/",
    element: withSuspense(<Home />),
  },
  {
    path: "/categories",
    element: withSuspense(<Categories />),
  },
  {
    path: "/resources",
    element: withSuspense(<Resources />),
  },
  {
    path: "/resources/:id",
    element: withSuspense(<ResourceDetail />),
  },
  {
    path: "/support",
    element: withSuspense(<Support />),
  },
  {
    path: "/admin",
    element: <Navigate to="/libraryadmin" replace />,
  },
  {
    path: "/libraryadmin",
    element: withSuspense(<Admin />),
  },
  {
    path: "*",
    element: withSuspense(<NotFound />),
  },
];

export default routes;
