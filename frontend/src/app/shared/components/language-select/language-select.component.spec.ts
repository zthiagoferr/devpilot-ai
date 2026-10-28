import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';

import { AnalysisLanguage } from '../../../core/api/api.types';
import { LanguageSelectComponent } from './language-select.component';

@Component({
  imports: [LanguageSelectComponent],
  template: `<app-language-select [(value)]="language" [(protheusVersion)]="version" />`,
})
class HostComponent {
  readonly language = signal<AnalysisLanguage>('auto');
  readonly version = signal('');
}

describe('LanguageSelectComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [HostComponent] }).compileComponents();
  });

  function setup() {
    const fixture = TestBed.createComponent(HostComponent);
    fixture.detectChanges();
    return fixture;
  }

  it('offers auto detection and all supported languages', () => {
    const element = setup().nativeElement as HTMLElement;
    const select = element.querySelector<HTMLSelectElement>('select');

    expect(select).not.toBeNull();
    expect(select?.value).toBe('auto');
    expect(Array.from(select?.options ?? []).map((option) => option.textContent?.trim())).toEqual([
      'Detectar automaticamente',
      'Python',
      'ADVPL',
      'HTML5',
      'CSS3',
      'JavaScript',
    ]);

    const label = element.querySelector<HTMLLabelElement>('label');
    expect(label?.getAttribute('for')).toBe(select?.id);
  });

  it('shows the optional Protheus version only for ADVPL', () => {
    const fixture = setup();
    const element = fixture.nativeElement as HTMLElement;
    const select = element.querySelector<HTMLSelectElement>('select');

    if (select !== null) {
      select.value = 'advpl';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    }
    fixture.detectChanges();

    expect(fixture.componentInstance.language()).toBe('advpl');
    const versionInput = element.querySelector<HTMLInputElement>('input');
    expect(versionInput).not.toBeNull();
    expect(element.textContent).toContain('Versão Protheus');
    expect(element.textContent).toContain('não exige Protheus instalado');

    if (versionInput !== null) {
      versionInput.value = '12.1.2410';
      versionInput.dispatchEvent(new Event('input', { bubbles: true }));
    }
    fixture.detectChanges();
    expect(fixture.componentInstance.version()).toBe('12.1.2410');

    if (select !== null) {
      select.value = 'python';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    }
    fixture.detectChanges();

    expect(fixture.componentInstance.language()).toBe('python');
    expect(element.querySelector('input')).toBeNull();
  });
});
