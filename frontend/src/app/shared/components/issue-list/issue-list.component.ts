import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  input,
  output,
  signal,
} from '@angular/core';

import { AnalysisIssue, Correction } from '../../../core/api/api.types';
import { BadgeComponent } from '../badge/badge.component';
import { ButtonComponent } from '../button/button.component';
import { createFieldId } from '../field/field-id';
import { IconComponent } from '../icon/icon.component';
import { CorrectionPanelComponent } from '../correction-panel/correction-panel.component';
import { languageLabel } from '../language-select/language-options';
import {
  ADVPL_DISCLAIMER,
  causeLabel,
  isAdvplIssue,
  issueLanguage,
  issueLocation,
  originBadge,
  severityLabel,
  severityTone,
  sortIssues,
} from './issue-presentation';

/**
 * Accessible issue list shared by the live result and the persisted detail.
 *
 * Each issue exposes its severity, message, translated cause, location and
 * origin. When correction is enabled, one issue at a time expands an AI
 * correction panel inline.
 */
@Component({
  selector: 'app-issue-list',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [BadgeComponent, ButtonComponent, CorrectionPanelComponent, IconComponent],
  templateUrl: './issue-list.component.html',
  styleUrl: './issue-list.component.css',
})
export class IssueListComponent {
  readonly issues = input<readonly AnalysisIssue[]>([]);
  readonly source = input('');
  readonly language = input<string | null>(null);
  readonly file = input<string | null>(null);
  readonly analysisId = input<string | null>(null);
  readonly protheusVersion = input<string | null>(null);
  readonly authenticated = input(false);
  readonly showCorrection = input(true);

  readonly loginRequested = output<void>();
  readonly decided = output<Correction>();

  private readonly listId = createFieldId('issues');
  protected readonly openIndex = signal<number | null>(null);
  protected readonly fullPanelOpen = signal(false);
  protected readonly fullBusy = signal(false);
  protected readonly fullRequestToken = signal(0);
  private lastIssues: readonly AnalysisIssue[] | null = null;

  constructor() {
    // The component is reused when a result with the same shape replaces the
    // previous one (for example switching analysis tabs). The expanded index
    // belongs to the old list and must be collapsed on an identity change.
    effect(() => {
      const issues = this.issues();
      if (issues === this.lastIssues) {
        return;
      }
      this.lastIssues = issues;
      this.openIndex.set(null);
      this.fullPanelOpen.set(false);
      this.fullBusy.set(false);
      // A stale token would make a freshly created full panel auto-request as
      // soon as a new list is rendered for the same component instance.
      this.fullRequestToken.set(0);
    });
  }

  protected readonly sortedIssues = computed(() => sortIssues(this.issues()));

  protected readonly hasAdvplIssue = computed(
    () =>
      (this.language() ?? '').trim().toLowerCase() === 'advpl' ||
      this.issues().some((issue) => isAdvplIssue(issue, this.language())),
  );

  protected readonly advplDisclaimer = ADVPL_DISCLAIMER;

  protected panelId(index: number): string {
    return `${this.listId}-panel-${index}`;
  }

  protected toggle(index: number): void {
    this.openIndex.update((current) => (current === index ? null : index));
  }

  protected canCorrect(): boolean {
    return this.showCorrection() && this.source().trim() !== '';
  }

  /**
   * Open the single full-mode panel and ask it to run one correction for every
   * listed issue. The token is what the panel observes; the header button owns
   * the loading/disabled state through `busyChange`.
   */
  protected requestAllCorrections(): void {
    if (!this.canCorrect() || this.fullBusy() || this.issues().length === 0) {
      return;
    }
    this.fullPanelOpen.set(true);
    this.fullRequestToken.update((value) => value + 1);
  }

  protected onFullBusy(busy: boolean): void {
    this.fullBusy.set(busy);
  }

  protected issueCause(issue: AnalysisIssue): string {
    return causeLabel(issue);
  }

  protected issuePosition(issue: AnalysisIssue): string {
    return issueLocation(issue, this.file());
  }

  protected issueLanguageName(issue: AnalysisIssue): string {
    const issueLanguageValue = issueLanguage(issue, this.language());
    return issueLanguageValue === '' ? '' : languageLabel(issueLanguageValue);
  }

  protected issueOrigin(issue: AnalysisIssue) {
    return originBadge(issue);
  }

  protected issueSeverityLabel(issue: AnalysisIssue): string {
    return severityLabel(issue);
  }

  protected issueSeverityTone(issue: AnalysisIssue) {
    return severityTone(issue);
  }

  protected issueIsAdvpl(issue: AnalysisIssue): boolean {
    return isAdvplIssue(issue, this.language());
  }

  protected forwardLogin(): void {
    this.loginRequested.emit();
  }

  protected forwardDecision(correction: Correction): void {
    this.decided.emit(correction);
  }
}
