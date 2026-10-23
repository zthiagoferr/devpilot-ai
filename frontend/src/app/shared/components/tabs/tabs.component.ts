import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  input,
  model,
  viewChildren,
} from '@angular/core';

export interface TabItem {
  readonly id: string;
  readonly label: string;
  readonly disabled?: boolean;
}

/**
 * Tabs following the WAI-ARIA tabs pattern: a single tab stop, automatic
 * activation with Arrow/Home/End, and a labelled tabpanel.
 */
@Component({
  selector: 'app-tabs',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="tabs">
      <div class="tabs__list" role="tablist" [attr.aria-label]="ariaLabel()">
        @for (tab of tabs(); track tab.id; let index = $index) {
          <button
            #tabButton
            type="button"
            role="tab"
            class="tabs__tab"
            [id]="tabId(tab.id)"
            [attr.aria-selected]="tab.id === activeId()"
            [attr.aria-controls]="panelId(tab.id)"
            [attr.tabindex]="tab.id === activeId() ? 0 : -1"
            [disabled]="tab.disabled ?? false"
            (click)="select(tab.id)"
            (keydown)="handleKeydown($event, index)"
          >
            {{ tab.label }}
          </button>
        }
      </div>

      <div
        class="tabs__panel"
        role="tabpanel"
        [id]="panelId(activeId())"
        [attr.aria-labelledby]="tabId(activeId())"
        tabindex="0"
      >
        <ng-content />
      </div>
    </div>
  `,
  styles: `
    .tabs {
      display: flex;
      flex-direction: column;
      gap: 20px;
      min-width: 0;
    }

    .tabs__list {
      display: flex;
      gap: 4px;
      overflow-x: auto;
      overflow-y: hidden;
      border-block-end: 1px solid var(--color-border-soft);
      scrollbar-width: thin;
    }

    .tabs__tab {
      position: relative;
      display: inline-flex;
      align-items: center;
      min-height: 44px;
      padding-inline: 14px;
      border: 0;
      border-radius: var(--radius-sm) var(--radius-sm) 0 0;
      background: transparent;
      color: var(--color-muted);
      font-size: var(--text-body-sm);
      font-weight: 550;
      white-space: nowrap;
      cursor: pointer;
      transition:
        background-color 150ms var(--ease-ui),
        color 150ms var(--ease-ui);
    }

    .tabs__tab::after {
      content: '';
      position: absolute;
      inset-inline: 8px;
      inset-block-end: -1px;
      height: 2px;
      border-radius: 9999px;
      background-color: transparent;
      pointer-events: none;
      transition: background-color 150ms var(--ease-ui);
    }

    .tabs__tab[aria-selected='true'] {
      color: var(--color-text);
    }

    .tabs__tab[aria-selected='true']::after {
      background-color: var(--color-accent);
      box-shadow: 0 0 12px 1px rgb(96 165 250 / 0.55);
    }

    .tabs__tab:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }

    .tabs__tab:focus-visible {
      outline: 2px solid var(--color-accent);
      outline-offset: -2px;
    }

    .tabs__panel {
      min-width: 0;
    }

    .tabs__panel:focus-visible {
      outline: 2px solid var(--color-accent);
      outline-offset: 4px;
      border-radius: var(--radius-sm);
    }

    @media (hover: hover) {
      .tabs__tab:hover:not(:disabled, [aria-selected='true']) {
        background-color: var(--color-surface-sunken);
        color: var(--color-text);
      }
    }
  `,
})
export class TabsComponent {
  readonly tabs = input.required<readonly TabItem[]>();
  readonly activeId = model.required<string>();
  readonly ariaLabel = input('Seções');

  private readonly tabButtons = viewChildren<ElementRef<HTMLButtonElement>>('tabButton');

  protected tabId(id: string): string {
    return `tab-${id}`;
  }

  protected panelId(id: string): string {
    return `panel-${id}`;
  }

  protected select(id: string): void {
    this.activeId.set(id);
  }

  protected handleKeydown(event: KeyboardEvent, index: number): void {
    const tabs = this.tabs();
    let target = -1;

    switch (event.key) {
      case 'ArrowRight':
        target = this.findEnabled(index, 1);
        break;
      case 'ArrowLeft':
        target = this.findEnabled(index, -1);
        break;
      case 'Home':
        target = this.findEnabled(-1, 1);
        break;
      case 'End':
        target = this.findEnabled(tabs.length, -1);
        break;
      case 'Enter':
      case ' ':
        event.preventDefault();
        this.select(tabs[index]?.id ?? this.activeId());
        return;
      default:
        return;
    }

    if (target < 0) {
      return;
    }

    event.preventDefault();
    const targetTab = tabs[target];
    if (!targetTab) {
      return;
    }
    this.activeId.set(targetTab.id);
    queueMicrotask(() => this.tabButtons()[target]?.nativeElement.focus());
  }

  private findEnabled(from: number, step: 1 | -1): number {
    const tabs = this.tabs();
    if (tabs.length === 0) {
      return -1;
    }

    for (let offset = 1; offset <= tabs.length; offset += 1) {
      const next = (from + step * offset + tabs.length * tabs.length) % tabs.length;
      if (!tabs[next]?.disabled) {
        return next;
      }
    }
    return -1;
  }
}
