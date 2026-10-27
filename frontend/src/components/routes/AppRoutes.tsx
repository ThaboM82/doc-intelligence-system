import {
  BrowserRouter,
  Routes,
  Route,
} from "react-router-dom";

import AppShell from "../components/Layout/AppShell";

import DashboardPage from "../pages/DashboardPage";
import DocumentsPage from "../pages/DocumentsPage";
import UploadPage from "../pages/UploadPage";
import SecurityPage from "../pages/SecurityPage";
import AnalyticsPage from "../pages/AnalyticsPage";
import ChatPage from "../pages/ChatPage";
import SettingsPage from "../pages/SettingsPage";

const AppRoutes = () => {
  return (
    <BrowserRouter>
      <Routes>
        <Route
          element={<AppShell />}
        >
          <Route
            path="/"
            element={
              <DashboardPage />
            }
          />

          <Route
            path="/documents"
            element={
              <DocumentsPage />
            }
          />

          <Route
            path="/upload"
            element={<UploadPage />}
          />

          <Route
            path="/security"
            element={
              <SecurityPage />
            }
          />

          <Route
            path="/analytics"
            element={
              <AnalyticsPage />
            }
          />

          <Route
            path="/chat"
            element={<ChatPage />}
          />

          <Route
            path="/settings"
            element={
              <SettingsPage />
            }
          />
        </Route>
      </Routes>
    </BrowserRouter>
  );
};

export default AppRoutes;