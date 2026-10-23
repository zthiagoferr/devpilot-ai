import { ChangeDetectionStrategy, Component } from '@angular/core';

import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';

@Component({
  selector: 'app-analysis-new',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [EmptyStateComponent],
  template: `
    <div class="flex flex-col gap-8">
      <header class="flex flex-col gap-3">
        <h1 class="text-display font-semibold tracking-[-0.02em] text-text">Nova análise</h1>
        <p class="max-w-[62ch] text-body text-muted">
          Cole o código para receber score, problemas priorizados e um resumo dos agentes.
        </p>
      </header>

      <app-empty-state
        title="Formulário em preparação"
        description="O envio de análise manual está sendo conectado à API."
      />
    </div>
  `,
})
export class AnalysisNewComponent {}
