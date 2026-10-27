import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type SkeletonVariant = 'text' | 'block' | 'circle';

@Component({
  selector: 'app-skeleton',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span class="skeleton__label sr-only">{{ label() }}</span>
    <div class="skeleton__body" [class]="bodyClass()" aria-hidden="true">
      @for (line of lineItems(); track $index) {
        <span [class]="'skeleton__shape skeleton__shape--' + variant()"></span>
      }
    </div>
  `,
  styles: `
    :host {
      display: block;
    }

    .skeleton__body {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .skeleton__body--text .skeleton__shape--text:last-child {
      width: 68%;
    }

    .skeleton__shape {
      display: block;
      width: 100%;
      border-radius: var(--radius-sm);
      background: linear-gradient(
        90deg,
        #1a1a1a 0%,
        #262626 50%,
        #1a1a1a 100%
      );
      background-size: 200% 100%;
      animation: shimmer 1.6s var(--ease-ui) infinite;
    }

    .skeleton__shape--text {
      height: 12px;
    }

    .skeleton__shape--block {
      height: 96px;
      border-radius: var(--radius-md);
    }

    .skeleton__shape--circle {
      width: 40px;
      height: 40px;
      border-radius: 9999px;
    }

    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }

    @media (prefers-reduced-motion: reduce) {
      .skeleton__shape {
        animation: none;
        background: #1f1f1f;
      }
    }

    @keyframes shimmer {
      to {
        background-position: -200% 0;
      }
    }
  `,
})
export class SkeletonComponent {
  readonly variant = input<SkeletonVariant>('text');
  readonly lines = input(3);
  readonly label = input('Carregando conteúdo');

  protected readonly lineItems = computed(() => Array.from({ length: Math.max(1, this.lines()) }));

  protected bodyClass(): string {
    return `skeleton__body skeleton__body--${this.variant()}`;
  }
}
