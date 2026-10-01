const sensors = [
  { id: "arduino_sensor_marten", key: "marten", label: "Marten", color: "#df5b37" },
  { id: "arduino_sensor_andor", key: "andor", label: "Andor", color: "#16718b" },
  { id: "arduino_sensor_luis", key: "luis", label: "Luis", color: "#668843" },
];

const state = {
  hours: 24,
  chart: null,
  loading: false,
};

const chartState = document.querySelector("#chart-state");
const connectionLabel = document.querySelector("#connection-label");
const refreshLabel = document.querySelector("#refresh-label");
const statusDot = document.querySelector("#status-dot");

function formatTemperature(value) {
  return `${Number(value).toFixed(1)}<span>°C</span>`;
}

function formatTime(value) {
  return new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
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

    valueElement.innerHTML = formatTemperature(reading.value);
    timeElement.textContent = formatTime(reading.timestamp);
    timeElement.dateTime = reading.timestamp;
  });
}

function makeDatasets(series) {
  return sensors.map((sensor) => ({
    label: sensor.label,
    data: (series[sensor.id] || [])
      .map((point) => ({
        x: Date.parse(point.timestamp),
        y: point.value,
      }))
      .filter((point) => Number.isFinite(point.x))
      .sort((left, right) => left.x - right.x),
    borderColor: sensor.color,
    backgroundColor: sensor.color,
    borderWidth: 2,
    pointRadius: 0,
    pointHoverRadius: 4,
    tension: 0.22,
  }));
}

function updateChart(series) {
  const datasets = makeDatasets(series);
  const hasData = datasets.some((dataset) => dataset.data.length > 0);

  if (!hasData) {
    chartState.textContent = "Für diesen Zeitraum liegen keine Messwerte vor.";
    chartState.classList.remove("hidden");
  } else {
    chartState.classList.add("hidden");
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
      animation: { duration: 350 },
      plugins: {
        legend: {
          align: "start",
          labels: { usePointStyle: true, boxWidth: 8, boxHeight: 8 },
        },
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
          ticks: {
            callback: (value) => formatTime(value),
            maxTicksLimit: 8,
            maxRotation: 0,
          },
        },
        y: {
          grid: { color: "rgba(29, 39, 41, 0.08)" },
          ticks: { callback: (value) => `${value} °C` },
        },
      },
    },
  });
}

function setStatus(mode, title, detail) {
  statusDot.className = `status-dot ${mode}`;
  connectionLabel.textContent = title;
  refreshLabel.textContent = detail;
}

async function postControl(endpoint, payload) {
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(`Control request failed: ${response.status}`);
  }

  return response.json();
}

document.querySelectorAll("[data-drive]").forEach((button) => {
  button.addEventListener("click", async () => {
    try {
      await postControl(`/api/drive/${button.dataset.drive}`, {});
      setStatus("online", "Steuerung", `Fahrt ${button.dataset.drive}`);
    } catch (_error) {
      setStatus("error", "Steuerung fehlerhaft", "Befehl konnte nicht gesendet werden");
    }
  });
});

const fanSlider = document.querySelector("#fan-slider");
const flapSlider = document.querySelector("#flap-slider");
const fanValue = document.querySelector("#fan-value");
const flapValue = document.querySelector("#flap-value");

function bindSlider(slider, label, endpoint) {
  slider.addEventListener("input", () => {
    label.textContent = slider.value;
  });

  slider.addEventListener("change", async () => {
    try {
      await postControl(endpoint, { value: Number(slider.value) });
      setStatus("online", "Steuerung", `${endpoint}=${slider.value}`);
    } catch (_error) {
      setStatus("error", "Steuerung fehlerhaft", "Befehl konnte nicht gesendet werden");
    }
  });
}

bindSlider(fanSlider, fanValue, "/api/actuators/fan");
bindSlider(flapSlider, flapValue, "/api/actuators/flap");

async function refreshData() {
  if (state.loading) return;
  state.loading = true;

  try {
    const response = await fetch(`/api/temperatures?hours=${state.hours}`, {
      cache: "no-store",
    });
    if (!response.ok) throw new Error("request failed");

    const payload = await response.json();
    updateLatest(payload.latest);
    updateChart(payload.series);
    setStatus("online", "Live", `Aktualisiert ${new Date().toLocaleTimeString("de-DE")}`);
  } catch (_error) {
    chartState.textContent = "Messdaten sind gerade nicht erreichbar.";
    chartState.classList.remove("hidden");
    setStatus("error", "Verbindung gestört", "Nächster Versuch in 10 Sekunden");
  } finally {
    state.loading = false;
  }
}

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

refreshData();
setInterval(refreshData, 10_000);