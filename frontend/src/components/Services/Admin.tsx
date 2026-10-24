import apiClient from "./api";

export async function getDashboard() {
  return apiClient.get(
    "/api/v1/admin/dashboard"
  );
}

export async function threatScan(
  payload: {
    text: string;
    use_ai: boolean;
  }
) {
  return apiClient.post(
    "/api/v1/admin/threat-scan",
    payload
  );
}