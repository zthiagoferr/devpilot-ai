import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { App } from './app';
import { APP_CONFIG } from './core/config/config.service';

describe('App', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [
        provideRouter([]),
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

  it('exposes the primary navigation with aria-current on the active route', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();

    const links = (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLAnchorElement>(
      '.nav__link',
    );
    expect(links.length).toBe(3);
    expect(links[0]?.getAttribute('aria-current')).toBe('page');
  });
});
