import { NavLink } from "react-router-dom";

import {
  LayoutDashboard,
  FileText,
  UploadCloud,
  MessageSquareText,
  BarChart3,
  FolderOpen,
  Settings,
  Menu,
  X,
} from "lucide-react";

interface SidebarProps {
  sidebarOpen: boolean;
  toggleSidebar: () => void;
}

const navigationItems = [
  {
    title: "Dashboard",
    path: "/",
    icon: LayoutDashboard,
  },
  {
    title: "Documents",
    path: "/documents",
    icon: FolderOpen,
  },
  {
    title: "Upload",
    path: "/upload",
    icon: UploadCloud,
  },
  {
    title: "Document Analysis",
    path: "/analysis",
    icon: FileText,
  },
  {
    title: "AI Assistant",
    path: "/chat",
    icon: MessageSquareText,
  },
  {
    title: "Analytics",
    path: "/analytics",
    icon: BarChart3,
  },
  {
    title: "Settings",
    path: "/settings",
    icon: Settings,
  },
];

const Sidebar = ({
  sidebarOpen,
  toggleSidebar,
}: SidebarProps) => {
  return (
    <aside
      className={`
        ${
          sidebarOpen ? "w-72" : "w-20"
        }
        transition-all
        duration-300
        bg-white
        border-r
        border-slate-200
        flex
        flex-col
      `}
    >
      <div className="h-16 border-b border-slate-200 flex items-center justify-between px-4">
        {sidebarOpen && (
          <div>
            <h1 className="font-bold text-xl text-blue-600">
              DocIntel
            </h1>

            <p className="text-xs text-slate-500">
              Document Intelligence System
            </p>
          </div>
        )}

        <button
          onClick={toggleSidebar}
          className="p-2 rounded-lg hover:bg-slate-100"
        >
          {sidebarOpen ? (
            <X size={18} />
          ) : (
            <Menu size={18} />
          )}
        </button>
      </div>

      <nav className="flex-1 p-4 space-y-2">
        {navigationItems.map((item) => {
          const Icon = item.icon;

          return (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                `
                flex
                items-center
                gap-3
                px-4
                py-3
                rounded-xl
                transition-all
                duration-200

                ${
                  isActive
                    ? "bg-blue-600 text-white shadow-md"
                    : "text-slate-600 hover:bg-slate-100"
                }
              `
              }
            >
              <Icon size={20} />

              {sidebarOpen && (
                <span className="font-medium">
                  {item.title}
                </span>
              )}
            </NavLink>
          );
        })}
      </nav>

      <div className="border-t border-slate-200 p-4">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-full bg-blue-600 flex items-center justify-center text-white font-bold">
            A
          </div>

          {sidebarOpen && (
            <div>
              <h3 className="text-sm font-semibold">
                Admin User
              </h3>

              <p className="text-xs text-slate-500">
                admin@docintel.com
              </p>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
};

export default Sidebar;