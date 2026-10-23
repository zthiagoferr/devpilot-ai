import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type CardPadding = 'none' | 'sm' | 'md' | 'lg';
export type CardTone = 'default' | 'raised' | 'sunken';

@Component({
  selector: 'app-card',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section [class]="cardClass()">
      <ng-content />
    </section>
  `,
  styles: `
    :host {
      display: block;
    }

    .card {
      min-width: 0;
      background-color: var(--color-surface);
      border: 1px solid var(--color-border-soft);
      border-radius: var(--radius-lg);
      box-shadow: var(--shadow-panel);
    }

    .card--raised {
      background-color: var(--color-surface-raised);
    }

    .card--sunken {
      background-color: var(--color-surface-sunken);
    }

    .card--none {
      padding: 0;
    }

    .card--sm {
      padding: 16px;
    }

    .card--md {
      padding: 24px;
    }

    .card--lg {
      padding: 32px;
    }

    @media (max-width: 639px) {
      .card--lg {
        padding: 24px;
      }
    }
  `,
})
export class CardComponent {
  readonly padding = input<CardPadding>('md');
  readonly tone = input<CardTone>('default');

  protected readonly cardClass = computed(
    () => `card card--${this.padding()} card--${this.tone()}`,
  );
}
