import { Component, provideZonelessChangeDetection } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { TranslateService } from '../../core/i18n.service';
import { TranslatePipe } from './translate.pipe';

@Component({
  imports: [TranslatePipe],
  template: `<span>{{ 'nav.audit' | t }}</span>`,
})
class HostComponent {}

describe('TranslatePipe', () => {
  beforeEach(async () => {
    localStorage.clear();
    await TestBed.configureTestingModule({
      imports: [HostComponent],
      providers: [provideZonelessChangeDetection()],
    }).compileComponents();
  });

  it('should switch language when the i18n signal changes (zoneless)', () => {
    const fixture = TestBed.createComponent(HostComponent);
    fixture.detectChanges();
    const span = fixture.nativeElement.querySelector('span') as HTMLElement;
    expect(span.textContent).toContain('01 // AUDIT');

    const i18n = TestBed.inject(TranslateService);
    i18n.toggle();
    fixture.detectChanges();
    expect(span.textContent).toContain('01 // AUDITORÍA');
  });
});
