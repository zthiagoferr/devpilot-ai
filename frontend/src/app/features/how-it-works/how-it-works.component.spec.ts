import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { beforeEach, describe, expect, it } from 'vitest';

import { HowItWorksComponent } from './how-it-works.component';

describe('HowItWorksComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [HowItWorksComponent],
      providers: [provideRouter([])],
    }).compileComponents();
  });

  it('renders the guide heading, steps and the primary action', () => {
    const fixture = TestBed.createComponent(HowItWorksComponent);
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('h1')?.textContent?.trim()).toBe('Como funciona?');

    const steps = element.querySelectorAll('.help-steps li');
    expect(steps.length).toBeGreaterThan(0);

    const primary = element.querySelector<HTMLAnchorElement>('.help-actions a.help-primary');
    expect(primary?.getAttribute('href')).toBe('/analysis/new');
    expect(primary?.textContent).toContain('Nova análise');
  });
});
