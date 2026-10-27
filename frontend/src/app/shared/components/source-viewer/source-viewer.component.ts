import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';

import { ButtonComponent } from '../button/button.component';
import { InlineStatusComponent } from '../inline-status/inline-status.component';

const DEFAULT_LIMIT = 150_000;

@Component({
  selector: 'app-source-viewer',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ButtonComponent, InlineStatusComponent],
  template: `
    <div class="source">
      <div class="source__toolbar">
        <p class="source__meta">
          <span class="mono-metric">{{ lineCount() }}</span> linhas ·
          <span class="mono-metric">{{ sizeLabel() }}</span>
        </p>

        @if (truncated()) {
          <app-button size="sm" variant="ghost" (click)="toggle()">
            {{ expanded() ? 'Mostrar menos' : 'Mostrar mais' }}
          </app-button>
        }
      </div>

      @if (truncated() && !expanded()) {
        <app-inline-status
          tone="info"
          [message]="
            'Exibindo os primeiros ' +
            limitLabel() +
            ' de ' +
            sizeLabel() +
            '. O conteúdo completo está disponível ao expandir.'
          "
        />
      }

      <pre
        class="source__code"
        tabindex="0"
        aria-label="Código-fonte da análise"
      ><code>{{ visibleSource() }}</code></pre>
    </div>
  `,
  styles: `
    .source {
      display: flex;
      flex-direction: column;
      gap: 12px;
      min-width: 0;
    }

    .source__toolbar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }

    .source__meta {
      color: #a3a3a3;
      font-size: var(--text-caption);
    }

    .source__code {
      max-height: 520px;
      margin: 0;
      padding: 16px;
      overflow: auto;
      border: 1px solid #262626;
      border-radius: var(--radius-md);
      background-color: #080808;
      color: #fafafa;
      font-size: 0.8125rem;
      line-height: 1.65;
      tab-size: 4;
      white-space: pre;
      overscroll-behavior: contain;
    }

    .source__code:focus-visible {
      outline: 2px solid #fafafa;
      outline-offset: 2px;
    }
  `,
})
export class SourceViewerComponent {
  readonly source = input.required<string>();
  readonly limit = input(DEFAULT_LIMIT);

  protected readonly expanded = signal(false);

  protected readonly truncated = computed(() => this.source().length > this.limit());

  protected readonly visibleSource = computed(() => {
    const source = this.source();
    if (this.expanded() || !this.truncated()) {
      return source;
    }
    return source.slice(0, this.limit());
  });

  protected readonly lineCount = computed(() => {
    const source = this.source();
    return source === '' ? 0 : source.split('\n').length;
  });

  protected readonly sizeLabel = computed(() => this.formatBytes(byteLength(this.source())));

  protected readonly limitLabel = computed(() => this.formatBytes(this.limit()));

  protected toggle(): void {
    this.expanded.update((value) => !value);
  }

  private formatBytes(bytes: number): string {
    if (bytes < 1024) {
      return `${bytes} B`;
    }
    if (bytes < 1024 * 1024) {
      return `${(bytes / 1024).toFixed(1)} KB`;
    }
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
}

function byteLength(value: string): number {
  return new TextEncoder().encode(value).length;
}
