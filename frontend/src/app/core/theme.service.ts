import { DOCUMENT } from '@angular/common';
import { Inject, Injectable, signal } from '@angular/core';

/**
 * Dark/light theme. Dark is the default (OLED black); light is enabled by the
 * `.theme-light` class on `<body>`. The choice persists in localStorage under
 * `tengu-theme`.
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly storageKey = 'tengu-theme';
  readonly isDark = signal(true);

  constructor(@Inject(DOCUMENT) private document: Document) {
    const saved = this.readStored();
    if (saved === 'light') {
      this.isDark.set(false);
      this.document.body.classList.add('theme-light');
    }
  }

  toggle(): void {
    const next = !this.isDark();
    this.isDark.set(next);
    this.document.body.classList.toggle('theme-light', !next);
    localStorage.setItem(this.storageKey, next ? 'dark' : 'light');
  }

  label(keyLight: string, keyDark: string): string {
    return this.isDark() ? keyDark : keyLight;
  }

  private readStored(): 'light' | 'dark' | null {
    const saved = localStorage.getItem(this.storageKey);
    return saved === 'light' || saved === 'dark' ? saved : null;
  }
}
