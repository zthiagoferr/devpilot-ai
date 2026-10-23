import { ChangeDetectionStrategy, Component, inject } from '@angular/core';

import { LoginPromptService } from '../../core/auth/login-prompt.service';
import { ButtonComponent } from '../../shared/components/button/button.component';
import { ModalComponent } from '../../shared/components/modal/modal.component';

@Component({
  selector: 'app-login-prompt',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ButtonComponent, ModalComponent],
  template: `
    <app-modal
      title="Entre para continuar"
      description="O histórico de análises é privado e vinculado à sua conta."
      [opened]="auth.isOpen()"
      (closed)="auth.close()"
    >
      <p>
        A autenticação com Firebase será ativada na próxima etapa do painel. Enquanto isso, você
        pode criar análises manuais sem conta — apenas o detalhe salvo exige login.
      </p>

      <app-button modalFooter variant="secondary" (click)="auth.close()">Entendi</app-button>
    </app-modal>
  `,
  styles: `
    p {
      color: var(--color-muted);
      line-height: 1.6;
    }
  `,
})
export class LoginPromptComponent {
  protected readonly auth = inject(LoginPromptService);
}
