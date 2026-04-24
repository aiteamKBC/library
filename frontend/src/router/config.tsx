import { Suspense, lazy } from "react";
import type { RouteObject } from "react-router-dom";
import { Navigate } from "react-router-dom";

const NotFound = lazy(() => import("../pages/NotFound"));
const Home = lazy(() => import("../pages/home/page"));
const Categories = lazy(() => import("../pages/categories/page"));
const Resources = lazy(() => import("../pages/resources/page"));
const ResourceDetail = lazy(() => import("../pages/resources/detail/page"));
const Support = lazy(() => import("../pages/support/page"));
const Account = lazy(() => import("../pages/account/page"));
const Admin = lazy(() => import("../pages/admin/page"));
const Feedback = lazy(() => import("../pages/feedback/page"));

const loadingFallback = (
  <div className="min-h-screen bg-[#F9F4EC] flex items-center justify-center">
    <div className="flex items-center gap-3 rounded-full border border-[#E9D9BD] bg-white px-5 py-3 shadow-sm">
      <div className="h-2.5 w-2.5 rounded-full bg-[#442F73] animate-pulse" />
      <p className="text-sm font-medium text-[#241453]">Loading page...</p>
    </div>
  </div>
);

const routes: RouteObject[] = [
  {
    path: "/",
    element: (
      <Suspense fallback={loadingFallback}>
        <Home />
      </Suspense>
    ),
  },
  {
    path: "/categories",
    element: (
      <Suspense fallback={loadingFallback}>
        <Categories />
      </Suspense>
    ),
  },
  {
    path: "/resources",
    element: (
      <Suspense fallback={loadingFallback}>
        <Resources />
      </Suspense>
    ),
  },
  {
    path: "/resources/:id",
    element: (
      <Suspense fallback={loadingFallback}>
        <ResourceDetail />
      </Suspense>
    ),
  },
  {
    path: "/support",
    element: (
      <Suspense fallback={loadingFallback}>
        <Support />
      </Suspense>
    ),
  },
  {
    path: "/account",
    element: (
      <Suspense fallback={loadingFallback}>
        <Account />
      </Suspense>
    ),
  },
  {
    path: "/admin",
    element: <Navigate to="/libraryadmin" replace />,
  },
  {
    path: "/libraryadmin",
    element: (
      <Suspense fallback={loadingFallback}>
        <Admin />
      </Suspense>
    ),
  },
  {
    path: "/feedback",
    element: (
      <Suspense fallback={loadingFallback}>
        <Feedback />
      </Suspense>
    ),
  },
  {
    path: "*",
    element: (
      <Suspense fallback={loadingFallback}>
        <NotFound />
      </Suspense>
    ),
  },
];

export default routes;
