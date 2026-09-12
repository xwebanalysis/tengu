import { Pipe, PipeTransform } from '@angular/core';

import { TranslateService } from '../../core/i18n.service';

@Pipe({
  name: 't',
  standalone: true,
  pure: false,
})
export class TranslatePipe implements PipeTransform {
  constructor(private readonly translate: TranslateService) {}

  transform(key: string): string {
    return this.translate.t(key);
  }
}
