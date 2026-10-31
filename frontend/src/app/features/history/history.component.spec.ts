import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiClient } from '../../core/api/api-client';
import { Analysis, AnalysisResult } from '../../core/api/api.types';
import { AuthService } from '../../core/auth/auth.service';
import { LoginPromptService } from '../../core/auth/login-prompt.service';
import { HistoryComponent } from './history.component';

function analysis(id: string, createdAt: string, result: AnalysisResult): Analysis {
  return {
    id,
    task: 'code',
    project_name: `Projeto ${id}`,
    source_code: 'print(1)',
    repository_url: null,
    result,
    status: 'completed',
    created_at: createdAt,
  };
}

describe('HistoryComponent', () => {
  const listAnalyses = vi.fn();
  const authenticated = signal(true);
  const ready = signal(true);

  beforeEach(async () => {
    listAnalyses.mockReset();
    authenticated.set(true);
    ready.set(true);

    await TestBed.configureTestingModule({
      imports: [HistoryComponent],
      providers: [
        provideRouter([]),
        { provide: ApiClient, useValue: { listAnalyses } },
        {
          provide: AuthService,
          useValue: {
            isAuthenticated: authenticated,
            ready,
            expireSession: vi.fn(),
          },
        },
        { provide: LoginPromptService, useValue: { notice: signal(''), open: vi.fn() } },
      ],
    }).compileComponents();
  });

  async function settle(fixture: ComponentFixture<HistoryComponent>): Promise<void> {
    for (let index = 0; index < 10; index += 1) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      fixture.detectChanges();
    }
  }

  it('renders "—" instead of the raw score for skipped and unavailable analyses', async () => {
    listAnalyses.mockResolvedValue([
      analysis('evaluated', '2026-03-01T10:00:00Z', {
        score: 80,
        score_status: 'evaluated',
      }),
      analysis('skipped', '2026-02-01T10:00:00Z', {
        score: 100,
        score_status: 'skipped',
        validation_skipped: true,
      }),
      analysis('unavailable', '2026-01-01T10:00:00Z', {
        score: 90,
        score_status: 'unavailable',
      }),
    ]);

    const fixture = TestBed.createComponent(HistoryComponent);
    fixture.detectChanges();
    await settle(fixture);

    const element = fixture.nativeElement as HTMLElement;
    const scores = Array.from(element.querySelectorAll('tbody tr')).map((row) =>
      (row.querySelectorAll('td')[3]?.textContent ?? '').trim(),
    );

    expect(scores).toEqual(['80/100', '—', '—']);
    expect(element.textContent).not.toContain('100/100');
    expect(element.textContent).not.toContain('90/100');
  });

  it('keeps showing the score for legacy payloads without a score status', async () => {
    listAnalyses.mockResolvedValue([analysis('legacy', '2026-03-01T10:00:00Z', { score: 72 })]);

    const fixture = TestBed.createComponent(HistoryComponent);
    fixture.detectChanges();
    await settle(fixture);

    const element = fixture.nativeElement as HTMLElement;
    const scores = Array.from(element.querySelectorAll('tbody tr')).map((row) =>
      (row.querySelectorAll('td')[3]?.textContent ?? '').trim(),
    );

    expect(scores).toEqual(['72/100']);
  });
});
