import { BrowserRouter } from "react-router-dom";
import { AppRoutes } from "./router";
import { I18nextProvider } from "react-i18next";
import i18n from "./i18n";
import { AdminDataProvider } from "./hooks/useAdminData";
import { LibrarySessionProvider } from "./hooks/useLibrarySession";
import ScrollToTop from "./components/ScrollToTop";

function App() {
  return (
    <I18nextProvider i18n={i18n}>
      <LibrarySessionProvider>
        <AdminDataProvider>
          <BrowserRouter basename={__BASE_PATH__}>
            <ScrollToTop />
            <AppRoutes />
          </BrowserRouter>
        </AdminDataProvider>
      </LibrarySessionProvider>
    </I18nextProvider>
  );
}

export default App;
