import { TestBed } from '@angular/core/testing';
import { describe, expect, it, beforeEach } from 'vitest';

import { TabItem, TabsComponent } from './tabs.component';

const TABS: readonly TabItem[] = [
  { id: 'paste', label: 'Colar código' },
  { id: 'repository', label: 'Carregar repositório' },
  { id: 'disabled', label: 'Indisponível', disabled: true },
];

describe('TabsComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TabsComponent],
    }).compileComponents();
  });

  function createComponent(activeId = 'paste') {
    const fixture = TestBed.createComponent(TabsComponent);
    fixture.componentRef.setInput('tabs', TABS);
    fixture.componentRef.setInput('activeId', activeId);
    fixture.componentRef.setInput('ariaLabel', 'Método de análise');
    fixture.detectChanges();
    return fixture;
  }

  it('wires the tablist, tabs and tabpanel ARIA relationships', () => {
    const fixture = createComponent();
    const element = fixture.nativeElement as HTMLElement;

    expect(element.querySelector('[role="tablist"]')?.getAttribute('aria-label')).toBe(
      'Método de análise',
    );

    const tabs = element.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    expect(tabs.length).toBe(3);
    expect(tabs[0]?.getAttribute('aria-selected')).toBe('true');
    expect(tabs[1]?.getAttribute('aria-selected')).toBe('false');
    expect(tabs[0]?.getAttribute('tabindex')).toBe('0');
    expect(tabs[1]?.getAttribute('tabindex')).toBe('-1');
    expect(tabs[0]?.getAttribute('aria-controls')).toBe('panel-paste');

    const panel = element.querySelector('[role="tabpanel"]');
    expect(panel?.id).toBe('panel-paste');
    expect(panel?.getAttribute('aria-labelledby')).toBe('tab-paste');
  });

  it('moves selection with ArrowRight, skipping disabled tabs', async () => {
    const fixture = createComponent();
    const element = fixture.nativeElement as HTMLElement;
    const tabs = element.querySelectorAll<HTMLButtonElement>('[role="tab"]');

    tabs[0]?.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    fixture.detectChanges();

    expect(fixture.componentInstance.activeId()).toBe('repository');

    const updated = element.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    updated[1]?.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    fixture.detectChanges();

    expect(fixture.componentInstance.activeId()).toBe('paste');
  });

  it('supports Home and End navigation', () => {
    const fixture = createComponent('repository');
    const element = fixture.nativeElement as HTMLElement;
    let tabs = element.querySelectorAll<HTMLButtonElement>('[role="tab"]');

    tabs[2]?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true }));
    fixture.detectChanges();
    expect(fixture.componentInstance.activeId()).toBe('paste');

    tabs = element.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    tabs[0]?.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true }));
    fixture.detectChanges();
    expect(fixture.componentInstance.activeId()).toBe('repository');
  });

  it('updates aria-selected after a click selects another tab', () => {
    const fixture = createComponent();
    const element = fixture.nativeElement as HTMLElement;
    const tabs = element.querySelectorAll<HTMLButtonElement>('[role="tab"]');

    tabs[1]?.click();
    fixture.detectChanges();

    expect(fixture.componentInstance.activeId()).toBe('repository');
    expect(tabs[0]?.getAttribute('aria-selected')).toBe('false');
    expect(tabs[1]?.getAttribute('aria-selected')).toBe('true');
    expect(element.querySelector('[role="tabpanel"]')?.id).toBe('panel-repository');
  });
});
