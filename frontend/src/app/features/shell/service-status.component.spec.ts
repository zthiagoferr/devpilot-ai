import { ComponentFixture, TestBed } from '@angular/core/testing';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiClient } from '../../core/api/api-client';
import { ApiError } from '../../core/api/api-error.mapper';
import { ConfigService } from '../../core/config/config.service';
import { ServiceStatusComponent } from './service-status.component';

describe('ServiceStatusComponent', () => {
  const getOrchestratorStatus = vi.fn();

  async function create(): Promise<ComponentFixture<ServiceStatusComponent>> {
    await TestBed.configureTestingModule({
      imports: [ServiceStatusComponent],
      providers: [
        {
          provide: ApiClient,
          useValue: { getOrchestratorStatus },
        },
        {
          provide: ConfigService,
          useValue: { apiBaseUrl: 'http://api.test', hasApi: () => true },
        },
      ],
    }).compileComponents();

    const fixture = TestBed.createComponent(ServiceStatusComponent);
    fixture.detectChanges();
    await settle(fixture);
    return fixture;
  }

  async function settle(fixture: ComponentFixture<ServiceStatusComponent>): Promise<void> {
    for (let index = 0; index < 5; index += 1) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      fixture.detectChanges();
    }
  }

  afterEach(() => {
    getOrchestratorStatus.mockReset();
    vi.restoreAllMocks();
  });

  it('reports an operational API', async () => {
    getOrchestratorStatus.mockResolvedValue({ status: 'ready' });
    const fixture = await create();
    const element = fixture.nativeElement as HTMLElement;

    expect(element.textContent).toContain('API operacional');
    fixture.destroy();
  });

  it('reports a degraded API', async () => {
    getOrchestratorStatus.mockResolvedValue({ status: 'warming' });
    const fixture = await create();
    const element = fixture.nativeElement as HTMLElement;

    expect(element.textContent).toContain('API com restrições');
    fixture.destroy();
  });

  it('names an HTTP 503 JSON response explicitly', async () => {
    getOrchestratorStatus.mockRejectedValue(
      new ApiError('server', 'service unavailable', { status: 503, bodyIsJson: true }),
    );
    const fixture = await create();
    const element = fixture.nativeElement as HTMLElement;

    expect(element.textContent).toContain('API indisponível (HTTP 503)');
    expect(element.textContent).toContain('verifique o estado do serviço');
    fixture.destroy();
  });

  it('suggests an unexpected response for a non-JSON proxy body', async () => {
    getOrchestratorStatus.mockRejectedValue(
      new ApiError('server', 'service unavailable', { status: 503, bodyIsJson: false }),
    );
    const fixture = await create();
    const element = fixture.nativeElement as HTMLElement;

    expect(element.textContent).toContain('Resposta inesperada da API');
    fixture.destroy();
  });

  it('identifies a connection/CORS failure', async () => {
    getOrchestratorStatus.mockRejectedValue(
      new ApiError('network', 'Não foi possível falar com a API.'),
    );
    const fixture = await create();
    const element = fixture.nativeElement as HTMLElement;

    expect(element.textContent).toContain('Falha de conexão/CORS com a API');
    fixture.destroy();
  });

  it('identifies a request timeout', async () => {
    getOrchestratorStatus.mockRejectedValue(new DOMException('Aborted', 'AbortError'));
    const fixture = await create();
    const element = fixture.nativeElement as HTMLElement;

    expect(element.textContent).toContain('Tempo esgotado ao contatar a API');
    fixture.destroy();
  });
});
