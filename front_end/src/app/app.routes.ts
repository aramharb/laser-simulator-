import { Routes } from '@angular/router';
import { path } from 'pixi.js';

export const routes: Routes = [
    {
        path: '',
        loadComponent: () => import('./exercice/exercice').then(m => m.ExerciceComponent)
    }
];
