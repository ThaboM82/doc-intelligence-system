import {
  Bell,
  Menu,
  Moon,
  Search,
  Sun,
  UserCircle,
} from "lucide-react";

interface TopbarProps {
  pageTitle: string;
  sidebarOpen: boolean;
  darkMode: boolean;
  toggleSidebar: () => void;
  toggleMobileSidebar: () => void;
  toggleDarkMode: () => void;
}

const Topbar = ({
  pageTitle,
  sidebarOpen,
  darkMode,
  toggleSidebar,
  toggleMobileSidebar,
  toggleDarkMode,
}: TopbarProps) => {
  return (
    <header
      className="
        h-16
        border-b
        border-slate-200
        bg-white
        dark:border-slate-800
        dark:bg-slate-900
      "
    >
      <div className="flex h-full items-center justify-between px-6">
        {/* LEFT */}

        <div className="flex items-center gap-4">
          <button
            onClick={toggleMobileSidebar}
            className="
              rounded-lg
              p-2
              transition
              hover:bg-slate-100
              dark:hover:bg-slate-800
              lg:hidden
            "
          >
            <Menu size={20} />
          </button>

          <button
            onClick={toggleSidebar}
            title={
              sidebarOpen
                ? "Collapse Sidebar"
                : "Expand Sidebar"
            }
            className="
              hidden
              rounded-lg
              p-2
              transition
              hover:bg-slate-100
              dark:hover:bg-slate-800
              lg:flex
            "
          >
            <Menu size={20} />
          </button>

          <div>
            <h2
              className="
                text-xl
                font-semibold
                text-slate-800
                dark:text-white
              "
            >
              {pageTitle}
            </h2>
          </div>
        </div>

        {/* CENTER SEARCH */}

        <div className="hidden flex-1 px-10 lg:block">
          <div className="relative mx-auto max-w-xl">
            <Search
              size={18}
              className="
                absolute
                left-3
                top-1/2
                -translate-y-1/2
                text-slate-400
              "
            />

            <input
              type="text"
              placeholder="Search documents, chats, analytics..."
              className="
                w-full
                rounded-xl
                border
                border-slate-300
                bg-slate-50
                py-2.5
                pl-10
                pr-4
                text-sm
                outline-none
                transition
                focus:border-blue-500
                focus:ring-2
                focus:ring-blue-500/20
                dark:border-slate-700
                dark:bg-slate-800
                dark:text-white
                dark:placeholder:text-slate-400
              "
            />
          </div>
        </div>

        {/* RIGHT */}

        <div className="flex items-center gap-3">
          <button
            onClick={toggleDarkMode}
            className="
              rounded-lg
              p-2
              transition
              hover:bg-slate-100
              dark:hover:bg-slate-800
            "
          >
            {darkMode ? (
              <Sun
                size={20}
                className="text-yellow-400"
              />
            ) : (
              <Moon
                size={20}
                className="text-slate-700"
              />
            )}
          </button>

          <button
            className="
              relative
              rounded-lg
              p-2
              transition
              hover:bg-slate-100
              dark:hover:bg-slate-800
            "
          >
            <Bell size={20} />

            <span
              className="
                absolute
                right-2
                top-2
                h-2
                w-2
                rounded-full
                bg-red-500
              "
            />
          </button>

          <div
            className="
              hidden
              h-8
              w-px
              bg-slate-300
              dark:bg-slate-700
              md:block
            "
          />

          <button
            className="
              flex
              items-center
              gap-3
              rounded-xl
              px-2
              py-1
              transition
              hover:bg-slate-100
              dark:hover:bg-slate-800
            "
          >
            <UserCircle
              size={38}
              className="
                text-slate-600
                dark:text-slate-300
              "
            />

            <div className="hidden text-left md:block">
              <p
                className="
                  text-sm
                  font-medium
                  text-slate-900
                  dark:text-white
                "
              >
                Admin User
              </p>

              <p
                className="
                  text-xs
                  text-slate-500
                  dark:text-slate-400
                "
              >
                System Administrator
              </p>
            </div>
          </button>
        </div>
      </div>
    </header>
  );
};

export default Topbar;