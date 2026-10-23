import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { Router } from '@angular/router';

import { ButtonComponent } from '../../shared/components/button/button.component';
import { CardComponent } from '../../shared/components/card/card.component';
import { IconComponent } from '../../shared/components/icon/icon.component';

@Component({
  selector: 'app-overview',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ButtonComponent, CardComponent, IconComponent],
  templateUrl: './overview.component.html',
  styleUrl: './overview.component.css',
})
export class OverviewComponent {
  private readonly router = inject(Router);

  protected readonly stats = [
    { label: 'Análises salvas', hint: 'Disponível ao entrar' },
    { label: 'Score médio', hint: 'Calculado do histórico' },
    { label: 'Última análise', hint: 'Nenhuma ainda' },
  ];

  protected readonly steps = [
    {
      title: 'Envie o código',
      description: 'Cole o arquivo ou selecione um repositório na etapa de integração.',
    },
    {
      title: 'Agentes analisam',
      description: 'Código, testes e documentação são avaliados em paralelo.',
    },
    {
      title: 'Receba o relatório',
      description: 'Score, problemas priorizados e um resumo com próximos passos.',
    },
  ];

  protected startAnalysis(): void {
    void this.router.navigate(['/analysis/new']);
  }

  protected openHistory(): void {
    void this.router.navigate(['/history']);
  }
}
