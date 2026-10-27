import api from "./api";

export const AnalyticsService = {
  getOverview: () =>
    api("/analytics"),

  getTrends: () =>
    api("/analytics/trends"),

  getUsage: () =>
    api("/analytics/usage"),
};