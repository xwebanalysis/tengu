import { inject, Injectable } from '@angular/core';

import { TranslateService } from './i18n.service';
import { AuditMode, FindingView, Severity, severityCounts } from './models';
import { htmlLines, locateLine } from './snippet-locator';

export interface AuditExportContext {
  mode: AuditMode;
  url: string;
  subdomains: boolean;
  findings: readonly FindingView[];
  html: string;
}

/** Colors mirror Nothing tokens (`--success`, `--warning`, `--accent`, `--interactive`). */
const SEVERITY_HEX: Record<Severity, string> = {
  pass: '#4A9E5C',
  info: '#999999',
  low: '#D4A843',
  medium: '#D4A843',
  high: '#D71921',
  critical: '#D71921',
};

const CATEGORY_HEX: Record<string, string> = {
  performance: '#5B9BF6',
  seo: '#D4A843',
  accessibility: '#4A9E5C',
  best_practices: '#D71921',
};

const LIGHTHOUSE_CATEGORY: Record<string, string> = {
  performance: 'performance',
  seo: 'seo',
  accessibility: 'accessibility',
  best_practices: 'best-practices',
};

/**
 * Client-side exports: CSV, JSON, Lighthouse JSON, PDF, HTML and Markdown.
 * jsPDF is imported lazily so the initial bundle stays lean and tests never
 * need the renderer.
 */
@Injectable({ providedIn: 'root' })
export class ExportService {
  private readonly i18n = inject(TranslateService);

  exportCsv(context: AuditExportContext): void {
    const headers = [
      'mode',
      'url',
      'page_url',
      'category',
      'check',
      'severity',
      'title',
      'description',
      'snippet',
      'line',
    ];
    const rows = context.findings.map((finding) =>
      headers
        .map((header) => {
          switch (header) {
            case 'mode':
              return this.csvCell(context.mode);
            case 'url':
              return this.csvCell(context.url);
            case 'page_url':
              return this.csvCell(finding.page_url || context.url);
            case 'title':
              return this.csvCell(this.exportTitle(finding));
            case 'description':
              return this.csvCell(this.exportDescription(finding));
            case 'line':
              return this.csvCell(String(this.lineOf(context, finding)));
            default:
              return this.csvCell(String(finding[header as keyof FindingView] ?? ''));
          }
        })
        .join(','),
    );
    const csv = [headers.join(','), ...rows, `\n# ${this.i18n.t('audit.generated_by')}`].join('\n');
    this.downloadBlob(
      new Blob([csv], { type: 'text/csv;charset=utf-8' }),
      `${this.filenameStem('tengu-audit', context.url)}.csv`,
    );
  }

  exportJson(context: AuditExportContext): void {
    const payload = {
      mode: context.mode,
      url: context.url,
      subdomains: context.subdomains,
      timestamp: new Date().toISOString(),
      generator: this.i18n.t('audit.generated_by'),
      summary: severityCounts(context.findings),
      findings: context.findings.map((finding) => ({
        ...finding,
        line: this.lineOf(context, finding),
        page_url: finding.page_url || context.url,
      })),
    };
    this.downloadBlob(
      new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' }),
      `${this.filenameStem('tengu-audit', context.url)}.json`,
    );
  }

  exportLighthouse(context: AuditExportContext): void {
    const audits: Record<string, unknown> = {};
    for (const finding of context.findings) {
      audits[finding.check] = {
        id: finding.check,
        title: this.exportTitle(finding),
        description: this.exportDescription(finding),
        score: this.lighthouseScore(finding.severity),
        scoreDisplayMode: finding.severity === 'info' ? 'informative' : 'binary',
        numericValue: null,
        displayValue: null,
        warnings: [],
        details: {
          items: [{ snippet: finding.snippet || '', page_url: finding.page_url || context.url }],
        },
      };
    }

    const categories: Record<string, unknown> = {};
    for (const [category, lighthouseId] of Object.entries(LIGHTHOUSE_CATEGORY)) {
      const items = context.findings.filter((finding) => finding.category === category);
      if (items.length === 0) {
        continue;
      }
      const high = items.filter((f) => f.severity === 'high' || f.severity === 'critical').length;
      const medium = items.filter((f) => f.severity === 'medium' || f.severity === 'low').length;
      categories[lighthouseId] = {
        title: category,
        score: Math.max(0, 1 - (high * 0.3 + medium * 0.1)),
        auditRefs: items.map((finding) => ({ id: finding.check, weight: 1, group: '' })),
      };
    }

    const report = {
      lighthouseVersion: '11.0.0',
      requestedUrl: context.url,
      finalUrl: context.url,
      fetchTime: new Date().toISOString(),
      userAgent: 'Tengu',
      environment: { networkUserAgent: 'Tengu', benchmarkIndex: 1 },
      configSettings: {
        formFactor: 'desktop',
        screenEmulation: { mobile: false, width: 1350, height: 940, deviceScaleFactor: 1 },
      },
      categories,
      categoryGroups: {},
      audits,
    };

    this.downloadBlob(
      new Blob([JSON.stringify(report, null, 2)], { type: 'application/json;charset=utf-8' }),
      `${this.filenameStem('tengu-lighthouse', context.url)}.json`,
    );
  }

  async exportPdf(context: AuditExportContext): Promise<void> {
    const { jsPDF } = await import('jspdf');
    const { default: autoTable } = await import('jspdf-autotable');

    const counts = severityCounts(context.findings);
    const doc = new jsPDF('landscape', 'mm', 'a4');
    doc.setFillColor(0, 0, 0);
    doc.rect(0, 0, 297, 210, 'F');
    doc.setTextColor(255, 255, 255);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(18);
    doc.text(this.i18n.t('audit.report_title'), 15, 25);
    doc.setFontSize(7);
    doc.setTextColor(153, 153, 153);
    doc.text('— XWA submodule — Xscriptor', 15, 30);
    doc.setFont('helvetica', 'normal');
    doc.setTextColor(255, 255, 255);
    doc.setFontSize(10);
    doc.text(
      `${this.i18n.t('audit.url')}: ${context.url}  (${this.i18n.t('audit.mode_' + context.mode)})`,
      15,
      38,
    );
    doc.text(
      `${this.i18n.t('audit.date')}: ${new Date().toISOString()}  ${this.i18n.t('audit.findings')}: ${context.findings.length}`,
      15,
      44,
    );

    const headers = [
      [
        this.i18n.t('audit.category'),
        this.i18n.t('audit.check'),
        this.i18n.t('audit.sev'),
        this.i18n.t('audit.issue'),
        this.i18n.t('audit.page'),
        'L',
        this.i18n.t('audit.code'),
      ],
    ];
    const data = context.findings.map((finding) => [
      this.categoryLabel(finding.category),
      finding.check,
      finding.severity.toUpperCase(),
      this.exportTitle(finding),
      (finding.page_url || context.url).replace(/^https?:\/\//, '').slice(0, 30),
      this.lineOf(context, finding) > 0 ? `L${this.lineOf(context, finding)}` : '-',
      (finding.snippet || this.exportDescription(finding)).slice(0, 80).replace(/\s+/g, ' ').trim(),
    ]);

    autoTable(doc, {
      startY: 50,
      head: headers,
      body: data,
      theme: 'grid',
      styles: {
        fillColor: [17, 17, 17],
        textColor: [232, 232, 232],
        fontSize: 7,
        font: 'helvetica',
        cellPadding: 2,
      },
      headStyles: { fillColor: [0, 0, 0], textColor: [232, 232, 232], fontStyle: 'bold' },
      columnStyles: {
        0: { cellWidth: 16 },
        1: { cellWidth: 22 },
        2: { cellWidth: 12 },
        3: { cellWidth: 44 },
        4: { cellWidth: 36 },
        5: { cellWidth: 8 },
        6: { cellWidth: 'auto' },
      },
    });

    doc.save(`${this.filenameStem('tengu-audit', context.url)}.pdf`);
  }

  exportHtml(context: AuditExportContext): void {
    const counts = severityCounts(context.findings);
    const language = this.i18n.isEn() ? 'en' : 'es';
    const findingsHtml = context.findings
      .map(
        (finding) => `<tr>
        <td><span style="color:${CATEGORY_HEX[finding.category] || '#999999'}">${this.categoryLabel(finding.category)}</span></td>
        <td><code>${finding.check}</code></td>
        <td><span style="color:${SEVERITY_HEX[finding.severity]};font-family:'Space Mono',monospace;font-size:11px">${finding.severity.toUpperCase()}</span></td>
        <td>${this.escapeHtml(this.exportTitle(finding))}</td>
        <td style="font-size:12px;color:#5B9BF6;font-family:'Space Mono',monospace;word-break:break-all">${
          finding.page_url
            ? `<a href="${this.escapeHtml(finding.page_url)}" style="color:#5B9BF6">${this.escapeHtml(finding.page_url)}</a>`
            : '-'
        }</td>
        <td style="font-size:12px;color:#999999;white-space:pre-wrap;max-width:400px">${this.escapeHtml(this.exportDescription(finding))}</td>
        <td style="font-size:12px;color:#666666;font-family:'Space Mono',monospace">${
          this.lineOf(context, finding) > 0 ? `L${this.lineOf(context, finding)}` : '-'
        }</td>
      </tr>`,
      )
      .join('\n');

    const html = `<!DOCTYPE html>
<html lang="${language}">
<head><meta charset="utf-8"><title>${this.escapeHtml(this.i18n.t('audit.report_title'))}</title>
<style>
  :root { --accent:#D71921; --warning:#D4A843; --success:#4A9E5C; --interactive:#5B9BF6; }
  body { background:#000; color:#E8E8E8; font-family:'Space Grotesk',sans-serif; padding:40px; }
  h1 { font-size:24px; letter-spacing:-0.01em; margin:0 0 2px; }
  .sig { font-size:9px; color:#666666; margin:0 0 20px; letter-spacing:0.02em; }
  .meta { color:#999999; font-size:14px; margin-bottom:30px; }
  .meta span { margin-right:20px; }
  .summary { display:flex; gap:24px; margin-bottom:30px; }
  .stat { text-align:center; }
  .stat .num { font-size:36px; font-family:'Space Mono',monospace; }
  .stat .lbl { font-size:11px; text-transform:uppercase; letter-spacing:0.08em; color:#999999; }
  table { width:100%; border-collapse:collapse; }
  th { text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:0.08em; color:#999999; border-bottom:1px solid #333333; padding:12px 8px; }
  td { padding:10px 8px; border-bottom:1px solid #222222; font-size:14px; }
  code { font-family:'Space Mono',monospace; font-size:12px; color:#666666; }
  a { color:#5B9BF6; }
  .footer { margin-top:40px; padding-top:20px; border-top:1px solid #222222; color:#666666; font-size:12px; }
</style></head>
<body>
  <h1>${this.escapeHtml(this.i18n.t('audit.report_title'))}</h1>
  <div class="sig">— XWA submodule — Xscriptor</div>
  <div class="meta">
    <span>${this.i18n.t('audit.url')}: ${this.escapeHtml(context.url)}</span>
    <span>${this.i18n.t('audit.mode')}: ${this.i18n.t('audit.mode_' + context.mode)}</span>
    <span>${this.i18n.t('audit.date')}: ${new Date().toISOString()}</span>
    <span>${this.i18n.t('audit.findings')}: ${context.findings.length}</span>
  </div>
  <div class="summary">
    <div class="stat"><div class="num" style="color:var(--accent)">${counts.high + counts.critical}</div><div class="lbl">${this.i18n.t('audit.high')}</div></div>
    <div class="stat"><div class="num" style="color:var(--warning)">${counts.medium + counts.low}</div><div class="lbl">${this.i18n.t('audit.medium')}</div></div>
    <div class="stat"><div class="num" style="color:var(--interactive)">${counts.info}</div><div class="lbl">${this.i18n.t('audit.info')}</div></div>
    <div class="stat"><div class="num" style="color:var(--success)">${counts.pass}</div><div class="lbl">${this.i18n.t('audit.passed')}</div></div>
  </div>
  <table><thead><tr><th>${this.i18n.t('audit.category')}</th><th>${this.i18n.t('audit.check')}</th><th>${this.i18n.t('audit.severity')}</th><th>${this.i18n.t('audit.col_title')}</th><th>${this.i18n.t('audit.page')}</th><th>${this.i18n.t('audit.description')}</th><th>${this.i18n.t('audit.line')}</th></tr></thead>
  <tbody>${findingsHtml}</tbody></table>
  <div class="footer">${this.i18n.t('audit.generated_by')}</div>
</body></html>`;

    this.downloadBlob(
      new Blob([html], { type: 'text/html;charset=utf-8' }),
      `${this.filenameStem('tengu-audit', context.url)}.html`,
    );
  }

  exportMd(context: AuditExportContext): void {
    const counts = severityCounts(context.findings);
    const lines: string[] = [];
    const separator = '---';

    lines.push(`# ${this.i18n.t('audit.report_title')}`);
    lines.push('');
    lines.push('*— XWA submodule — Xscriptor*');
    lines.push('');
    lines.push(`**${this.i18n.t('audit.url')}:** ${context.url}`);
    lines.push(`**${this.i18n.t('audit.mode')}:** ${this.i18n.t('audit.mode_' + context.mode)}`);
    lines.push(`**${this.i18n.t('audit.date')}:** ${new Date().toISOString()}`);
    lines.push(`**${this.i18n.t('audit.total_findings')}:** ${context.findings.length}`);
    lines.push('');
    lines.push(separator);
    lines.push('');
    lines.push(`## ${this.i18n.t('audit.summary')}`);
    lines.push('');
    lines.push(`| ${this.i18n.t('audit.severity')} | ${this.i18n.t('audit.count')} |`);
    lines.push('|----------|-------|');
    for (const severity of ['high', 'medium', 'low', 'info', 'pass', 'critical'] as Severity[]) {
      lines.push(`| ${severity.toUpperCase()} | ${counts[severity]} |`);
    }
    lines.push('');
    lines.push(separator);
    lines.push('');
    lines.push(`## ${this.i18n.t('audit.findings')}`);
    lines.push('');
    lines.push(
      `| ${this.i18n.t('audit.category')} | ${this.i18n.t('audit.check')} | ${this.i18n.t('audit.severity')} | ${this.i18n.t('audit.col_title')} | ${this.i18n.t('audit.page')} | ${this.i18n.t('audit.line')} |`,
    );
    lines.push('|----------|-------|----------|-------|------|------|');

    for (const finding of context.findings) {
      const category = this.categoryLabel(finding.category);
      const title = this.exportTitle(finding).replace(/\|/g, '\\|');
      const pageUrl = (finding.page_url || context.url)
        .replace(/^https?:\/\//, '')
        .replace(/\|/g, '\\|');
      const line = this.lineOf(context, finding);
      lines.push(
        `| ${category} | \`${finding.check}\` | ${finding.severity.toUpperCase()} | ${title} | ${pageUrl} | ${line > 0 ? line : '-'} |`,
      );
    }

    lines.push('');
    lines.push(separator);
    lines.push('');
    lines.push(`*${this.i18n.t('audit.generated_by')}*`);

    this.downloadBlob(
      new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' }),
      `${this.filenameStem('tengu-audit', context.url)}.md`,
    );
  }

  categoryLabel(category: string): string {
    return category.replace(/_/g, '-').toUpperCase();
  }

  private exportTitle(finding: FindingView): string {
    if (this.i18n.isEn()) {
      return finding.title;
    }
    return FINDING_TITLES_ES[finding.check] ?? finding.title;
  }

  private exportDescription(finding: FindingView): string {
    if (this.i18n.isEn()) {
      return finding.description;
    }
    return FINDING_DESCRIPTIONS_ES[finding.check] ?? finding.description;
  }

  private lineOf(context: AuditExportContext, finding: FindingView): number {
    return locateLine(htmlLines(context.html), finding.snippet);
  }

  private lighthouseScore(severity: Severity): number | null {
    switch (severity) {
      case 'pass':
        return 1;
      case 'low':
        return 0.75;
      case 'medium':
        return 0.5;
      case 'high':
      case 'critical':
        return 0;
      default:
        return null;
    }
  }

  private csvCell(value: string): string {
    return `"${String(value ?? '')
      .replace(/"/g, '""')
      .replace(/\n/g, '\\n')
      .replace(/\r/g, '\\r')}"`;
  }

  private escapeHtml(value: string): string {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  private filenameStem(prefix: string, url: string): string {
    return `${prefix}-${url.replace(/[^a-z0-9]/gi, '-')}`;
  }

  private downloadBlob(blob: Blob, filename: string): void {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.rel = 'noopener';
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }
}

const FINDING_TITLES_ES: Record<string, string> = {
  alt_text: 'Imagen(es) sin texto alternativo',
  headings_outline: 'La estructura de encabezados salta uno o más niveles',
  aria_roles: "role='button' en elemento no interactivo sin tabindex",
  aria_usage: 'No se detectaron atributos ARIA en la página',
  landmarks: 'No se encontraron regiones landmark',
  form_labels: 'Control(es) de formulario sin etiqueta accesible',
  keyboard_nav: 'Elemento(s) con valores positivos de tabindex',
  link_text: 'El texto del enlace es genérico o no descriptivo',
  tables: 'Falta <caption> en tabla de datos',
  iframes: 'Iframe sin atributo title',
  viewport: 'La meta etiqueta viewport impide el zoom',
  lang_attribute: 'Falta atributo lang en <html>',
  media_captions: 'Elemento(s) multimedia sin subtítulos',
  color_contrast: 'Elemento(s) con contraste de color insuficiente',
  color_contrast_bg_image:
    'Elemento(s) con imagen de fondo — el contraste no se puede medir estáticamente',
  focus_indicator: 'Elemento(s) enfocables con outline:none',
  https: 'Página servida sobre HTTP inseguro',
  security_headers: 'Falta cabecera de seguridad',
  cookies: 'Cookie sin atributo Secure',
  doctype: 'Falta o es incorrecta la declaración doctype',
  deprecated_html: 'Elemento(s) HTML obsoleto(s)',
  mixed_content: 'Contenido mixto detectado',
  sri: 'Recurso(s) externo(s) sin integridad de subrecursos',
  gdpr_consent: 'Mecanismo de consentimiento de cookies GDPR',
  csp: 'La política de seguridad de contenido tiene problemas de configuración',
  permissions_policy: 'Análisis de cabecera Permissions-Policy',
  page_weight: 'El peso de la página excede lo recomendado',
  image_audit: 'Problemas de optimización de imágenes',
  font_audit: 'Problemas de carga de fuentes',
  cache_header: 'Falta cabecera de caché',
  compression: 'Falta compresión',
  render_blocking: 'Recursos que bloquean el renderizado',
  third_party_scripts: 'Scripts de terceros detectados',
  web_vitals: 'LCP, CLS y INP requieren un navegador',
  title: 'Problema con la etiqueta title',
  meta_description: 'Problema con la meta descripción',
  heading: 'Problema con la jerarquía de encabezados',
  canonical: 'Problema con la URL canónica',
  open_graph: 'Problema con etiquetas Open Graph',
  twitter_card: 'Problema con Twitter Card',
  json_ld: 'Problema con datos estructurados JSON-LD',
  meta_robots: 'Problema con la etiqueta meta robots',
  hreflang: 'Problema con etiquetas hreflang',
  robots_txt: 'Problemas de configuración en robots.txt',
  sitemap: 'Problema con el sitemap',
  broken_links: 'Enlace(s) rotos encontrados',
  redirect_chain: 'Cadena de redirecciones detectada',
  structured_data_microdata: 'Datos estructurados Microdata/RDFa',
  console_errors: 'La detección de errores de consola requiere un navegador',
};

const FINDING_DESCRIPTIONS_ES: Record<string, string> = {
  color_contrast:
    'Se encontraron elementos con contraste de color insuficiente entre el texto y el fondo. tamaños de texto grandes (≥18pt o ≥14pt bold): 3:1.',
  color_contrast_bg_image:
    'Se encontraron elementos de texto con una imagen de fondo CSS. El análisis estático no puede medir el contraste.',
  https: 'La página se sirve sobre HTTP sin cifrar. Esto es un problema crítico de seguridad y SEO.',
  alt_text:
    'Se encontraron imágenes sin atributo alt. Los lectores de pantalla no pueden describir el contenido.',
  headings_outline: 'La página no tiene elementos de encabezado (h1–h6) o la jerarquía es incorrecta.',
  form_labels: 'Se encontraron controles de formulario sin etiqueta accesible.',
  landmarks: 'La página no usa elementos landmark HTML5 o roles ARIA landmark.',
  viewport: 'La etiqueta meta viewport impide el zoom en dispositivos móviles.',
  lang_attribute: 'El elemento <html> no tiene atributo lang.',
  focus_indicator: 'Se encontraron elementos enfocables con outline:none.',
  broken_links: 'Se encontraron enlaces rotos en la página.',
  redirect_chain: 'La URL pasa por múltiples redirecciones antes de llegar al destino final.',
};
