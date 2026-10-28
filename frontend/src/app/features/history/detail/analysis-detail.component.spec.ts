import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiClient } from '../../../core/api/api-client';
import { Analysis } from '../../../core/api/api.types';
import { AuthService } from '../../../core/auth/auth.service';
import { LoginPromptService } from '../../../core/auth/login-prompt.service';
import { AnalysisDetailComponent } from './analysis-detail.component';

const ANALYSIS: Analysis = {
  id: 'analysis-1',
  task: 'code',
  project_name: 'Financeiro',
  source_code: 'User Function Teste()\nIf .T.\nReturn\n',
  repository_url: 'owner/repo',
  result: {
    score: 68,
    summary: 'Dois problemas encontrados.',
    language: 'advpl',
    language_source: 'extension',
    confidence: 0.9,
    issues: [
      {
        severity: 'info',
        message: 'Variável global',
        line: 10,
        cause: 'global_variable',
        language: 'advpl',
        origin: 'validator',
        analysis_kind: 'heuristic_validation',
        file: 'src/app.prg',
      },
      {
        severity: 'critical',
        message: 'Bloco IF sem fechamento',
        line: 2,
        column: 4,
        cause: 'unclosed_block',
        code: 'unclosed_block',
        language: 'advpl',
        origin: 'validator',
        analysis_kind: 'heuristic_validation',
        file: 'src/app.prg',
      },
    ],
  },
  status: 'completed',
  created_at: '2026-10-28T12:00:00Z',
};

describe('AnalysisDetailComponent', () => {
  const getAnalysis = vi.fn();
  const loginOpen = vi.fn();

  beforeEach(async () => {
    getAnalysis.mockReset();
    loginOpen.mockReset();
    getAnalysis.mockResolvedValue(ANALYSIS);

    await TestBed.configureTestingModule({
      imports: [AnalysisDetailComponent],
      providers: [
        provideRouter([]),
        { provide: ApiClient, useValue: { getAnalysis } },
        { provide: AuthService, useValue: { isAuthenticated: () => false } },
        { provide: LoginPromptService, useValue: { open: loginOpen } },
      ],
    }).compileComponents();
  });

  async function settle(fixture: ComponentFixture<AnalysisDetailComponent>): Promise<void> {
    for (let index = 0; index < 10; index += 1) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      fixture.detectChanges();
    }
  }

  it('renders language, translated causes, origin, location and the ADVPL disclaimer', async () => {
    const fixture = TestBed.createComponent(AnalysisDetailComponent);
    fixture.componentRef.setInput('id', 'analysis-1');
    fixture.detectChanges();
    await settle(fixture);

    const element = fixture.nativeElement as HTMLElement;
    expect(getAnalysis).toHaveBeenCalledWith('analysis-1', expect.any(AbortSignal));
    expect(element.textContent).toContain('Financeiro');
    expect(element.textContent).toContain('ADVPL');
    expect(element.textContent).toContain('90% de confiança');
    expect(element.textContent).toContain('Causa: Bloco sem fechamento');
    expect(element.textContent).toContain('Causa: Variável global');
    expect(element.textContent).toContain('src/app.prg:2:4');
    expect(element.textContent).toContain('Validação local (heurística)');
    expect(element.textContent).toContain('Análise estática — não valida compilação');
    expect(element.textContent).toContain('Corrigir com IA');
  });

  it('sorts issues by severity before rendering', async () => {
    const fixture = TestBed.createComponent(AnalysisDetailComponent);
    fixture.componentRef.setInput('id', 'analysis-1');
    fixture.detectChanges();
    await settle(fixture);

    const element = fixture.nativeElement as HTMLElement;
    const text = element.textContent ?? '';
    expect(text.indexOf('Bloco IF sem fechamento')).toBeLessThan(text.indexOf('Variável global'));
  });
});
