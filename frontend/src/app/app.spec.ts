import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { App } from './app';
import { APP_CONFIG } from './core/config/config.service';

@Component({ selector: 'app-stub-page', standalone: true, template: '' })
class StubPageComponent {}

describe('App', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App, StubPageComponent],
      providers: [
        provideRouter([{ path: 'overview', component: StubPageComponent }]),
        {
          provide: APP_CONFIG,
          useValue: { apiBaseUrl: '', basePath: '', apiUnavailable: true },
        },
      ],
    }).compileComponents();
  });

  it('renders the application shell with a skip link', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('app-shell')).not.toBeNull();
    expect(element.querySelector('.skip-link')?.getAttribute('href')).toBe('#main-content');
  });

  it('exposes the top dock navigation with aria-current on the active route', async () => {
    const fixture = TestBed.createComponent(App);
    const router = TestBed.inject(Router);
    await router.navigateByUrl('/overview');
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    const chips = Array.from(
      element.querySelectorAll<HTMLAnchorElement>('a.content__footer-chip'),
    );
    expect(chips).toHaveLength(6);

    const brand = element.querySelector<HTMLAnchorElement>('a.content__footer-chip--brand');
    expect(brand).not.toBeNull();
    const brandImages = Array.from(brand?.querySelectorAll<HTMLImageElement>('img') ?? []);
    expect(brandImages).toHaveLength(1);
    expect(brandImages[0]?.getAttribute('src')).toBe('brand/mark-128.png');
    expect(brandImages[0]?.getAttribute('alt')).toBe('');
    expect(brand?.hasAttribute('aria-current')).toBe(false);

    const navChips = chips.filter((chip) => !chip.classList.contains('content__footer-chip--brand'));
    expect(navChips.map((chip) => chip.getAttribute('href'))).toEqual([
      '/overview',
      '/analysis/new',
      '/history',
      '/documentation',
      '/how-it-works',
    ]);

    const current = element.querySelectorAll<HTMLAnchorElement>('[aria-current="page"]');
    expect(current).toHaveLength(1);
    expect(current[0]?.textContent).toContain('Visão geral');
  });
});
