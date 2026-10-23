import { ChangeDetectionStrategy, Component } from '@angular/core';

import { AppShellComponent } from './features/shell/app-shell.component';

@Component({
  selector: 'app-root',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [AppShellComponent],
  template: '<app-shell />',
})
export class App {}
