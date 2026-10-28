// src/components/pages/Admin.tsx

import React, { useMemo, useState } from "react";
import {
  Shield,
  Users,
  Activity,
  AlertTriangle,
  Settings,
  Database,
  Lock,
  Search,
  RefreshCw,
} from "lucide-react";

interface UserSummary {
  id: string;
  name: string;
  email: string;
  role: string;
  status: "Active" | "Suspended";
}

const mockUsers: UserSummary[] = [
  {
    id: "1",
    name: "John Smith",
    email: "john.smith@company.com",
    role: "Administrator",
    status: "Active",
  },
  {
    id: "2",
    name: "Sarah Connor",
    email: "sarah.connor@company.com",
    role: "Security Analyst",
    status: "Active",
  },
  {
    id: "3",
    name: "Michael Adams",
    email: "michael.adams@company.com",
    role: "Viewer",
    status: "Suspended",
  },
];

const StatCard = ({
  title,
  value,
  icon,
  color,
}: {
  title: string;
  value: string;
  icon: React.ReactNode;
  color: string;
}) => (
  <div className="rounded-xl border bg-white p-5 shadow-sm transition hover:shadow-md">
    <div className="flex items-center justify-between">
      <div>
        <p className="text-sm text-gray-500">{title}</p>
        <h3 className="mt-2 text-3xl font-bold">{value}</h3>
      </div>

      <div className={`rounded-lg p-3 ${color}`}>{icon}</div>
    </div>
  </div>
);

export default function Admin(): JSX.Element {
  const [search, setSearch] = useState("");

  const filteredUsers = useMemo(
    () =>
      mockUsers.filter(
        (user) =>
          user.name.toLowerCase().includes(search.toLowerCase()) ||
          user.email.toLowerCase().includes(search.toLowerCase())
      ),
    [search]
  );

  return (
    <div className="min-h-screen bg-slate-50 p-6">
      {/* Header */}
      <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">
            Administration Center
          </h1>
          <p className="mt-1 text-slate-500">
            Manage users, permissions, security and platform health.
          </p>
        </div>

        <button
          className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700"
          type="button"
        >
          <RefreshCw size={18} />
          Refresh
        </button>
      </div>

      {/* Stats */}
      <div className="mb-8 grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title="Active Users"
          value="1,284"
          color="bg-blue-100"
          icon={<Users className="text-blue-600" />}
        />

        <StatCard
          title="Security Events"
          value="32"
          color="bg-red-100"
          icon={<Shield className="text-red-600" />}
        />

        <StatCard
          title="Audit Logs Today"
          value="8,459"
          color="bg-green-100"
          icon={<Activity className="text-green-600" />}
        />

        <StatCard
          title="System Alerts"
          value="4"
          color="bg-amber-100"
          icon={<AlertTriangle className="text-amber-600" />}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        {/* User Management */}
        <div className="xl:col-span-2 rounded-xl border bg-white shadow-sm">
          <div className="border-b p-5">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <h2 className="text-xl font-semibold">
                User Administration
              </h2>

              <div className="relative w-full md:w-80">
                <Search
                  size={18}
                  className="absolute left-3 top-3 text-gray-400"
                />

                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search users..."
                  className="w-full rounded-lg border py-2 pl-10 pr-4 focus:border-blue-500 focus:outline-none"
                />
              </div>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-slate-50">
                <tr>
                  <th className="p-4 text-left text-sm font-semibold">
                    Name
                  </th>
                  <th className="p-4 text-left text-sm font-semibold">
                    Email
                  </th>
                  <th className="p-4 text-left text-sm font-semibold">
                    Role
                  </th>
                  <th className="p-4 text-left text-sm font-semibold">
                    Status
                  </th>
                </tr>
              </thead>

              <tbody>
                {filteredUsers.map((user) => (
                  <tr key={user.id} className="border-t">
                    <td className="p-4">{user.name}</td>
                    <td className="p-4">{user.email}</td>
                    <td className="p-4">{user.role}</td>
                    <td className="p-4">
                      <span
                        className={`rounded-full px-3 py-1 text-xs font-medium ${
                          user.status === "Active"
                            ? "bg-green-100 text-green-700"
                            : "bg-red-100 text-red-700"
                        }`}
                      >
                        {user.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Management Panel */}
        <div className="space-y-4">
          <div className="rounded-xl border bg-white p-5 shadow-sm">
            <h3 className="mb-4 font-semibold">Quick Actions</h3>

            <div className="space-y-3">
              <button className="flex w-full items-center gap-3 rounded-lg border p-3 text-left hover:bg-slate-50">
                <Users size={18} />
                Manage Users
              </button>

              <button className="flex w-full items-center gap-3 rounded-lg border p-3 text-left hover:bg-slate-50">
                <Lock size={18} />
                Access Policies
              </button>

              <button className="flex w-full items-center gap-3 rounded-lg border p-3 text-left hover:bg-slate-50">
                <Database size={18} />
                Data Management
              </button>

              <button className="flex w-full items-center gap-3 rounded-lg border p-3 text-left hover:bg-slate-50">
                <Settings size={18} />
                System Settings
              </button>
            </div>
          </div>

          <div className="rounded-xl border bg-white p-5 shadow-sm">
            <h3 className="mb-4 font-semibold">Platform Health</h3>

            <div className="space-y-4">
              <div>
                <div className="mb-1 flex justify-between text-sm">
                  <span>API Availability</span>
                  <span>99.9%</span>
                </div>

                <div className="h-2 rounded-full bg-gray-100">
                  <div className="h-2 w-[99%] rounded-full bg-green-500" />
                </div>
              </div>

              <div>
                <div className="mb-1 flex justify-between text-sm">
                  <span>Storage</span>
                  <span>68%</span>
                </div>

                <div className="h-2 rounded-full bg-gray-100">
                  <div className="h-2 w-[68%] rounded-full bg-blue-500" />
                </div>
              </div>

              <div>
                <div className="mb-1 flex justify-between text-sm">
                  <span>CPU Usage</span>
                  <span>34%</span>
                </div>

                <div className="h-2 rounded-full bg-gray-100">
                  <div className="h-2 w-[34%] rounded-full bg-amber-500" />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}