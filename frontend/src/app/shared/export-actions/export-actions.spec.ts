import { TestBed } from '@angular/core/testing';

import { ExportActionsComponent } from './export-actions';

describe('ExportActionsComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [ExportActionsComponent] }).compileComponents();
  });

  function create() {
    const fixture = TestBed.createComponent(ExportActionsComponent);
    fixture.componentInstance.hasExports = true;
    fixture.componentInstance.findingCount = 3;
    fixture.detectChanges();
    return fixture;
  }

  it('should render one button per export format', () => {
    const fixture = create();
    const buttons = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('button.export-btn'),
    ).map((button) => button.textContent?.trim());
    expect(buttons).toEqual([
      'EXPORT CSV',
      'EXPORT JSON',
      'LH JSON',
      'EXPORT HTML',
      'EXPORT MD',
      'EXPORT PDF',
    ]);
  });

  it('should emit every client-side export event', () => {
    const fixture = create();
    const emitted: string[] = [];
    fixture.componentInstance.exportCsv.subscribe(() => emitted.push('csv'));
    fixture.componentInstance.exportJson.subscribe(() => emitted.push('json'));
    fixture.componentInstance.exportLighthouse.subscribe(() => emitted.push('lighthouse'));
    fixture.componentInstance.exportHtml.subscribe(() => emitted.push('html'));
    fixture.componentInstance.exportMd.subscribe(() => emitted.push('md'));
    fixture.componentInstance.exportPdf.subscribe(() => emitted.push('pdf'));

    const buttons = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>('button.export-btn'),
    );
    buttons.forEach((button) => button.click());

    expect(emitted).toEqual(['csv', 'json', 'lighthouse', 'html', 'md', 'pdf']);
  });

  it('should hide the toolbar without findings and surface the pdf busy state', () => {
    const fixture = TestBed.createComponent(ExportActionsComponent);
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelectorAll('button.export-btn').length).toBe(0);

    fixture.componentRef.setInput('hasExports', true);
    fixture.componentRef.setInput('pdfBusy', true);
    fixture.detectChanges();
    const buttons = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>('button.export-btn'),
    );
    expect(buttons.length).toBe(6);
    const pdf = buttons[5];
    expect(pdf.disabled).toBe(true);
    expect(pdf.textContent?.trim()).toBe('PDF...');
  });
});
