import { Amplify } from "aws-amplify";
import {
  confirmSignIn,
  fetchAuthSession,
  getCurrentUser,
  signIn,
  signOut,
} from "aws-amplify/auth";
import Chart from "chart.js/auto";

import { api } from "./api.js";
import "../../src/mobilefrost/static/dashboard.css";
import "./style.css";
import { renderCommandStatus, setAuthenticationView } from "./ui_state.js";


const sensors = [
  { id: "arduino_sensor_marten", key: "marten", label: "Marten", color: "#df5b37" },
  { id: "arduino_sensor_andor", key: "andor", label: "Andor", color: "#16718b" },
  { id: "arduino_sensor_luis", key: "luis", label: "Luis", color: "#668843" },
];

const state = { hours: 24, chart: null, refreshTimer: null, signingIn: false };
const configuration = import.meta.env;
const requiredConfiguration = [
  "VITE_API_URL",
  "VITE_AWS_REGION",
  "VITE_COGNITO_USER_POOL_ID",
  "VITE_COGNITO_USER_POOL_CLIENT_ID",
];
const missingConfiguration = requiredConfiguration.filter((key) => !configuration[key]);

const authSection = document.querySelector("#auth-section");
const dashboardView = document.querySelector("#dashboard-view");
const loginForm = document.querySelector("#login-form");
const authMessage = document.querySelector("#auth-message");
const loginSubmit = document.querySelector("#login-submit");
const newPasswordRow = document.querySelector("#new-password-row");
const accountTools = document.querySelector("#account-tools");
const chartState = document.querySelector("#chart-state");
const connectionLabel = document.querySelector("#connection-label");
const refreshLabel = document.querySelector("#refresh-label");
const statusDot = document.querySelector("#status-dot");
const driveState = document.querySelector("#drive-state");
const driveMessage = document.querySelector("#drive-message");
const actuatorMessage = document.querySelector("#actuator-message");


function configureAmplify() {
  if (missingConfiguration.length) {
    authMessage.textContent = "Cloud-Anmeldung ist noch nicht konfiguriert.";
    loginSubmit.disabled = true;
    return false;
  }

  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: configuration.VITE_COGNITO_USER_POOL_ID,
        userPoolClientId: configuration.VITE_COGNITO_USER_POOL_CLIENT_ID,
        loginWith: { email: true },
      },
    },
  });
  return true;
}


function showSignedOut(message = "") {
  setAuthenticationView(authSection, dashboardView, accountTools, false);
  authMessage.textContent = message;
  if (state.refreshTimer) window.clearInterval(state.refreshTimer);
  state.refreshTimer = null;
  state.chart?.destroy();
  state.chart = null;
}


async function showSignedIn(username) {
  setAuthenticationView(authSection, dashboardView, accountTools, true);
  document.querySelector("#account-label").textContent = username;
  await Promise.all([refreshData(), refreshDrive()]);
  if (!state.refreshTimer) {
    state.refreshTimer = window.setInterval(() => {
      refreshData();
      refreshDrive();
    }, 10_000);
  }
}


async function handleLogin(event) {
  event.preventDefault();
  if (state.signingIn) return;
  state.signingIn = true;
  loginSubmit.disabled = true;
  authMessage.textContent = "";

  try {
    let result;
    if (newPasswordRow.hidden) {
      const formData = new FormData(loginForm);
      result = await signIn({
        username: formData.get("email"),
        password: formData.get("password"),
      });
      if (result.nextStep.signInStep === "CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED") {
        newPasswordRow.hidden = false;
        document.querySelector("#new-password").required = true;
        loginSubmit.textContent = "Passwort bestätigen";
        authMessage.textContent = "Bitte neues Passwort festlegen.";
        return;
      }
    } else {
      result = await confirmSignIn({
        challengeResponse: document.querySelector("#new-password").value,
      });
    }

    if (!result.isSignedIn) {
      authMessage.textContent = "Weitere Anmeldungsschritte sind erforderlich.";
      return;
    }
    const user = await getCurrentUser();
    await showSignedIn(user.username || user.userId);
  } catch (error) {
    authMessage.textContent = error.message || "Anmeldung fehlgeschlagen.";
  } finally {
    state.signingIn = false;
    loginSubmit.disabled = false;
  }
}


async function refreshData() {
  try {
    const payload = await api.getTemperatures(state.hours);
    updateLatest(payload.latest || {});
    updateChart(payload.series || {});
    setConnection("online", "Cloud verbunden", `Aktualisiert ${new Date().toLocaleTimeString("de-DE")}`);
  } catch (error) {
    chartState.textContent = "Cloud-Messdaten sind gerade nicht erreichbar.";
    chartState.classList.remove("hidden");
    setConnection("error", "Verbindung gestört", error.message || "Nächster Versuch in 10 Sekunden");
  }
}


async function refreshDrive() {
  try {
    const payload = await api.getDrive();
    const active = payload.active;
    driveState.textContent = active
      ? `Aktiv seit ${formatTime(active.started_at)}`
      : "Keine aktive Fahrt";
    document.querySelector("#drive-start").disabled = Boolean(active);
    document.querySelector("#drive-stop").disabled = !active;
  } catch (error) {
    driveMessage.textContent = error.message || "Fahrtstatus nicht erreichbar.";
    document.querySelector("#drive-start").disabled = true;
    document.querySelector("#drive-stop").disabled = true;
  }
}


async function changeDrive(action) {
  const button = document.querySelector(`#drive-${action}`);
  button.disabled = true;
  driveMessage.textContent = "";
  try {
    if (action === "start") await api.startDrive();
    else await api.stopDrive();
    driveMessage.textContent = action === "start" ? "Fahrt gestartet." : "Fahrt beendet.";
  } catch (error) {
    driveMessage.textContent = error.message || "Fahrt konnte nicht geändert werden.";
  } finally {
    await refreshDrive();
  }
}


async function changeActuator(kind, value) {
  renderCommandStatus(actuatorMessage, "pending");
  try {
    const command = kind === "fan" ? await api.setFan(value) : await api.setFlap(value);
    await pollCommand(command.request_id);
  } catch (error) {
    actuatorMessage.textContent = error.message || "Befehl konnte nicht gesendet werden.";
    actuatorMessage.dataset.status = "failed";
  }
}


async function pollCommand(requestId) {
  for (let attempt = 0; attempt < 32; attempt += 1) {
    const command = await api.getCommand(requestId);
    renderCommandStatus(actuatorMessage, command.status);
    if (command.status !== "pending") return;
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
  }
  renderCommandStatus(actuatorMessage, "timed_out");
}


function updateLatest(latest) {
  sensors.forEach((sensor) => {
    const reading = latest[sensor.id];
    const valueElement = document.querySelector(`#value-${sensor.key}`);
    const timeElement = document.querySelector(`#time-${sensor.key}`);
    if (!reading) {
      valueElement.innerHTML = "--.-<span>°C</span>";
      timeElement.textContent = "Keine Messung";
      return;
    }
    valueElement.innerHTML = `${Number(reading.value).toFixed(1)}<span>°C</span>`;
    timeElement.textContent = formatTime(reading.timestamp);
    timeElement.dateTime = reading.timestamp;
  });
}


function updateChart(series) {
  const datasets = sensors.map((sensor) => ({
    label: sensor.label,
    data: (series[sensor.id] || []).map((point) => ({
      x: Date.parse(point.timestamp),
      y: Number(point.value),
    })).filter((point) => Number.isFinite(point.x)),
    borderColor: sensor.color,
    backgroundColor: sensor.color,
    borderWidth: 2,
    pointRadius: 0,
    pointHoverRadius: 4,
    tension: 0.22,
  }));
  const hasData = datasets.some((dataset) => dataset.data.length);

  if (hasData) chartState.classList.add("hidden");
  else {
    chartState.textContent = "Für diesen Zeitraum liegen keine Messwerte vor.";
    chartState.classList.remove("hidden");
  }

  if (state.chart) {
    state.chart.data.datasets = datasets;
    state.chart.update("none");
    return;
  }

  state.chart = new Chart(document.querySelector("#temperature-chart"), {
    type: "line",
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "nearest", intersect: false },
      plugins: {
        legend: { align: "start", labels: { usePointStyle: true, boxWidth: 8, boxHeight: 8 } },
        tooltip: {
          callbacks: {
            title: (items) => formatTime(items[0].parsed.x),
            label: (context) => `${context.dataset.label}: ${context.parsed.y.toFixed(1)} °C`,
          },
        },
      },
      scales: {
        x: {
          type: "linear",
          grid: { display: false },
          ticks: { callback: (value) => formatTime(value), maxTicksLimit: 8, maxRotation: 0 },
        },
        y: { grid: { color: "rgba(29, 39, 41, 0.08)" }, ticks: { callback: (value) => `${value} °C` } },
      },
    },
  });
}


function setConnection(mode, title, detail) {
  statusDot.className = `status-dot ${mode}`;
  connectionLabel.textContent = title;
  refreshLabel.textContent = detail;
}


function formatTime(value) {
  const timestamp = new Date(value);
  if (!Number.isFinite(timestamp.getTime())) return "Zeit unbekannt";
  return new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(timestamp);
}


function bindControls() {
  document.querySelectorAll("[data-hours]").forEach((button) => {
    button.addEventListener("click", () => {
      state.hours = Number(button.dataset.hours);
      document.querySelectorAll("[data-hours]").forEach((candidate) => {
        const active = candidate === button;
        candidate.classList.toggle("active", active);
        candidate.setAttribute("aria-pressed", String(active));
      });
      chartState.textContent = "Messwerte werden geladen…";
      chartState.classList.remove("hidden");
      refreshData();
    });
  });

  document.querySelector("#drive-start").addEventListener("click", () => changeDrive("start"));
  document.querySelector("#drive-stop").addEventListener("click", () => changeDrive("stop"));
  bindSlider("fan", "#fan-slider", "#fan-value");
  bindSlider("flap", "#flap-slider", "#flap-value");
}


function bindSlider(kind, sliderSelector, valueSelector) {
  const slider = document.querySelector(sliderSelector);
  const label = document.querySelector(valueSelector);
  const suffix = kind === "flap" ? "°" : "";
  slider.addEventListener("input", () => {
    label.textContent = `${slider.value}${suffix}`;
  });
  slider.addEventListener("change", () => changeActuator(kind, Number(slider.value)));
}


async function initialize() {
  if (!configureAmplify()) return;
  bindControls();
  loginForm.addEventListener("submit", handleLogin);
  document.querySelector("#sign-out").addEventListener("click", async () => {
    await signOut();
    showSignedOut();
  });

  try {
    const user = await getCurrentUser();
    const session = await fetchAuthSession();
    if (session.tokens?.idToken) await showSignedIn(user.username || user.userId);
    else showSignedOut();
  } catch (_error) {
    showSignedOut();
  }
}


initialize();