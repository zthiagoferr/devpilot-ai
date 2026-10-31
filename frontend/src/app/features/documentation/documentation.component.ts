import { ChangeDetectionStrategy, Component } from '@angular/core';
import { DOCUMENTATION } from './documentation-data';

@Component({
  selector: 'app-documentation',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './documentation.component.html',
  styleUrl: './documentation.component.css',
})
export class DocumentationComponent {
  protected readonly documents = DOCUMENTATION;

  protected scrollToSection(index: number): void {
    const section = document.getElementById(`doc-${index}`);
    if (!section) return;
    section.scrollIntoView({
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
      block: 'start',
    });
  }
}
