import { BrowserRouter } from "react-router-dom";
import { AppRoutes } from "./router";
import { I18nextProvider } from "react-i18next";
import i18n from "./i18n";
import { AdminDataProvider } from "./hooks/useAdminData";

function App() {
  return (
    <I18nextProvider i18n={i18n}>
      <AdminDataProvider>
        <BrowserRouter basename={__BASE_PATH__}>
          <AppRoutes />
        </BrowserRouter>
      </AdminDataProvider>
    </I18nextProvider>
  );
}

export default App;
