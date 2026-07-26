import { AfterViewInit, Component, ElementRef, OnDestroy, ViewChild, computed, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { ShootingRangeGame, type DifficultyLevel, type ShootingRangeStats } from '../shooting-range/game';
import { ShootOffSocketService } from '../service/shootoff-socket.service';

type LevelObjective = 'score' | 'wave-clear';

interface LevelConfiguration {
  objective: LevelObjective;
  targetScore?: number;
  objectiveLabel: string;
}

interface LevelPerformanceReport {
  level: number;
  outcomeLabel: 'Completed' | 'Failed';
  difficulty: DifficultyLevel;
  objective: string;
  completionLabel: string;
  completedAtLabel: string;
  elapsedTimeLabel: string;
  elapsedSeconds: number;
  finalScore: number;
  shots: number;
  hits: number;
  misses: number;
  accuracy: number;
  pointsPerShot: number;
  hitsPerMinute: number;
}

interface ShotDebugInfo {
  arenaX: number;
  arenaY: number;
  worldX: number;
  worldY: number;
  rawX?: number;
  rawY?: number;
  color?: string;
  confidence?: number;
  pointerDispatched: boolean;
}

type CalibrationState = 'idle' | 'manual_adjusting' | 'calibrated' | 'calibration_failed' | 'error';
type CalibrationMode = 'manual' | 'cached' | 'zhang_4pt' | 'zhang_2pt_affine';
type CalibrationBBox = [number, number, number, number];

const LEVEL_CONFIGS: Partial<Record<number, LevelConfiguration>> = {
  1: {
    objective: 'score',
    targetScore: 180,
    objectiveLabel: 'Target score: 180',
  },
  2: {
    objective: 'score',
    targetScore: 220,
    objectiveLabel: 'Target score: 220',
  },
  3: {
    objective: 'wave-clear',
    objectiveLabel: 'Objective: clear waves 1 to 4',
  },
  4: {
    objective: 'wave-clear',
    objectiveLabel: 'Objective: clear waves 1 to 4',
  },
  5: {
    objective: 'score',
    targetScore: 200,
    objectiveLabel: 'Target score: 200',
  },
  6: {
    objective: 'wave-clear',
    objectiveLabel: 'Objective: 20 random images, terrorist +50 / innocent -50',
  },
};

const TOTAL_LEVEL_OPTIONS = 7;
const EDITABLE_TARGET_SCORE_LEVELS = [1, 2] as const;
const TARGET_SCORE_MIN = 50;
const TARGET_SCORE_MAX = 1000;
const TARGET_SCORE_STEP = 10;
const SHOOTOFF_ARENA_WIDTH = 800;
const SHOOTOFF_ARENA_HEIGHT = 600;
const MANUAL_CALIBRATION_REASON = 'Green screen active. Adjust the arena manually in the backend preview window, then press Enter to accept.';

function createDefaultLevelDifficulties(): Record<number, DifficultyLevel> {
  return Object.fromEntries(
    Array.from({ length: TOTAL_LEVEL_OPTIONS }, (_, index) => [index + 1, 'Medium']),
  ) as Record<number, DifficultyLevel>;
}

function createDefaultEditableTargetScores(): Record<number, number> {
  const level1Score = LEVEL_CONFIGS[1]?.targetScore ?? 180;
  const level2Score = LEVEL_CONFIGS[2]?.targetScore ?? 220;

  return {
    1: level1Score,
    2: level2Score,
  };
}

@Component({
  selector: 'app-exercice',
  templateUrl: './exercice.html',
  styleUrl: './exercice.scss',
})
export class ExerciceComponent implements AfterViewInit, OnDestroy {
  @ViewChild('pixiHost', { static: true }) private readonly pixiHost!: ElementRef<HTMLDivElement>;

  private readonly shootOffSocketService = inject(ShootOffSocketService);

  protected readonly levelOptions = Array.from({ length: TOTAL_LEVEL_OPTIONS }, (_, index) => index + 1);
  protected readonly difficultyOptions: DifficultyLevel[] = ['Easy', 'Medium', 'Hard'];

  protected readonly selectedDifficultyLevel = signal(1);
  protected readonly isLevelsMenuOpen = signal(false);
  protected readonly levelDifficultyMap = signal<Record<number, DifficultyLevel>>(createDefaultLevelDifficulties());
  protected readonly editableTargetScoreMap = signal<Record<number, number>>(createDefaultEditableTargetScores());
  protected readonly selectedLevelConfiguration = computed(() => LEVEL_CONFIGS[this.selectedDifficultyLevel()]);

  protected readonly isSelectedDifficultyAvailable = computed(() => this.hasLevelConfiguration(this.selectedDifficultyLevel()));
  protected readonly targetScore = computed(() => this.resolveTargetScore(this.selectedDifficultyLevel()));
  protected readonly objectiveLabel = computed(() => {
    const selectedLevel = this.selectedDifficultyLevel();
    const levelConfiguration = LEVEL_CONFIGS[selectedLevel];

    if (!levelConfiguration) {
      return 'No objective';
    }

    if (levelConfiguration.objective === 'score') {
      return `Target score: ${this.resolveTargetScore(selectedLevel)}`;
    }

    return levelConfiguration.objectiveLabel;
  });
  protected readonly selectedLevelDifficulty = computed(() => this.levelDifficultyMap()[this.selectedDifficultyLevel()] ?? 'Medium');
  protected readonly isTargetScoreEditorVisible = computed(() => this.isEditableTargetScoreLevel(this.selectedDifficultyLevel()));
  protected readonly selectedEditableTargetScore = computed(() => this.resolveTargetScore(this.selectedDifficultyLevel()));

  protected readonly shots = signal(0);
  protected readonly hits = signal(0);
  protected readonly score = signal(0);
  protected readonly points = signal(0);
  protected readonly elapsedSeconds = signal(0);
  protected readonly isSessionRunning = signal(false);
  protected readonly calibrationState = signal<CalibrationState>('idle');
  protected readonly calibrationErrorMessage = signal<string | null>(null);
  protected readonly calibrationMode = signal<CalibrationMode | null>(null);
  protected readonly calibrationBbox = signal<CalibrationBBox | null>(null);
  protected readonly calibrationConfidence = signal<number | null>(null);
  protected readonly calibrationHasHomography = signal<boolean | null>(null);
  protected readonly calibrationReason = signal<string | null>(null);
  protected readonly calibrationElapsedSeconds = signal<number | null>(null);
  private readonly shootOffArenaWidth = signal(SHOOTOFF_ARENA_WIDTH);
  private readonly shootOffArenaHeight = signal(SHOOTOFF_ARENA_HEIGHT);
  protected readonly lastShotDebug = signal<ShotDebugInfo | null>(null);
  protected readonly calibrationMessage = computed(() => {
    const state = this.calibrationState();

    if (state === 'manual_adjusting') {
      const bboxLabel = this.formatCalibrationBbox(this.calibrationBbox());
      const reason = this.calibrationReason() ?? MANUAL_CALIBRATION_REASON;

      return `Manual calibration active${bboxLabel ? ` for bbox ${bboxLabel}` : ''}. ${reason}`;
    }

    if (state === 'calibrated') {
      const confidence = this.calibrationConfidence();
      const confidenceLabel = confidence === null ? 'unknown confidence' : `confidence ${this.formatCalibrationConfidence(confidence)}`;
      const bboxLabel = this.formatCalibrationBbox(this.calibrationBbox());
      const hasHomography = this.calibrationHasHomography();

      const details = [confidenceLabel];
      if (hasHomography !== null && hasHomography !== undefined) {
        details.push(hasHomography ? 'homography' : 'bbox only');
      }

      return `Calibration locked with ${details.join(', ')}${bboxLabel ? `, bbox ${bboxLabel}.` : '.'}`;
    }

    if (state === 'calibration_failed') {
      return this.calibrationReason() ? `Calibration failed: ${this.calibrationReason()}` : 'Calibration failed.';
    }

    if (state === 'error') {
      return this.calibrationErrorMessage() ?? 'Calibration failed.';
    }

    return '';
  });
  protected readonly isCalibrationRunning = computed(() => {
    const state = this.calibrationState();
    return state === 'manual_adjusting';
  });
  protected readonly timerLabel = computed(() => this.formatElapsedTime(this.elapsedSeconds()));
  protected readonly accuracy = computed(() => {
    const totalShots = this.shots();
    if (totalShots === 0) {
      return 0;
    }

    return Math.round((this.hits() / totalShots) * 100);
  });
  protected readonly levelReport = signal<LevelPerformanceReport | undefined>(undefined);
  protected readonly isLevelReportVisible = signal(false);
  protected readonly calibrationStateLabel = computed(() => {
    const state = this.calibrationState();

    switch (state) {
      case 'manual_adjusting':
        return 'Manual';
      case 'calibrated':
        return 'Locked';
      case 'calibration_failed':
        return 'Failed';
      case 'error':
        return 'Error';
      default:
        return 'Idle';
    }
  });
  protected readonly calibrationModeLabel = computed(() => this.formatCalibrationMode(this.calibrationMode()));
  protected readonly calibrationConfidenceLabel = computed(() => this.formatCalibrationConfidence(this.calibrationConfidence()));
  protected readonly calibrationBboxLabel = computed(() => this.formatCalibrationBbox(this.calibrationBbox()) ?? '--');
  protected readonly calibrationHomographyLabel = computed(() => this.formatCalibrationHomography(this.calibrationHasHomography()));
  protected readonly calibrationElapsedLabel = computed(() => {
    const elapsedSeconds = this.calibrationElapsedSeconds();

    if (elapsedSeconds === null || elapsedSeconds === undefined) {
      return '--';
    }

    return `${this.roundToSingleDecimal(elapsedSeconds)}s`;
  });
  protected readonly isCalibrationOverlayVisible = computed(() => {
    const state = this.calibrationState();
    return state === 'manual_adjusting';
  });

  private game?: ShootingRangeGame;
  private sessionTimerId: number | undefined;
  private hasPublishedCompletionForSession = false;
  private shotStream?: Subscription;
  private calibrationStream?: Subscription;

  async ngAfterViewInit(): Promise<void> {
    if (!this.canBootstrapPixi()) {
      return;
    }

    await this.initializeGame();
  }

  ngOnDestroy(): void {
    this.stopTimer();
    this.stopCalibrationStream();
    this.game?.destroy();
  }

  protected chooseLevel(level: number): void {
    this.selectedDifficultyLevel.set(level);
    this.isLevelsMenuOpen.set(false);
    this.restartSession();
  }

  protected toggleLevelsMenu(): void {
    this.isLevelsMenuOpen.update((value) => !value);
  }

  protected chooseCurrentLevelDifficulty(difficulty: DifficultyLevel): void {
    const selectedLevel = this.selectedDifficultyLevel();

    this.levelDifficultyMap.update((currentMap) => ({
      ...currentMap,
      [selectedLevel]: difficulty,
    }));
    this.restartSession();
  }

  protected getLevelDifficulty(level: number): DifficultyLevel {
    return this.levelDifficultyMap()[level] ?? 'Medium';
  }

  protected startSession(): void {
    if (
      !this.game
      || !this.isSelectedDifficultyAvailable()
      || this.isSessionRunning()
      || this.calibrationState() !== 'calibrated'
    ) {
      return;
    }

    this.clearLevelReport();
    this.stopCalibrationStream();
    this.game.setPlayerInShootingArea(true);
    this.startTimer();
    this.syncArenaSizeFromHost();
    this.startShotStream();
  }

  protected restartSession(): void {
    this.clearLevelReport();
    this.stopTimer();
    this.stopCalibrationStream();
    this.elapsedSeconds.set(0);
    this.lastShotDebug.set(null);
    this.game?.setPlayerInShootingArea(false);
    this.game?.resetSession();
    this.applySelectedLevelConfiguration();
  }

  protected startCalibration(): void {
    if (this.calibrationStream) {
      return;
    }

    this.calibrationErrorMessage.set(null);
    this.resetCalibrationMetadata();
    this.calibrationState.set('manual_adjusting');
    this.calibrationReason.set(MANUAL_CALIBRATION_REASON);
    this.stopShotStream();

    const arena = this.syncArenaSizeFromHost();
    const socketOptions = {
      debugPreview: true,
      calibrate: true,
      arenaWidth: arena.width,
      arenaHeight: arena.height,
    };

    console.log('[ExerciceComponent] Starting calibration with arena options:', socketOptions);

    const calibrationObs = this.shootOffSocketService.connect(socketOptions);

    this.calibrationStream = calibrationObs.subscribe({
      next: (message) => {
        if (this.shootOffSocketService.isErrorMessage(message)) {
          console.error('[ExerciceComponent] Calibration error received:', message);
          this.setCalibrationError(message.error);
          return;
        }

        if (this.shootOffSocketService.isCalibrationStatus(message)) {
          console.log('[ExerciceComponent] Calibration status received:', message);
          this.handleCalibrationMessage(message);
        }
      },
      error: () => {
        console.error('[ExerciceComponent] Calibration stream error');
        this.setCalibrationError('Calibration failed to start.');
      },
      complete: () => {
        console.log('[ExerciceComponent] Calibration stream completed');
        if (this.calibrationState() === 'manual_adjusting') {
          this.setCalibrationError('Calibration stopped.');
        }
      },
    });
  }

  protected closeLevelReport(): void {
    this.restartSession();
  }

  protected goToNextLevel(): void {
    const nextLevel = this.findNextConfiguredLevel();

    if (!nextLevel) {
      this.closeLevelReport();
      return;
    }

    this.selectedDifficultyLevel.set(nextLevel);
    this.isLevelsMenuOpen.set(false);
    this.restartSession();
  }

  protected canGoToNextLevel(): boolean {
    return this.findNextConfiguredLevel() !== undefined;
  }

  protected increaseSelectedLevelTargetScore(): void {
    this.adjustSelectedLevelTargetScore(TARGET_SCORE_STEP);
  }

  protected decreaseSelectedLevelTargetScore(): void {
    this.adjustSelectedLevelTargetScore(-TARGET_SCORE_STEP);
  }

  protected updateSelectedLevelTargetScore(rawValue: string): void {
    const selectedLevel = this.selectedDifficultyLevel();

    if (!this.isEditableTargetScoreLevel(selectedLevel)) {
      return;
    }

    const parsedValue = Number(rawValue);

    if (!Number.isFinite(parsedValue)) {
      return;
    }

    this.setEditableTargetScore(selectedLevel, parsedValue);
  }

  protected isLevelEmpty(level: number): boolean {
    return !this.hasLevelConfiguration(level);
  }

  private async initializeGame(): Promise<void> {
    this.game = new ShootingRangeGame({
      host: this.pixiHost.nativeElement,
      onStatsChange: this.syncStats,
      onLevelComplete: this.handleLevelComplete,
      onSessionStopped: this.handleSessionStopped,
    });

    await this.game.init();
    this.applySelectedLevelConfiguration();
    this.game.setPlayerInShootingArea(false);
  }

  private canBootstrapPixi(): boolean {
    if (typeof window === 'undefined' || typeof document === 'undefined') {
      return false;
    }

    const testCanvas = document.createElement('canvas');

    return Boolean(testCanvas.getContext('2d'));
  }

  private readonly syncStats = (stats: ShootingRangeStats): void => {
    this.shots.set(stats.shots);
    this.hits.set(stats.hits);
    this.score.set(stats.score);
    this.points.set(stats.points);

    const levelConfiguration = this.selectedLevelConfiguration();
    if (!levelConfiguration || levelConfiguration.objective !== 'score') {
      return;
    }

    const targetScore = this.resolveTargetScore(this.selectedDifficultyLevel());
    if (targetScore <= 0) {
      return;
    }

    if (stats.score >= targetScore) {
      this.completeCurrentLevel('Target score reached');
    }
  };

  private readonly handleLevelComplete = (level: number): void => {
    if (level !== this.selectedDifficultyLevel()) {
      return;
    }

    this.completeCurrentLevel('Objective completed');
  };

  private readonly handleSessionStopped = (): void => {
    if (this.isSessionRunning()) {
      this.stopTimer();
    }

    const currentLevel = this.selectedDifficultyLevel();
    const isAllyProtectionLevel = currentLevel === 2 || currentLevel === 4;

    if (!isAllyProtectionLevel || this.hasPublishedCompletionForSession) {
      return;
    }

    this.hasPublishedCompletionForSession = true;
    this.publishLevelReport('u fail u killed an ally', 'Failed');
  };

  private completeCurrentLevel(completionLabel: string): void {
    if (this.hasPublishedCompletionForSession) {
      return;
    }

    this.hasPublishedCompletionForSession = true;

    this.stopTimer();
    this.game?.setPlayerInShootingArea(false);
    this.publishLevelReport(completionLabel, 'Completed');
  }

  private publishLevelReport(
    completionLabel: string,
    outcomeLabel: 'Completed' | 'Failed',
  ): void {
    const shots = this.shots();
    const hits = this.hits();
    const misses = Math.max(shots - hits, 0);
    const elapsedSeconds = this.elapsedSeconds();
    const finalScore = this.score();
    const objective = this.objectiveLabel();
    const pointsPerShot = shots > 0 ? finalScore / shots : 0;
    const hitsPerMinute = elapsedSeconds > 0 ? (hits * 60) / elapsedSeconds : 0;

    this.levelReport.set({
      level: this.selectedDifficultyLevel(),
      outcomeLabel,
      difficulty: this.selectedLevelDifficulty(),
      objective,
      completionLabel,
      completedAtLabel: new Date().toLocaleString(),
      elapsedTimeLabel: this.formatElapsedTime(elapsedSeconds),
      elapsedSeconds,
      finalScore,
      shots,
      hits,
      misses,
      accuracy: this.accuracy(),
      pointsPerShot: this.roundToSingleDecimal(pointsPerShot),
      hitsPerMinute: this.roundToSingleDecimal(hitsPerMinute),
    });

    this.isLevelReportVisible.set(true);
  }

  private clearLevelReport(): void {
    this.hasPublishedCompletionForSession = false;
    this.levelReport.set(undefined);
    this.isLevelReportVisible.set(false);
  }

  private applySelectedLevelConfiguration(): void {
    this.game?.setLevel(this.selectedDifficultyLevel());
    this.game?.setDifficulty(this.selectedLevelDifficulty());
  }

  private hasLevelConfiguration(level: number): boolean {
    return Boolean(LEVEL_CONFIGS[level]);
  }

  private isEditableTargetScoreLevel(level: number): boolean {
    return EDITABLE_TARGET_SCORE_LEVELS.includes(level as (typeof EDITABLE_TARGET_SCORE_LEVELS)[number]);
  }

  private resolveTargetScore(level: number): number {
    const levelConfiguration = LEVEL_CONFIGS[level];

    if (!levelConfiguration || levelConfiguration.objective !== 'score') {
      return 0;
    }

    if (!this.isEditableTargetScoreLevel(level)) {
      return levelConfiguration.targetScore ?? 0;
    }

    return this.editableTargetScoreMap()[level] ?? levelConfiguration.targetScore ?? 0;
  }

  private adjustSelectedLevelTargetScore(delta: number): void {
    const selectedLevel = this.selectedDifficultyLevel();

    if (!this.isEditableTargetScoreLevel(selectedLevel)) {
      return;
    }

    this.setEditableTargetScore(selectedLevel, this.resolveTargetScore(selectedLevel) + delta);
  }

  private setEditableTargetScore(level: number, value: number): void {
    const clampedScore = this.clamp(Math.round(value), TARGET_SCORE_MIN, TARGET_SCORE_MAX);

    this.editableTargetScoreMap.update((currentMap) => ({
      ...currentMap,
      [level]: clampedScore,
    }));
  }

  private findNextConfiguredLevel(): number | undefined {
    const currentLevel = this.selectedDifficultyLevel();

    for (let level = currentLevel + 1; level <= TOTAL_LEVEL_OPTIONS; level += 1) {
      if (this.hasLevelConfiguration(level)) {
        return level;
      }
    }

    return undefined;
  }

  private syncArenaSizeFromHost(): { width: number; height: number } {
    const host = this.pixiHost?.nativeElement;
    if (!host) {
      console.warn('[ExerciceComponent] pixiHost not available, using default arena size');
      return { width: this.shootOffArenaWidth(), height: this.shootOffArenaHeight() };
    }

    const rect = host.getBoundingClientRect();
    const width = Math.round(rect.width);
    const height = Math.round(rect.height);

    if (width > 0 && height > 0) {
      const oldWidth = this.shootOffArenaWidth();
      const oldHeight = this.shootOffArenaHeight();
      
      this.shootOffArenaWidth.set(width);
      this.shootOffArenaHeight.set(height);
      
      if (oldWidth !== width || oldHeight !== height) {
        console.log(
          `[ExerciceComponent] Arena size synced from host: ${oldWidth}x${oldHeight} → ${width}x${height}`,
          { rect, width, height }
        );
      }
      return { width, height };
    }

    console.warn('[ExerciceComponent] Invalid arena dimensions from host', { width, height, rect });
    return { width: this.shootOffArenaWidth(), height: this.shootOffArenaHeight() };
  }

  private startShotStream(): void {
    if (this.shotStream || !this.game) {
      return;
    }

    const arena = this.syncArenaSizeFromHost();
    console.log('[ExerciceComponent] Starting shot stream with arena size:', arena);
    
    this.shotStream = this.shootOffSocketService
      .connectToShots({ arenaWidth: arena.width, arenaHeight: arena.height })
      .subscribe({
        next: (message) => {
          const arenaWidth = this.shootOffArenaWidth();
          const arenaHeight = this.shootOffArenaHeight();
          
          // Debug: Log shot with arena dimensions
          console.log(
            `[ExerciceComponent] Shot received - Arena: ${arenaWidth}x${arenaHeight}, Shot coords: (${message.x.toFixed(2)}, ${message.y.toFixed(2)})`,
            { message, arenaWidth, arenaHeight }
          );
          
          const result = this.game?.registerArenaShot(
            message.x,
            message.y,
            arenaWidth,
            arenaHeight,
          );

          if (result) {
            console.log(
              `[ExerciceComponent] Shot mapped to world coords: (${result.worldX.toFixed(2)}, ${result.worldY.toFixed(2)})`,
              { result }
            );
            
            this.lastShotDebug.set({
              arenaX: message.x,
              arenaY: message.y,
              worldX: result.worldX,
              worldY: result.worldY,
              rawX: message.raw_x,
              rawY: message.raw_y,
              color: message.color,
              confidence: message.confidence,
              pointerDispatched: result.pointerDispatched,
            });
          }
        },
        error: (err) => {
          console.error('[ExerciceComponent] Shot stream error:', err);
          this.shotStream = undefined;
        },
        complete: () => {
          console.log('[ExerciceComponent] Shot stream completed');
          this.shotStream = undefined;
        },
      });
  }

  private stopShotStream(): void {
    if (!this.shotStream) {
      return;
    }

    this.shotStream.unsubscribe();
    this.shotStream = undefined;
  }

  private stopCalibrationStream(): void {
    if (!this.calibrationStream) {
      return;
    }

    this.calibrationStream.unsubscribe();
    this.calibrationStream = undefined;
  }

  private setCalibrationError(message: string): void {
    this.calibrationErrorMessage.set(message);
    this.resetCalibrationMetadata();
    this.calibrationState.set('error');
    this.stopCalibrationStream();
  }

  private handleCalibrationMessage(message: {
    status: 'manual_adjusting' | 'calibrated' | 'calibration_failed';
    bbox?: CalibrationBBox;
    mode?: CalibrationMode;
    reason?: string;
    confidence?: number;
    elapsed_seconds?: number;
    arena_w?: number;
    arena_h?: number;
    has_homography?: boolean;
  }): void {
    this.calibrationMode.set(message.mode ?? this.calibrationMode());

    if (message.arena_w !== undefined && Number.isFinite(message.arena_w) && message.arena_w > 0) {
      const oldWidth = this.shootOffArenaWidth();
      this.shootOffArenaWidth.set(message.arena_w);
      console.log(
        `[ExerciceComponent] Arena width updated from server: ${oldWidth} → ${message.arena_w}`,
        { arena_w: message.arena_w }
      );
    }
    if (message.arena_h !== undefined && Number.isFinite(message.arena_h) && message.arena_h > 0) {
      const oldHeight = this.shootOffArenaHeight();
      this.shootOffArenaHeight.set(message.arena_h);
      console.log(
        `[ExerciceComponent] Arena height updated from server: ${oldHeight} → ${message.arena_h}`,
        { arena_h: message.arena_h }
      );
    }

    if (message.confidence !== undefined && Number.isFinite(message.confidence)) {
      this.calibrationConfidence.set(this.clamp(message.confidence, 0, 1));
    }

    if (message.has_homography !== undefined) {
      this.calibrationHasHomography.set(Boolean(message.has_homography));
    }

    if (message.bbox) {
      this.calibrationBbox.set(message.bbox);
    }

    if (message.elapsed_seconds !== undefined && Number.isFinite(message.elapsed_seconds)) {
      this.calibrationElapsedSeconds.set(message.elapsed_seconds);
    }

    if (message.status === 'manual_adjusting') {
      this.calibrationState.set('manual_adjusting');
      this.calibrationReason.set(
        message.reason ?? MANUAL_CALIBRATION_REASON
      );
      return;
    }

    if (message.status === 'calibration_failed') {
      this.calibrationState.set('calibration_failed');
      this.calibrationReason.set(message.reason ?? 'Calibration timed out.');
      this.stopCalibrationStream();
      return;
    }

    this.calibrationState.set('calibrated');
    this.calibrationReason.set(message.reason ?? null);
    this.stopCalibrationStream();
  }


  private resetCalibrationMetadata(): void {
    this.calibrationMode.set(null);
    this.calibrationBbox.set(null);
    this.calibrationConfidence.set(null);
    this.calibrationHasHomography.set(null);
    this.calibrationReason.set(null);
    this.calibrationElapsedSeconds.set(null);
  }

  private startTimer(): void {
    if (this.sessionTimerId !== undefined) {
      return;
    }

    this.isSessionRunning.set(true);
    this.sessionTimerId = window.setInterval(() => {
      this.elapsedSeconds.update((value) => value + 1);
    }, 1000);
  }

  private stopTimer(): void {
    if (this.sessionTimerId !== undefined) {
      window.clearInterval(this.sessionTimerId);
      this.sessionTimerId = undefined;
    }

    this.isSessionRunning.set(false);
    this.stopShotStream();
  }

  private formatCalibrationConfidence(confidence: number | null): string {
    if (confidence === null || confidence === undefined || !Number.isFinite(confidence)) {
      return '--';
    }

    return confidence.toFixed(3);
  }

  private formatCalibrationMode(mode: CalibrationMode | null): string {
    if (!mode) {
      return '--';
    }

    switch (mode) {
      case 'zhang_4pt':
        return 'Zhang 4pt';
      case 'zhang_2pt_affine':
        return 'Zhang 2pt (affine)';
      case 'cached':
        return 'Cached';
      case 'manual':
        return 'Manual';
      default:
        return mode;
    }
  }

  private formatCalibrationHomography(value: boolean | null): string {
    if (value === null || value === undefined) {
      return '--';
    }

    return value ? 'yes' : 'no';
  }

  private formatCalibrationBbox(bbox: CalibrationBBox | null): string | null {
    if (!bbox) {
      return null;
    }

    const [left, top, right, bottom] = bbox;
    return `${left}, ${top} -> ${right}, ${bottom}`;
  }

  private formatElapsedTime(totalSeconds: number): string {
    const minutes = Math.floor(totalSeconds / 60).toString().padStart(2, '0');
    const seconds = (totalSeconds % 60).toString().padStart(2, '0');

    return `${minutes}:${seconds}`;
  }

  private roundToSingleDecimal(value: number): number {
    return Math.round(value * 10) / 10;
  }

  private clamp(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, value));
  }
}
