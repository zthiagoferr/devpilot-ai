import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { Router } from '@angular/router';

import { LoginPromptService } from '../../core/auth/login-prompt.service';
import { ButtonComponent } from '../../shared/components/button/button.component';
import { EmptyStateComponent } from '../../shared/components/empty-state/empty-state.component';
import { IconComponent } from '../../shared/components/icon/icon.component';

@Component({
  selector: 'app-history',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ButtonComponent, EmptyStateComponent, IconComponent],
  template: `
    <div class="flex flex-col gap-8">
      <header class="flex flex-col gap-3">
        <h1 class="text-display font-semibold tracking-[-0.02em] text-text">Histórico</h1>
        <p class="max-w-[62ch] text-body text-muted">
          Suas análises salvas ficam privadas na conta e ordenadas da mais recente para a mais
          antiga.
        </p>
      </header>

      <app-empty-state
        icon="lock"
        title="Histórico privado"
        description="Entre na sua conta para consultar as análises salvas. O acesso à conta estará disponível em breve."
      >
        <app-button variant="secondary" (click)="auth.open()">
          <app-icon name="lock" [size]="15" />
          Entrar
        </app-button>
        <app-button variant="ghost" (click)="startAnalysis()">
          <app-icon name="plus" [size]="15" />
          Analisar sem conta
        </app-button>
      </app-empty-state>
    </div>
  `,
})
export class HistoryComponent {
  protected readonly auth = inject(LoginPromptService);
  private readonly router = inject(Router);

  protected startAnalysis(): void {
    void this.router.navigate(['/analysis/new']);
  }
}
