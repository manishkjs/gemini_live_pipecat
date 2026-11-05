import { Component, type ErrorInfo, type ReactNode } from "react";

interface StudioErrorBoundaryProps {
  readonly children: ReactNode;
}

interface StudioErrorBoundaryState {
  readonly errorMessage: string | null;
}

/** Catches unexpected render errors so malformed runtime state can never blank the studio viewport. */
export class StudioErrorBoundary extends Component<
  StudioErrorBoundaryProps,
  StudioErrorBoundaryState
> {
  override state: StudioErrorBoundaryState = { errorMessage: null };

  static getDerivedStateFromError(error: unknown): StudioErrorBoundaryState {
    return {
      errorMessage: error instanceof Error ? error.message : "Unexpected UI error.",
    };
  }

  override componentDidCatch(error: unknown, info: ErrorInfo): void {
    console.error("VoiceStudio render error:", error, info.componentStack);
  }

  private readonly handleTryAgain = (): void => {
    this.setState({ errorMessage: null });
  };

  private readonly handleResetAndReload = (): void => {
    try {
      const keysToRemove: string[] = [];
      for (let i = 0; i < window.localStorage.length; i++) {
        const key = window.localStorage.key(i);
        if (key && key.startsWith("voice-studio")) {
          keysToRemove.push(key);
        }
      }
      for (const key of keysToRemove) {
        window.localStorage.removeItem(key);
      }
    } catch {
      // Ignore storage access restrictions before reloading.
    }
    window.location.reload();
  };

  override render(): ReactNode {
    if (this.state.errorMessage != null) {
      return (
        <div role="alert" className="studio-error-fallback">
          <div className="studio-error-card">
            <h1 className="studio-error-title">Voice Studio recovered from an error</h1>
            <p className="studio-error-body">{this.state.errorMessage}</p>
            <div className="studio-error-actions">
              <button type="button" className="ghost-btn" onClick={this.handleTryAgain}>
                Try again
              </button>
              <button type="button" className="cta" onClick={this.handleResetAndReload}>
                Reset settings &amp; reload
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
