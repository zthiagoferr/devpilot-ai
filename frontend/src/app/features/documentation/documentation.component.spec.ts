import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';

import { DocumentationComponent } from './documentation.component';

describe('DocumentationComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DocumentationComponent],
    }).compileComponents();
  });

  it('renders the documentation sections and index', () => {
    const fixture = TestBed.createComponent(DocumentationComponent);
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('h1')?.textContent?.trim()).toBe('Documentação');
    expect(element.querySelectorAll('.docs-section').length).toBeGreaterThan(0);

    const index = element.querySelector('.docs-index');
    expect(index?.textContent).toContain('Apresentação em português');
  });
});
