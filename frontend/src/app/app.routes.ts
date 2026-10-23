import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: 'overview',
    title: 'Visão geral — DevPilot AI',
    loadComponent: () =>
      import('./features/overview/overview.component').then(
        (module) => module.OverviewComponent,
      ),
  },
  {
    path: 'analysis/new',
    title: 'Nova análise — DevPilot AI',
    loadComponent: () =>
      import('./features/analysis/new/analysis-new.component').then(
        (module) => module.AnalysisNewComponent,
      ),
  },
  {
    path: 'history',
    title: 'Histórico — DevPilot AI',
    loadComponent: () =>
      import('./features/history/history.component').then(
        (module) => module.HistoryComponent,
      ),
  },
  {
    path: 'history/:id',
    title: 'Detalhe da análise — DevPilot AI',
    loadComponent: () =>
      import('./features/history/detail/analysis-detail.component').then(
        (module) => module.AnalysisDetailComponent,
      ),
  },

  // Redirects kept for links shared from the legacy dashboard hash routes.
  { path: 'analysis', pathMatch: 'full', redirectTo: 'analysis/new' },
  { path: 'new-analysis', pathMatch: 'full', redirectTo: 'analysis/new' },
  { path: 'analysis-detail', pathMatch: 'full', redirectTo: 'history' },
  { path: '', pathMatch: 'full', redirectTo: 'overview' },
  { path: '**', redirectTo: 'overview' },
];
