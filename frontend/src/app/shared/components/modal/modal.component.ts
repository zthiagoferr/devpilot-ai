import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  effect,
  input,
  model,
  output,
  viewChild,
} from '@angular/core';

let dialogSequence = 0;

/**
 * Accessible modal built on the native `<dialog>` element.
 * `showModal()` supplies the top layer and inert background; this component
 * adds initial focus, focus return to the trigger, Escape handling (native)
 * and a body scroll lock.
 */
@Component({
  selector: 'app-modal',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <dialog
      #dialog
      class="modal"
      aria-modal="true"
      [attr.aria-labelledby]="titleId"
      (cancel)="handleCancel($event)"
      (close)="handleClose()"
      (click)="handleBackdrop($event)"
    >
      <div #panel class="modal__panel" tabindex="-1" (click)="stopPropagation($event)">
        <header class="modal__header">
          <div class="modal__heading">
            <h2 class="modal__title" [id]="titleId">{{ title() }}</h2>
            @if (description()) {
              <p class="modal__description">{{ description() }}</p>
            }
          </div>
          <button type="button" class="modal__close" aria-label="Fechar janela" (click)="close()">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
              <path d="M18 6 6 18" />
              <path d="M6 6l12 12" />
            </svg>
          </button>
        </header>

        <div class="modal__body">
          <ng-content />
        </div>

        <footer class="modal__footer">
          <ng-content select="[modalFooter]" />
        </footer>
      </div>
    </dialog>
  `,
  styles: `
    .modal {
      width: min(560px, calc(100vw - 32px));
      max-width: 560px;
      max-height: calc(100dvh - 32px);
      margin: auto;
      padding: 0;
      border: 0;
      background: transparent;
      color: var(--color-text);
    }

    .modal::backdrop {
      background-color: rgb(4 6 10 / 0.72);
      backdrop-filter: blur(2px);
    }

    .modal__panel {
      display: flex;
      flex-direction: column;
      gap: 16px;
      max-height: calc(100dvh - 32px);
      overflow-y: auto;
      padding: 24px;
      border: 1px solid var(--color-border);
      border-radius: var(--radius-xl);
      background-color: var(--color-surface);
      box-shadow: 0 32px 80px -32px rgb(0 0 0 / 0.85);
    }

    .modal__panel:focus-visible {
      outline: 2px solid var(--color-accent);
      outline-offset: 4px;
    }

    .modal__header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
    }

    .modal__heading {
      display: flex;
      flex-direction: column;
      gap: 4px;
      min-width: 0;
    }

    .modal__title {
      color: var(--color-text);
      font-size: var(--text-title);
      line-height: 1.2;
      letter-spacing: -0.01em;
    }

    .modal__description {
      color: var(--color-muted);
      font-size: var(--text-body-sm);
    }

    .modal__close {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 44px;
      height: 44px;
      flex: none;
      margin: -8px -8px 0 0;
      border: 1px solid transparent;
      border-radius: var(--radius-md);
      background: transparent;
      color: var(--color-muted);
      cursor: pointer;
      transition:
        background-color 150ms var(--ease-ui),
        color 150ms var(--ease-ui);
    }

    .modal__body {
      color: var(--color-text);
      font-size: var(--text-body-sm);
      line-height: 1.55;
    }

    .modal__footer {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 8px;
    }

    .modal__footer:empty {
      display: none;
    }

    @media (hover: hover) {
      .modal__close:hover {
        background-color: var(--color-surface-raised);
        color: var(--color-text);
      }
    }

    .modal[open] .modal__panel {
      animation: modal-in 180ms var(--ease-ui) both;
    }

    @media (prefers-reduced-motion: reduce) {
      .modal[open] .modal__panel {
        animation: none;
      }
    }

    @keyframes modal-in {
      from {
        opacity: 0;
        transform: translateY(8px) scale(0.98);
      }

      to {
        opacity: 1;
        transform: translateY(0) scale(1);
      }
    }
  `,
})
export class ModalComponent {
  readonly title = input.required<string>();
  readonly description = input('');
  readonly opened = model(false);

  readonly closed = output<void>();

  protected readonly titleId = `modal-title-${(dialogSequence += 1)}`;

  private readonly dialogRef = viewChild<ElementRef<HTMLDialogElement>>('dialog');
  private readonly panelRef = viewChild<ElementRef<HTMLElement>>('panel');
  private previousFocus: HTMLElement | null = null;

  constructor() {
    effect(() => {
      const dialog = this.dialogRef()?.nativeElement;
      if (!dialog) {
        return;
      }

      if (this.opened() && !dialog.open) {
        this.previousFocus =
          document.activeElement instanceof HTMLElement ? document.activeElement : null;
        dialog.showModal();
        queueMicrotask(() => this.panelRef()?.nativeElement.focus());
      } else if (!this.opened() && dialog.open) {
        dialog.close();
      }
    });

    effect((onCleanup) => {
      if (!this.opened()) {
        return;
      }
      const previousOverflow = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
      onCleanup(() => {
        document.body.style.overflow = previousOverflow;
      });
    });
  }

  protected close(): void {
    this.opened.set(false);
  }

  protected handleCancel(event: Event): void {
    // The native dialog closes on Escape; keep the Angular state in sync.
    event.preventDefault();
    this.close();
  }

  protected handleClose(): void {
    if (this.opened()) {
      this.opened.set(false);
    }
    this.previousFocus?.focus();
    this.previousFocus = null;
    this.closed.emit();
  }

  protected handleBackdrop(event: MouseEvent): void {
    if (event.target === this.dialogRef()?.nativeElement) {
      this.close();
    }
  }

  protected stopPropagation(event: MouseEvent): void {
    event.stopPropagation();
  }
}
