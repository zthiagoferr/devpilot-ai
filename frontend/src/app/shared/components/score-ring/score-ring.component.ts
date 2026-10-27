import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

const RADIUS = 52;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

type RingTone = 'success' | 'warning' | 'danger' | 'muted';

@Component({
  selector: 'app-score-ring',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="score-ring"
      [class]="'score-ring score-ring--' + tone()"
      [style.--ring-size]="size() + 'px'"
      role="img"
      [attr.aria-label]="ariaLabel()"
    >
      <svg viewBox="0 0 120 120" aria-hidden="true" focusable="false">
        <circle class="score-ring__track" cx="60" cy="60" [attr.r]="radius" />
        <circle
          class="score-ring__value"
          cx="60"
          cy="60"
          [attr.r]="radius"
          [attr.stroke-dasharray]="circumference"
          [attr.stroke-dashoffset]="dashOffset()"
          transform="rotate(-90 60 60)"
        />
      </svg>

      <div class="score-ring__center" aria-hidden="true">
        <span class="score-ring__number">{{ displayScore() }}</span>
        <span class="score-ring__caption">{{ caption() }}</span>
      </div>
    </div>
  `,
  styles: `
    .score-ring {
      position: relative;
      display: grid;
      place-items: center;
      width: var(--ring-size);
      height: var(--ring-size);
      flex: none;
    }

    svg {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      overflow: visible;
    }

    .score-ring__track,
    .score-ring__value {
      fill: none;
      stroke-width: 8;
    }

    .score-ring__track {
      stroke: #262626;
    }

    .score-ring__value {
      stroke: #8a8a8a;
      stroke-linecap: round;
      transition:
        stroke-dashoffset 600ms var(--ease-ui),
        stroke 150ms var(--ease-ui);
    }

    .score-ring--success .score-ring__value {
      stroke: #fafafa;
      stroke-width: 8;
    }

    .score-ring--warning .score-ring__value {
      stroke: #a3a3a3;
      stroke-width: 8;
    }

    .score-ring--danger .score-ring__value {
      stroke: #fafafa;
      stroke-width: 10;
      stroke-linecap: butt;
    }

    .score-ring--danger .score-ring__number {
      font-weight: 700;
    }

    .score-ring__center {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 2px;
      color: var(--color-text);
    }

    .score-ring__number {
      font-family: var(--font-mono);
      font-variant-numeric: tabular-nums;
      font-size: calc(var(--ring-size) * 0.27);
      font-weight: 600;
      line-height: 1;
      letter-spacing: -0.02em;
    }

    .score-ring__caption {
      color: var(--color-muted);
      font-size: var(--text-caption);
      line-height: 1.2;
    }

    @media (prefers-reduced-motion: reduce) {
      .score-ring__value {
        transition: none;
      }
    }
  `,
})
export class ScoreRingComponent {
  readonly score = input<number | null>(null);
  readonly size = input(112);
  readonly caption = input('score');

  protected readonly radius = RADIUS;
  protected readonly circumference = CIRCUMFERENCE;

  protected readonly normalized = computed(() => {
    const value = this.score();
    if (value === null || !Number.isFinite(value)) {
      return null;
    }
    return Math.max(0, Math.min(100, Math.round(value)));
  });

  protected readonly displayScore = computed(() => {
    const value = this.normalized();
    return value === null ? '—' : String(value);
  });

  protected readonly tone = computed<RingTone>(() => {
    const value = this.normalized();
    if (value === null) {
      return 'muted';
    }
    if (value >= 80) {
      return 'success';
    }
    if (value >= 60) {
      return 'warning';
    }
    return 'danger';
  });

  protected readonly dashOffset = computed(() => {
    const value = this.normalized() ?? 0;
    return CIRCUMFERENCE * (1 - value / 100);
  });

  protected readonly ariaLabel = computed(() => {
    const value = this.normalized();
    return value === null ? 'Score indisponível' : `Score ${value} de 100`;
  });
}
