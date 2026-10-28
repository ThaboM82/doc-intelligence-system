// src/components/pages/Analytics.tsx

import React, { useEffect, useMemo, useState } from "react";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart,
  Pie,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
  Cell,
} from "recharts";

interface AnalyticsSummary {
  totalDocuments: number;
  totalUsers: number;
  uploadsToday: number;
  quarantineFiles: number;
  auditEvents: number;
  complianceScore: number;
  securityScore: number;
}

interface UploadTrend {
  month: string;
  uploads: number;
}

interface SecurityMetric {
  name: string;
  value: number;
}

interface ActivityMetric {
  category: string;
  count: number;
}

const COLORS = [
  "#2563eb",
  "#16a34a",
  "#dc2626",
  "#9333ea",
  "#f59e0b",
];

const Analytics: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [trends, setTrends] = useState<UploadTrend[]>([]);
  const [securityMetrics, setSecurityMetrics] = useState<SecurityMetric[]>([]);
  const [activities, setActivities] = useState<ActivityMetric[]>([]);

  useEffect(() => {
    const loadAnalytics = async () => {
      try {
        // Replace with actual API call

        const response = {
          summary: {
            totalDocuments: 12487,
            totalUsers: 842,
            uploadsToday: 324,
            quarantineFiles: 16,
            auditEvents: 18452,
            complianceScore: 94,
            securityScore: 91,
          },

          trends: [
            { month: "Jan", uploads: 1200 },
            { month: "Feb", uploads: 1400 },
            { month: "Mar", uploads: 1650 },
            { month: "Apr", uploads: 1820 },
            { month: "May", uploads: 2100 },
            { month: "Jun", uploads: 2550 },
          ],

          security: [
            { name: "Protected", value: 78 },
            { name: "Encrypted", value: 12 },
            { name: "Quarantined", value: 6 },
            { name: "Flagged", value: 4 },
          ],

          activities: [
            { category: "Uploads", count: 8434 },
            { category: "Downloads", count: 6271 },
            { category: "Shares", count: 3249 },
            { category: "Audits", count: 18452 },
          ],
        };

        setSummary(response.summary);
        setTrends(response.trends);
        setSecurityMetrics(response.security);
        setActivities(response.activities);
      } catch (error) {
        console.error("Failed to load analytics", error);
      } finally {
        setLoading(false);
      }
    };

    loadAnalytics();
  }, []);

  const riskLevel = useMemo(() => {
    if (!summary) return "Unknown";

    if (summary.securityScore >= 90) return "Low";
    if (summary.securityScore >= 70) return "Medium";

    return "High";
  }, [summary]);

  if (loading) {
    return (
      <div className="p-8">
        <div className="animate-pulse space-y-6">
          <div className="h-10 bg-gray-200 rounded" />
          <div className="grid grid-cols-4 gap-4">
            {[...Array(4)].map((_, index) => (
              <div
                key={index}
                className="h-32 bg-gray-200 rounded-xl"
              />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (!summary) {
    return (
      <div className="flex justify-center items-center h-[60vh]">
        <p className="text-red-600 text-lg">
          Unable to load analytics dashboard.
        </p>
      </div>
    );
  }

  return (
    <div className="p-8 bg-slate-50 min-h-screen">
      {/* Header */}

      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">
            Analytics Dashboard
          </h1>

          <p className="text-slate-500 mt-2">
            Enterprise security, compliance and document insights
          </p>
        </div>

        <div className="bg-white rounded-xl px-6 py-4 shadow">
          <p className="text-sm text-gray-500">Risk Level</p>

          <span
            className={`font-semibold ${
              riskLevel === "Low"
                ? "text-green-600"
                : riskLevel === "Medium"
                ? "text-yellow-600"
                : "text-red-600"
            }`}
          >
            {riskLevel}
          </span>
        </div>
      </div>

      {/* KPI SECTION */}

      <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <MetricCard
          title="Total Documents"
          value={summary.totalDocuments.toLocaleString()}
        />

        <MetricCard
          title="Users"
          value={summary.totalUsers.toLocaleString()}
        />

        <MetricCard
          title="Uploads Today"
          value={summary.uploadsToday.toLocaleString()}
        />

        <MetricCard
          title="Audit Events"
          value={summary.auditEvents.toLocaleString()}
        />
      </div>

      {/* Compliance */}

      <div className="grid lg:grid-cols-2 gap-6 mb-8">
        <ScoreCard
          title="Compliance Score"
          score={summary.complianceScore}
          color="bg-blue-600"
        />

        <ScoreCard
          title="Security Score"
          score={summary.securityScore}
          color="bg-green-600"
        />
      </div>

      {/* Charts */}

      <div className="grid lg:grid-cols-2 gap-8 mb-8">
        <div className="bg-white rounded-xl p-6 shadow">
          <h2 className="font-semibold mb-4">
            Document Upload Trends
          </h2>

          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={trends}>
              <CartesianGrid strokeDasharray="3 3" />

              <XAxis dataKey="month" />
              <YAxis />

              <Tooltip />

              <Line
                dataKey="uploads"
                stroke="#2563eb"
                strokeWidth={3}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-xl p-6 shadow">
          <h2 className="font-semibold mb-4">
            Security Overview
          </h2>

          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={securityMetrics}
                dataKey="value"
                outerRadius={100}
                label
              >
                {securityMetrics.map((entry, index) => (
                  <Cell
                    key={entry.name}
                    fill={COLORS[index % COLORS.length]}
                  />
                ))}
              </Pie>

              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Activity Chart */}

      <div className="bg-white rounded-xl p-6 shadow">
        <h2 className="font-semibold mb-4">
          Platform Activity Metrics
        </h2>

        <ResponsiveContainer width="100%" height={350}>
          <BarChart data={activities}>
            <CartesianGrid strokeDasharray="3 3" />

            <XAxis dataKey="category" />
            <YAxis />

            <Tooltip />

            <Bar
              dataKey="count"
              fill="#2563eb"
              radius={[6, 6, 0, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Enterprise Summary */}

      <div className="grid lg:grid-cols-3 gap-6 mt-8">
        <SummaryTile
          title="Quarantine Queue"
          value={summary.quarantineFiles}
          danger
        />

        <SummaryTile
          title="Compliance Status"
          value={`${summary.complianceScore}%`}
        />

        <SummaryTile
          title="Security Health"
          value={`${summary.securityScore}%`}
        />
      </div>
    </div>
  );
};

interface MetricCardProps {
  title: string;
  value: string | number;
}

const MetricCard: React.FC<MetricCardProps> = ({
  title,
  value,
}) => (
  <div className="bg-white rounded-xl shadow p-6">
    <p className="text-sm text-gray-500">{title}</p>

    <h3 className="text-3xl font-bold mt-2 text-slate-900">
      {value}
    </h3>
  </div>
);

interface ScoreCardProps {
  title: string;
  score: number;
  color: string;
}

const ScoreCard: React.FC<ScoreCardProps> = ({
  title,
  score,
  color,
}) => (
  <div className="bg-white rounded-xl shadow p-6">
    <div className="flex justify-between mb-2">
      <span>{title}</span>
      <span>{score}%</span>
    </div>

    <div className="w-full h-3 bg-gray-200 rounded-full">
      <div
        className={`${color} h-3 rounded-full`}
        style={{ width: `${score}%` }}
      />
    </div>
  </div>
);

interface SummaryTileProps {
  title: string;
  value: string | number;
  danger?: boolean;
}

const SummaryTile: React.FC<SummaryTileProps> = ({
  title,
  value,
  danger,
}) => (
  <div className="bg-white rounded-xl shadow p-6">
    <p className="text-sm text-gray-500">{title}</p>

    <h3
      className={`text-2xl font-bold mt-2 ${
        danger ? "text-red-600" : "text-slate-900"
      }`}
    >
      {value}
    </h3>
  </div>
);

export default Analytics;