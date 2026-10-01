import { fetchAuthSession } from "aws-amplify/auth";


export class AuthenticationRequiredError extends Error {
  constructor() {
    super("Bitte zuerst anmelden.");
    this.name = "AuthenticationRequiredError";
  }
}


export class ApiError extends Error {
  constructor(status, message, details = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}


export function createApi({
  baseUrl,
  getIdToken = getCognitoIdToken,
  fetchImpl = globalThis.fetch,
}) {
  const request = async (path, options = {}) => {
    const token = await getIdToken();
    if (!token) throw new AuthenticationRequiredError();
    if (!baseUrl) throw new Error("API-Adresse ist nicht konfiguriert.");

    const headers = {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      ...options.headers,
    };
    const requestOptions = {
      method: options.method || "GET",
      headers,
    };
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      requestOptions.body = JSON.stringify(options.body);
    }

    const response = await fetchImpl(
      `${baseUrl.replace(/\/+$/, "")}${path}`,
      requestOptions,
    );
    let payload = {};
    try {
      payload = await response.json();
    } catch (_error) {
      payload = {};
    }
    if (!response.ok) {
      throw new ApiError(
        response.status,
        payload.error || "Cloud-Anfrage fehlgeschlagen.",
        payload,
      );
    }
    return payload;
  };

  return {
    request,
    getTemperatures: (hours = 24) =>
      request(`/api/temperatures?hours=${encodeURIComponent(hours)}`),
    getDrive: () => request("/api/drive"),
    startDrive: () => request("/api/drive/start", { method: "POST", body: {} }),
    stopDrive: () => request("/api/drive/stop", { method: "POST", body: {} }),
    setFan: (value) => request("/api/actuators/fan", { method: "POST", body: { value } }),
    setFlap: (value) => request("/api/actuators/flap", { method: "POST", body: { value } }),
    getCommand: (requestId) =>
      request(`/api/commands/${encodeURIComponent(requestId)}`),
  };
}


export async function getCognitoIdToken() {
  const session = await fetchAuthSession();
  return session.tokens?.idToken?.toString() || null;
}


export const api = createApi({
  baseUrl: import.meta.env.VITE_API_URL || "",
});