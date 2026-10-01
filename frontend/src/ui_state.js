const COMMAND_MESSAGES = {
  pending: "Befehl wird an die Kühlbox übertragen…",
  acknowledged: "Befehl wurde an die Kühlbox weitergegeben.",
  failed: "Befehl konnte nicht gesendet werden.",
  timed_out: "Keine Bestätigung von der Kühlbox erhalten.",
};


export function commandStatusMessage(status) {
  return COMMAND_MESSAGES[status] || "Status des Befehls ist unbekannt.";
}


export function renderCommandStatus(element, status) {
  element.textContent = commandStatusMessage(status);
  element.setAttribute("aria-live", "polite");
  element.dataset.status = status;
}


export function setAuthenticationView(authElement, dashboardElement, accountElement, authenticated) {
  authElement.hidden = authenticated;
  dashboardElement.hidden = !authenticated;
  accountElement.hidden = !authenticated;
}