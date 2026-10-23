import { Injectable, signal } from '@angular/core';

/**
 * Placeholder entry point for the authentication dialog.
 *
 * F5 replaces the modal content with the Firebase form; the detail and shell
 * screens already call this service, so no further wiring will be needed.
 */
@Injectable({ providedIn: 'root' })
export class LoginPromptService {
  private readonly state = signal(false);

  readonly isOpen = this.state.asReadonly();

  open(): void {
    this.state.set(true);
  }

  close(): void {
    this.state.set(false);
  }
}
