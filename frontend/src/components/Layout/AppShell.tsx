import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";

import Sidebar from "./Sidebar";
import Topbar from "./Topbar";

const AppShell = () => {
  const location = useLocation();

  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [mobileSidebarOpen, setMobileSidebarOpen] =
    useState(false);

  const [darkMode, setDarkMode] = useState(false);

  const [pageTitle, setPageTitle] =
    useState("Dashboard");

  const [isLoading, setIsLoading] =
    useState(false);

  const toggleSidebar = () => {
    setSidebarOpen((prev) => !prev);
  };

  const toggleMobileSidebar = () => {
    setMobileSidebarOpen((prev) => !prev);
  };

  const toggleDarkMode = () => {
    setDarkMode((prev) => !prev);
  };

  useEffect(() => {
    const savedTheme =
      localStorage.getItem("theme");

    if (savedTheme === "dark") {
      setDarkMode(true);
    }
  }, []);

  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add("dark");
      localStorage.setItem("theme", "dark");
    } else {
      document.documentElement.classList.remove("dark");
      localStorage.setItem("theme", "light");
    }
  }, [darkMode]);

  useEffect(() => {
    switch (location.pathname) {
      case "/":
        setPageTitle("Dashboard");
        break;

      case "/documents":
        setPageTitle("Documents");
        break;

      case "/upload":
        setPageTitle("Upload Documents");
        break;

      case "/analysis":
        setPageTitle("Document Analysis");
        break;

      case "/chat":
        setPageTitle("AI Assistant");
        break;

      case "/analytics":
        setPageTitle("Analytics");
        break;

      case "/settings":
        setPageTitle("Settings");
        break;

      default:
        setPageTitle("Document Intelligence");
        break;
    }
  }, [location.pathname]);

  return (
    <div
      className="
        flex
        h-screen
        overflow-hidden
        bg-slate-100
        dark:bg-slate-950
      "
    >
      {/* Desktop Sidebar */}

      <div className="hidden lg:block">
        <Sidebar
          sidebarOpen={sidebarOpen}
          toggleSidebar={toggleSidebar}
        />
      </div>

      {/* Mobile Overlay */}

      {mobileSidebarOpen && (
        <div
          className="
            fixed
            inset-0
            z-40
            bg-black/50
            lg:hidden
          "
          onClick={toggleMobileSidebar}
        />
      )}

      {/* Mobile Sidebar */}

      <div
        className={`
          fixed
          left-0
          top-0
          z-50
          h-screen
          transition-transform
          duration-300
          lg:hidden
          ${
            mobileSidebarOpen
              ? "translate-x-0"
              : "-translate-x-full"
          }
        `}
      >
        <Sidebar
          sidebarOpen={true}
          toggleSidebar={toggleMobileSidebar}
        />
      </div>

      {/* Main Area */}

      <div className="flex flex-1 flex-col overflow-hidden">
        <Topbar
          pageTitle={pageTitle}
          sidebarOpen={sidebarOpen}
          darkMode={darkMode}
          toggleSidebar={toggleSidebar}
          toggleMobileSidebar={
            toggleMobileSidebar
          }
          toggleDarkMode={toggleDarkMode}
        />

        {/* Page Container */}

        <main
          className="
            flex-1
            overflow-y-auto
            bg-slate-100
            dark:bg-slate-950
          "
        >
          <div className="mx-auto max-w-7xl p-6">
            {/* Breadcrumb */}

            <div className="mb-8">
              <p
                className="
                  text-sm
                  font-medium
                  text-slate-500
                "
              >
                Home / {pageTitle}
              </p>

              <h1
                className="
                  mt-2
                  text-3xl
                  font-bold
                  text-slate-900
                  dark:text-white
                "
              >
                {pageTitle}
              </h1>
            </div>

            {/* Global Loading Bar */}

            {isLoading && (
              <div className="mb-6">
                <div
                  className="
                    h-2
                    overflow-hidden
                    rounded-full
                    bg-slate-200
                  "
                >
                  <div
                    className="
                      h-full
                      w-1/2
                      animate-pulse
                      rounded-full
                      bg-blue-600
                    "
                  />
                </div>
              </div>
            )}

            {/* Routed Pages */}

            <Outlet />
          </div>
        </main>

        {/* Footer */}

        <footer
          className="
            border-t
            border-slate-200
            bg-white
            px-6
            py-3
            dark:border-slate-800
            dark:bg-slate-900
          "
        >
          <div
            className="
              flex
              flex-col
              gap-2
              text-center
              text-xs
              text-slate-500
              md:flex-row
              md:justify-between
            "
          >
            <span>
              © 2026 Document Intelligence System
            </span>

            <span>
              AI Powered Document Analysis Platform
            </span>
          </div>
        </footer>
      </div>
    </div>
  );
};

export default AppShell;