import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiClient } from '../../core/api/api-client';
import { Analysis, AnalysisResult } from '../../core/api/api.types';
import { AuthService } from '../../core/auth/auth.service';
import { LoginPromptService } from '../../core/auth/login-prompt.service';
import { OverviewComponent } from './overview.component';

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

describe('OverviewComponent', () => {
  const listAnalyses = vi.fn();
  const authenticated = signal(true);
  const ready = signal(true);

  beforeEach(async () => {
    listAnalyses.mockReset();
    authenticated.set(true);
    ready.set(true);

    await TestBed.configureTestingModule({
      imports: [OverviewComponent],
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

  async function settle(fixture: ComponentFixture<OverviewComponent>): Promise<void> {
    for (let index = 0; index < 10; index += 1) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      fixture.detectChanges();
    }
  }

  function metricValue(element: HTMLElement, label: string): string {
    const card = Array.from(
      element.querySelectorAll('section[aria-label="Indicadores"] app-card'),
    ).find((item) => (item.textContent ?? '').includes(label));
    return (card?.querySelector('.mono-metric')?.textContent ?? '').trim();
  }

  function activityScores(element: HTMLElement): string[] {
    return Array.from(element.querySelectorAll('.activity-row__score .mono-metric')).map((item) =>
      (item.textContent ?? '').trim(),
    );
  }

  it('renders "—" for skipped/unavailable rows and excludes them from the average', async () => {
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

    const fixture = TestBed.createComponent(OverviewComponent);
    fixture.detectChanges();
    await settle(fixture);

    const element = fixture.nativeElement as HTMLElement;
    expect(metricValue(element, 'Score médio')).toBe('80.0');
    expect(activityScores(element)).toEqual(['80', '—', '—']);
  });

  it('shows "—" for the average when nothing was actually evaluated', async () => {
    listAnalyses.mockResolvedValue([
      analysis('skipped', '2026-02-01T10:00:00Z', {
        score: 100,
        score_status: 'skipped',
      }),
      analysis('unavailable', '2026-01-01T10:00:00Z', {
        score: 90,
        score_status: 'unavailable',
      }),
    ]);

    const fixture = TestBed.createComponent(OverviewComponent);
    fixture.detectChanges();
    await settle(fixture);

    const element = fixture.nativeElement as HTMLElement;
    expect(metricValue(element, 'Score médio')).toBe('—');
    expect(activityScores(element)).toEqual(['—', '—']);
  });
});
