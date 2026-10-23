import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';

@Component({
  selector: 'app-analysis-detail',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [EmptyStateComponent],
  template: `
    <div class="flex flex-col gap-8">
      <header class="flex flex-col gap-3">
        <h1 class="text-display font-semibold tracking-[-0.02em] text-text">Detalhe da análise</h1>
        <p class="text-body-sm text-muted">Identificador <code class="mono-metric">{{ id() }}</code></p>
      </header>

      <app-empty-state
        title="Detalhe em preparação"
        description="O relatório completo será exibido aqui."
      />
    </div>
  `,
})
export class AnalysisDetailComponent {
  readonly id = input.required<string>();
}
