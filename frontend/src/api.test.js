// @vitest-environment jsdom

import { describe, expect, it, vi } from "vitest";
import { AuthenticationRequiredError, ApiError, createApi } from "./api.js";
import {
  commandStatusMessage,
  renderCommandStatus,
  setAuthenticationView,
} from "./ui_state.js";


describe("createApi", () => {
  it("sends the Cognito ID token to the configured API", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ hours: 24 }));
    const api = createApi({
      baseUrl: "https://api.example.test",
      getIdToken: async () => "cognito-id-token",
      fetchImpl,
    });

    await api.getTemperatures(24);

    expect(fetchImpl).toHaveBeenCalledWith(
      "https://api.example.test/api/temperatures?hours=24",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer cognito-id-token",
        }),
      }),
    );
  });

  it("does not call the API without an authenticated token", async () => {
    const fetchImpl = vi.fn();
    const api = createApi({
      baseUrl: "https://api.example.test",
      getIdToken: async () => null,
      fetchImpl,
    });

    await expect(api.getDrive()).rejects.toBeInstanceOf(AuthenticationRequiredError);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("returns structured errors from non-success responses", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({ error: "Ungültiger Wert" }, 400),
    );
    const api = createApi({
      baseUrl: "https://api.example.test",
      getIdToken: async () => "token",
      fetchImpl,
    });

    await expect(api.setFan(999)).rejects.toMatchObject({
      constructor: ApiError,
      status: 400,
      message: "Ungültiger Wert",
    });
  });
});

describe("commandStatusMessage", () => {
  it.each([
    ["pending", "Befehl wird an die Kühlbox übertragen…"],
    ["acknowledged", "Befehl wurde an die Kühlbox weitergegeben."],
    ["failed", "Befehl konnte nicht gesendet werden."],
    ["timed_out", "Keine Bestätigung von der Kühlbox erhalten."],
  ])("describes %s command state", (status, expected) => {
    expect(commandStatusMessage(status)).toBe(expected);
  });

  it("renders command status as live text", () => {
    const element = document.createElement("p");
    renderCommandStatus(element, "acknowledged");

    expect(element.textContent).toBe("Befehl wurde an die Kühlbox weitergegeben.");
    expect(element.getAttribute("aria-live")).toBe("polite");
  });

  it("hides dashboard controls until the user is authenticated", () => {
    const auth = document.createElement("section");
    const dashboard = document.createElement("section");
    const account = document.createElement("div");

    setAuthenticationView(auth, dashboard, account, false);

    expect(auth.hidden).toBe(false);
    expect(dashboard.hidden).toBe(true);
    expect(account.hidden).toBe(true);

    setAuthenticationView(auth, dashboard, account, true);
    expect(auth.hidden).toBe(true);
    expect(dashboard.hidden).toBe(false);
    expect(account.hidden).toBe(false);
  });
});


function jsonResponse(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  };
}