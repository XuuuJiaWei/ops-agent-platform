export const SPACES_CHANGED_EVENT = "ops-agent-platform:spaces-changed";

export function notifySpacesChanged() {
  window.dispatchEvent(new CustomEvent(SPACES_CHANGED_EVENT));
}
