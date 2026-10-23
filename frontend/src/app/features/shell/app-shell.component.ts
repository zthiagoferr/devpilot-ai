import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterOutlet } from '@angular/router';
import { filter, map } from 'rxjs';

import { LoginPromptService } from '../../core/auth/login-prompt.service';
import { ButtonComponent } from '../../shared/components/button/button.component';
import { IconComponent, IconName } from '../../shared/components/icon/icon.component';
import { LoginPromptComponent } from '../auth/login-prompt.component';
import { ServiceStatusComponent } from './service-status.component';

interface NavItem {
  readonly key: 'overview' | 'analysis' | 'history';
  readonly label: string;
  readonly path: string;
  readonly icon: IconName;
}

const NAV_ITEMS: readonly NavItem[] = [
  { key: 'overview', label: 'Visão geral', path: '/overview', icon: 'grid' },
  { key: 'analysis', label: 'Nova análise', path: '/analysis/new', icon: 'plus' },
  { key: 'history', label: 'Histórico', path: '/history', icon: 'history' },
];

@Component({
  selector: 'app-shell',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterOutlet,
    RouterLink,
    ButtonComponent,
    IconComponent,
    LoginPromptComponent,
    ServiceStatusComponent,
  ],
  templateUrl: './app-shell.component.html',
  styleUrl: './app-shell.component.css',
  host: {
    '(document:keydown.escape)': 'handleEscape()',
  },
})
export class AppShellComponent {
  protected readonly auth = inject(LoginPromptService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly navItems = NAV_ITEMS;
  protected readonly drawerOpen = signal(false);

  private readonly currentUrl = toSignal(
    this.router.events.pipe(
      filter((event): event is NavigationEnd => event instanceof NavigationEnd),
      map((event) => event.urlAfterRedirects),
    ),
    { initialValue: this.router.url },
  );

  protected readonly activeSection = computed<NavItem['key']>(() => {
    const url = this.currentUrl();
    if (url.startsWith('/analysis')) {
      return 'analysis';
    }
    if (url.startsWith('/history')) {
      return 'history';
    }
    return 'overview';
  });

  private readonly menuButton = viewChild<ElementRef<HTMLButtonElement>>('menuButton');
  private readonly drawerCloseButton =
    viewChild<ElementRef<HTMLButtonElement>>('drawerCloseButton');

  constructor() {
    this.router.events
      .pipe(
        filter((event): event is NavigationEnd => event instanceof NavigationEnd),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe(() => this.closeDrawer(false));

    const handleResize = (): void => {
      if (this.drawerOpen() && window.matchMedia('(min-width: 1024px)').matches) {
        this.closeDrawer(false);
      }
    };
    window.addEventListener('resize', handleResize);
    this.destroyRef.onDestroy(() => window.removeEventListener('resize', handleResize));

    effect((onCleanup) => {
      if (!this.drawerOpen()) {
        return;
      }
      const previousOverflow = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
      onCleanup(() => {
        document.body.style.overflow = previousOverflow;
      });
    });
  }

  protected isActive(item: NavItem): boolean {
    return this.activeSection() === item.key;
  }

  protected openDrawer(): void {
    this.drawerOpen.set(true);
    setTimeout(() => this.drawerCloseButton()?.nativeElement.focus(), 0);
  }

  protected closeDrawer(restoreFocus: boolean): void {
    if (!this.drawerOpen()) {
      return;
    }
    this.drawerOpen.set(false);
    if (restoreFocus) {
      setTimeout(() => this.menuButton()?.nativeElement.focus(), 0);
    }
  }

  protected handleEscape(): void {
    if (this.drawerOpen()) {
      this.closeDrawer(true);
    }
  }
}
