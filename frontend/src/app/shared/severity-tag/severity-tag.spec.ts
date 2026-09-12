import { TestBed } from '@angular/core/testing';

import { SeverityTagComponent } from './severity-tag';

describe('SeverityTagComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [SeverityTagComponent] }).compileComponents();
  });

  it('should render the uppercase unified severity', () => {
    const fixture = TestBed.createComponent(SeverityTagComponent);
    fixture.componentInstance.severity = 'medium';
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;
    expect(element.textContent?.trim()).toBe('[ MEDIUM ]');
    expect(element.querySelector('span')?.classList.contains('sev-medium')).toBe(true);
  });

  it('should map legacy labels to unified classes', () => {
    const fixture = TestBed.createComponent(SeverityTagComponent);
    fixture.componentInstance.severity = 'Error';
    expect(fixture.componentInstance.tagClass()).toBe('sev-high');
    expect(fixture.componentInstance.label).toBe('ERROR');
  });

  it('should map pass and critical', () => {
    const fixture = TestBed.createComponent(SeverityTagComponent);
    fixture.componentInstance.severity = 'pass';
    expect(fixture.componentInstance.tagClass()).toBe('sev-pass');
    fixture.componentInstance.severity = 'critical';
    expect(fixture.componentInstance.tagClass()).toBe('sev-critical');
  });
});
