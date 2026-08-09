type ThreadMessage = {
  id?: unknown;
  role?: unknown;
};

type ThreadObservation = {
  agentThreadId: string;
  messages: ThreadMessage[];
  selectedThreadId: string;
};

/**
 * Prevents messages briefly retained from the previous CopilotKit thread from
 * promoting a newly selected thread as if those messages belonged to it.
 */
export class ThreadActivityGate {
  private reportedThreadIds = new Set<string>();
  private selectedThreadId: string | undefined;
  private staleFingerprint: string | undefined;

  shouldReport({ agentThreadId, messages, selectedThreadId }: ThreadObservation): boolean {
    const fingerprint = messageFingerprint(messages);
    if (this.selectedThreadId !== selectedThreadId) {
      this.selectedThreadId = selectedThreadId;
      this.staleFingerprint = fingerprint;
      return false;
    }

    if (agentThreadId !== selectedThreadId) {
      return false;
    }

    if (this.staleFingerprint !== undefined) {
      if (fingerprint === this.staleFingerprint) {
        return false;
      }
      this.staleFingerprint = undefined;
    }

    if (messages.length === 0 || this.reportedThreadIds.has(selectedThreadId)) {
      return false;
    }

    this.reportedThreadIds.add(selectedThreadId);
    return true;
  }
}

function messageFingerprint(messages: ThreadMessage[]): string {
  return JSON.stringify(messages.map((message, index) => [message.role, message.id ?? index]));
}
