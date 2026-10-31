import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type IconName =
  | 'activity'
  | 'alertTriangle'
  | 'apple'
  | 'arrowRight'
  | 'check'
  | 'chevronRight'
  | 'clock'
  | 'close'
  | 'code'
  | 'copy'
  | 'external'
  | 'folder'
  | 'gitBranch'
  | 'google'
  | 'grid'
  | 'history'
  | 'info'
  | 'lock'
  | 'menu'
  | 'microsoft'
  | 'plus'
  | 'sparkles'
  | 'xCircle';

const ICON_PATHS: Readonly<Record<IconName, readonly string[]>> = {
  activity: ['M22 12h-4l-3 9L9 3l-3 9H2'],
  apple: [
    'M15.5 7.5c-1 0-1.8.4-2.5.9-.7-.5-1.5-.9-2.5-.9-2.2 0-4 2-4 4.6 0 3.2 2.3 6.9 4.2 6.9.7 0 1.4-.4 2.3-.4s1.6.4 2.3.4c1.9 0 4.2-3.7 4.2-6.9 0-2.6-1.8-4.6-4-4.6Z',
    'M12.3 6.8c.7-.9.6-2.1.4-2.6-.8.1-1.7.6-2.2 1.3-.5.7-.6 1.8-.4 2.4.8.1 1.6-.4 2.2-1.1Z',
  ],
  alertTriangle: [
    'M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z',
    'M12 9v4',
    'M12 17h.01',
  ],
  arrowRight: ['M5 12h14', 'm13 6 6 6-6 6'],
  check: ['M20 6 9 17l-5-5'],
  chevronRight: ['m9 18 6-6-6-6'],
  clock: ['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z', 'M12 6v6l4 2'],
  close: ['M18 6 6 18', 'M6 6l12 12'],
  code: ['m8 6-6 6 6 6', 'm16 6 6 6-6 6'],
  copy: ['M8 8h12v12H8z', 'M16 8V4H4v12h4'],
  external: [
    'M15 3h6v6',
    'M10 14 21 3',
    'M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6',
  ],
  folder: ['M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'],
  gitBranch: [
    'M6 3v12',
    'M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z',
    'M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z',
    'M18 9a9 9 0 0 1-9 9',
  ],
  google: ['M21 12a9 9 0 1 1-2.64-6.36', 'M21 12h-9'],
  grid: ['M3 3h7v7H3z', 'M14 3h7v7h-7z', 'M14 14h7v7h-7z', 'M3 14h7v7H3z'],
  history: ['M3 12a9 9 0 1 0 3-6.7L3 8', 'M3 3v5h5', 'M12 7v5l3 2'],
  info: ['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z', 'M12 16v-4', 'M12 8h.01'],
  lock: ['M5 11h14v10H5z', 'M8 11V7a4 4 0 0 1 8 0v4'],
  menu: ['M4 6h16', 'M4 12h16', 'M4 18h16'],
  microsoft: [
    'M3 3h7.5v7.5H3z',
    'M13.5 3H21v7.5h-7.5z',
    'M3 13.5h7.5V21H3z',
    'M13.5 13.5H21V21h-7.5z',
  ],
  plus: ['M12 5v14', 'M5 12h14'],
  sparkles: [
    'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z',
    'M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15Z',
  ],
  xCircle: ['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z', 'm15 9-6 6', 'm9 9 6 6'],
};

@Component({
  selector: 'app-icon',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg
      [attr.width]="size()"
      [attr.height]="size()"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      [attr.stroke-width]="strokeWidth()"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      @for (path of paths(); track path) {
        <path [attr.d]="path" />
      }
    </svg>
  `,
  styles: `
    :host {
      display: inline-flex;
      flex: none;
      align-items: center;
      justify-content: center;
    }
  `,
})
export class IconComponent {
  readonly name = input.required<IconName>();
  readonly size = input(20);
  readonly strokeWidth = input(1.75);

  protected readonly paths = computed(() => ICON_PATHS[this.name()] ?? ICON_PATHS.info);
}
