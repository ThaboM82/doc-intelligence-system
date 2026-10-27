import api from "./api";

export const SecurityService = {
  getThreats: () =>
    api("/security/threats"),

  getQuarantine: () =>
    api("/security/quarantine"),

  runScan: () =>
    api("/security/scan", {
      method: "POST",
    }),
};