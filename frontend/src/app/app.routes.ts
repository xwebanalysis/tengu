import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: 'audit',
    loadComponent: () => import('./features/audit/audit').then((m) => m.AuditComponent),
  },
  {
    path: 'history',
    loadComponent: () => import('./features/history/history').then((m) => m.HistoryComponent),
  },
  { path: '', redirectTo: '/audit', pathMatch: 'full' },
];
