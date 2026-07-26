import { Application, Assets, Container, Graphics, Point, Sprite, Texture, Ticker } from 'pixi.js';
import { BulletMark } from './bullet';
import { Score, type ScoreValue } from './score';
import { Target, type TargetLane } from './target';

// Shared asset paths used by all levels.
const TARGET_TEXTURE_PATH = 'assets/shooting-range/models/targetBoard_v2.png';
const BULLET_MARK_TEXTURE_PATH = 'assets/shooting-range/models/bulletMark.png';
const INNOCENT_TEXTURE_PATH = 'assets/shooting-range/models/innocent.png';
const BACKGROUND_TEXTURE_PATH = 'assets/shooting-range/background.png';
const BACKGROUND_LEVEL1_TEXTURE_PATH = 'assets/shooting-range/background_level1.png';
const BACKGROUND_LEVEL2_TEXTURE_PATH = 'assets/shooting-range/background_level_2.jpg';
const BACKGROUND_LEVEL6_TEXTURE_PATH = 'assets/shooting-range/background_level6.png';
const TERRORIST_TEXTURE_PATH = 'assets/shooting-range/terrorist.png';
const SHOT_SOUND_PATH = 'assets/shooting-range/sounds/shot.mp3';
const SHOT_FAIL_SOUND_PATH = 'assets/shooting-range/sounds/shotFail.mp3';

export type DifficultyLevel = 'Easy' | 'Medium' | 'Hard';

// Shared difficulty settings used by non-level-specific scenarios.
interface DifficultyConfig {
  speedMultiplier: number;
  sizeMultiplier: number;
}

// Level 1 target placement and sizing presets.
interface Level1TargetPreset {
  xRatio: number;
  yRatio: number;
  sizeRatio: number;
}

// Level 2 target placement and movement presets.
interface Level2TargetPreset {
  startXRatio: number;
  endXRatio: number;
  yRatio: number;
  sizeRatio: number;
  travelTimeSeconds: number;
}

interface InnocentPreset {
  xRatio: number;
  yRatio: number;
  sizeRatio: number;
  penalty: number;
}

interface InnocentPerson {
  container: Container;
  preset: InnocentPreset;
  hitRadius: number;
}

interface Level3TargetPreset {
  xRatio: number;
  yRatio: number;
  sizeRatio: number;
}

interface Level4TargetPreset {
  xRatio: number;
  yRatio: number;
  sizeRatio: number;
}

interface Level6SpawnPreset {
  xRatio: number;
  yRatio: number;
  sizeRatio: number;
}

type Level6ActorType = 'terrorist' | 'innocent';

interface Level6Encounter {
  container: Container;
  sprite: Sprite;
  actorType: Level6ActorType;
  elapsedMs: number;
  hit: boolean;
  fallElapsedMs: number;
  fallVelocityPerMs: number;
  fallRotationPerMs: number;
  hitMark?: BulletMark;
  hitMarkRemainingMs: number;
}

// Common default difficulty profile.
const DIFFICULTY_CONFIG: Record<DifficultyLevel, DifficultyConfig> = {
  Easy: { speedMultiplier: 0.8, sizeMultiplier: 1.6 },
  Medium: { speedMultiplier: 1, sizeMultiplier: 1.0 },
  Hard: { speedMultiplier: 1.35, sizeMultiplier: 0.4 },
};

// ---------------------------
// Level 1 preferences (static)
// ---------------------------
const LEVEL1_TARGET_PRESETS: Level1TargetPreset[] = [
  { xRatio: 0.16, yRatio: 0.27, sizeRatio: 5 },
  { xRatio: 0.33, yRatio: 0.55, sizeRatio: 3 },
  { xRatio: 0.52, yRatio: 0.31, sizeRatio: 3 },
  { xRatio: 0.72, yRatio: 0.22, sizeRatio: 2 },
  { xRatio: 0.79, yRatio: 0.6, sizeRatio: 6 },
];

// -----------------------------------------
// Level 2 preferences (city + civilians)
// -----------------------------------------
const LEVEL2_TARGET_PRESETS: Level2TargetPreset[] = [
  { startXRatio: 0.08, endXRatio: 0.34, yRatio: 0.57, sizeRatio: 2.66, travelTimeSeconds: 5.2 },
  { startXRatio: 0.58, endXRatio: 0.58, yRatio: 0.64, sizeRatio: 2.86, travelTimeSeconds: 1 },
  { startXRatio: 0.27, endXRatio: 0.27, yRatio: 0.75, sizeRatio: 2.06, travelTimeSeconds: 1 },
 
];

const LEVEL2_INNOCENT_PRESETS: InnocentPreset[] = [
  { xRatio: 0.14, yRatio: 0.75, sizeRatio: 0.92, penalty: 30 },
  { xRatio: 0.47, yRatio: 0.7, sizeRatio: 0.72, penalty: 35 },
  { xRatio: 0.9, yRatio: 0.74, sizeRatio: 0.84, penalty: 40 },
];

const LEVEL3_TARGET_PRESETS: Level3TargetPreset[] = [
  { xRatio: 0.5, yRatio: 0.58, sizeRatio: 3.15 },
  { xRatio: 0.3, yRatio: 0.7, sizeRatio: 3 },
  { xRatio: 0.7, yRatio: 0.7, sizeRatio: 3},
  { xRatio: 0.5, yRatio: 0.8, sizeRatio: 3 },
];

const LEVEL4_TARGET_PRESETS: Level4TargetPreset[] = [
  { xRatio: 0.5, yRatio: 0.56, sizeRatio: 3.05 },
  { xRatio: 0.28, yRatio: 0.68, sizeRatio: 2.9 },
  { xRatio: 0.74, yRatio: 0.69, sizeRatio: 2.95 },
  { xRatio: 0.5, yRatio: 0.79, sizeRatio: 2.95 },
];

const LEVEL6_SPAWN_PRESETS: Level6SpawnPreset[] = [
  { xRatio: 0.2, yRatio: 0.6, sizeRatio: 1.08 },
  { xRatio: 0.36, yRatio: 0.52, sizeRatio: 0.95 },
  { xRatio: 0.5, yRatio: 0.72, sizeRatio: 1.1 },
  { xRatio: 0.66, yRatio: 0.54, sizeRatio: 0.92 },
  { xRatio: 0.8, yRatio: 0.66, sizeRatio: 1.06 },
  { xRatio: 0.27, yRatio: 0.77, sizeRatio: 1.04 },
  { xRatio: 0.58, yRatio: 0.44, sizeRatio: 0.9 },
  { xRatio: 0.76, yRatio: 0.79, sizeRatio: 1.02 },
];

const WAVE_MODE_FINAL_WAVE = 4;
const LEVEL6_MAX_IMAGES = 10;
const LEVEL6_IMAGE_DURATION_MS = 3000;
const LEVEL6_NEXT_IMAGE_DELAY_MS = 220;
const LEVEL6_HIT_MARK_DURATION_MS = 620;
const LEVEL6_FALL_DURATION_MS = 760;

function createAudioClip(path: string, volume: number): HTMLAudioElement | undefined {
  if (typeof Audio === 'undefined') {
    return undefined;
  }

  const clip = new Audio(path);

  clip.preload = 'auto';
  clip.volume = volume;

  return clip;
}

export interface ShootingRangeStats {
  shots: number;
  hits: number;
  score: number;
  points: number;
}

export interface ShootingRangeGameOptions {
  host: HTMLElement;
  onStatsChange?: (stats: ShootingRangeStats) => void;
  onLevelComplete?: (level: number) => void;
  onSessionStopped?: () => void;
}

export class ShootingRangeGame {
  // Core Pixi layers.
  private readonly app = new Application();
  private readonly worldLayer = new Container();
  private readonly effectsLayer = new Container();
  private readonly hudLayer = new Container();

  // Scene display objects.
  private readonly backgroundSprite = new Sprite();
  private readonly arenaBackground = new Graphics();
  private readonly cityBackground = new Graphics();
  private readonly platform = new Graphics();
  private readonly shootingArea = new Graphics();
  private readonly crosshair = new Graphics();

  private readonly targets: Target[] = [];
  private readonly innocentPeople: InnocentPerson[] = [];
  private readonly bulletMarks: BulletMark[] = [];
  private readonly scorePopups: Score[] = [];
  private readonly level3TargetHits = new WeakMap<Target, number>();

  // Audio resources.
  private readonly shotSound = createAudioClip(SHOT_SOUND_PATH, 0.6);
  private readonly shotFailSound = createAudioClip(SHOT_FAIL_SOUND_PATH, 0.5);

  // Loaded textures.
  private backgroundTexture?: Texture;
  private backgroundLevel1Texture?: Texture;
  private backgroundLevel2Texture?: Texture;
  private backgroundLevel6Texture?: Texture;
  private targetTexture?: Texture;
  private bulletMarkTexture?: Texture;
  private innocentTexture?: Texture;
  private terroristTexture?: Texture;

  // Active mode selectors.
  private currentLevel = 5;
  private difficulty: DifficultyLevel = 'Medium';
  private waveLevelStep = 0;
  private level6Encounter?: Level6Encounter;
  private level6ShownImages = 0;
  private level6SpawnDelayMs = 0;
  private level6LastSpawnIndex = -1;
  private level6Finished = false;

  // Runtime stats.
  private shots = 0;
  private hits = 0;
  private score = 0;
  private points = 0;
  private isPlayerInShootingArea = false;

  private previousWidth = 0;
  private previousHeight = 0;

  private pointerMoveHandler?: (event: PointerEvent) => void;
  private pointerDownHandler?: (event: PointerEvent) => void;

  constructor(private readonly options: ShootingRangeGameOptions) {}

  // ---------- Lifecycle ----------

  async init(): Promise<void> {
    await this.app.init({
      resizeTo: this.options.host,
      antialias: true,
      backgroundColor: 0x85b3d3,
    });

    this.options.host.appendChild(this.app.canvas);

    this.app.canvas.style.width = '100%';
    this.app.canvas.style.height = '100%';
    this.app.canvas.style.display = 'block';
    this.app.canvas.style.touchAction = 'none';
    this.app.canvas.style.cursor = 'none';

    this.app.stage.addChild(this.worldLayer);
    this.app.stage.addChild(this.effectsLayer);
    this.app.stage.addChild(this.hudLayer);

    this.backgroundSprite.anchor.set(0.5);
    this.worldLayer.addChild(this.backgroundSprite);
    this.worldLayer.addChild(this.arenaBackground);
    this.worldLayer.addChild(this.cityBackground);
    this.worldLayer.addChild(this.platform);
    this.worldLayer.addChild(this.shootingArea);

    await this.loadAssets();

    this.syncLayout();
    this.rebuildTargets();
    this.createCrosshair();
    this.bindPointerControls();

    this.app.ticker.add(this.update);
    this.emitStats();
  }

  destroy(): void {
    this.app.ticker.remove(this.update);

    const canvas = this.app.canvas;

    if (canvas && this.pointerMoveHandler) {
      canvas.removeEventListener('pointermove', this.pointerMoveHandler);
    }

    if (canvas && this.pointerDownHandler) {
      canvas.removeEventListener('pointerdown', this.pointerDownHandler);
    }

    this.shotSound?.pause();
    this.shotFailSound?.pause();

    this.app.destroy(true, { children: true, texture: true, textureSource: true });
  }

  // ---------- Public controls used by the app shell ----------

  setPlayerInShootingArea(isInArea: boolean): void {
    this.isPlayerInShootingArea = isInArea;

    if (this.isLevel6(this.currentLevel)) {
      this.resetLevel6State();
    }

    if (this.isWaveLevel(this.currentLevel)) {
      if (!isInArea) {
        this.waveLevelStep = 0;
        this.clearTargets();
      } else if (this.waveLevelStep === 0) {
        this.waveLevelStep = 1;
        this.rebuildTargets();
      }
    }

    this.drawArena();
  }

  setDifficulty(level: DifficultyLevel): void {
    this.difficulty = level;
    this.rebuildTargets();
  }

  setLevel(level: number): void {
    const previousLevel = this.currentLevel;

    this.currentLevel = level;

    if (previousLevel === 6 || level === 6) {
      this.resetLevel6State();
    }

    if (!this.isWaveLevel(this.currentLevel) || !this.isPlayerInShootingArea) {
      this.waveLevelStep = 0;
    }

    this.drawArena();
    this.rebuildTargets();
  }

  resetSession(): void {
    this.shots = 0;
    this.hits = 0;
    this.score = 0;
    this.points = 0;

    for (const bulletMark of this.bulletMarks) {
      bulletMark.destroy();
    }
    this.bulletMarks.length = 0;

    for (const scorePopup of this.scorePopups) {
      this.effectsLayer.removeChild(scorePopup.label);
      scorePopup.destroy();
    }
    this.scorePopups.length = 0;

    this.resetLevel6State();

    this.emitStats();
  }

  registerArenaShot(
    arenaX: number,
    arenaY: number,
    arenaWidth = 800,
    arenaHeight = 600,
  ): { worldX: number; worldY: number; pointerDispatched: boolean } | null {
    const width = this.app.screen.width;
    const height = this.app.screen.height;

    if (width <= 0 || height <= 0 || arenaWidth <= 0 || arenaHeight <= 0) {
      return null;
    }

    const worldX = (arenaX / arenaWidth) * width;
    const worldY = (arenaY / arenaHeight) * height;
    const pointerDispatched = this.dispatchPointerShot(worldX, worldY, width, height);

    if (!pointerDispatched) {
      this.handleShot(worldX, worldY, true);
    }

    return { worldX, worldY, pointerDispatched };
  }

  private dispatchPointerShot(worldX: number, worldY: number, width: number, height: number): boolean {
    const canvas = this.app.canvas;

    if (!canvas || typeof PointerEvent === 'undefined') {
      return false;
    }

    const rect = canvas.getBoundingClientRect();
    const clientX = rect.left + (worldX / width) * rect.width;
    const clientY = rect.top + (worldY / height) * rect.height;

    canvas.dispatchEvent(
      new PointerEvent('pointermove', {
        clientX,
        clientY,
        bubbles: true,
      }),
    );
    canvas.dispatchEvent(
      new PointerEvent('pointerdown', {
        clientX,
        clientY,
        bubbles: true,
        button: 0,
        buttons: 1,
        pointerType: 'mouse',
        isPrimary: true,
      }),
    );

    return true;
  }

  // ---------- Asset loading and entity lifecycle ----------

  private async loadAssets(): Promise<void> {
    const [
      targetTexture,
      bulletMarkTexture,
      innocentTexture,
      backgroundTexture,
      backgroundLevel1Texture,
      backgroundLevel2Texture,
      backgroundLevel6Texture,
      terroristTexture,
    ] = await Promise.all([
      Assets.load(TARGET_TEXTURE_PATH),
      Assets.load(BULLET_MARK_TEXTURE_PATH),
      Assets.load(INNOCENT_TEXTURE_PATH).catch(() => undefined),
      Assets.load(BACKGROUND_TEXTURE_PATH).catch(() => undefined),
      Assets.load(BACKGROUND_LEVEL1_TEXTURE_PATH).catch(() => undefined),
      Assets.load(BACKGROUND_LEVEL2_TEXTURE_PATH).catch(() => undefined),
      Assets.load(BACKGROUND_LEVEL6_TEXTURE_PATH).catch(() => undefined),
      Assets.load(TERRORIST_TEXTURE_PATH).catch(() => undefined),
    ]);

    this.targetTexture = targetTexture as Texture;
    this.bulletMarkTexture = bulletMarkTexture as Texture;

    if (innocentTexture) {
      this.innocentTexture = innocentTexture as Texture;
    }

    if (backgroundTexture) {
      this.backgroundTexture = backgroundTexture as Texture;
      this.backgroundSprite.texture = this.backgroundTexture;
    }

    if (backgroundLevel1Texture) {
      this.backgroundLevel1Texture = backgroundLevel1Texture as Texture;
    }

    if (backgroundLevel2Texture) {
      this.backgroundLevel2Texture = backgroundLevel2Texture as Texture;
    }

    if (backgroundLevel6Texture) {
      this.backgroundLevel6Texture = backgroundLevel6Texture as Texture;
    }

    if (terroristTexture) {
      this.terroristTexture = terroristTexture as Texture;
    }
  }

  private rebuildTargets(): void {
    if (!this.targetTexture) {
      return;
    }

    this.clearTargets();

    if (this.isLevel6(this.currentLevel)) {
      return;
    }

    if (this.isWaveLevel(this.currentLevel) && !this.isPlayerInShootingArea) {
      return;
    }

    const lanes = this.getLanes();
    const baseTargetDiameter = this.getTargetDiameter();

    lanes.forEach((lane, index) => {
      const targetDiameter = this.getTargetDiameterForIndex(index, baseTargetDiameter);
      const target = new Target(this.targetTexture!, lane, targetDiameter);

      this.targets.push(target);
      this.worldLayer.addChild(target.sprite);
    });

    if (this.isInnocentLevel(this.currentLevel)) {
      this.rebuildInnocentPeople();
    }
  }

  private clearTargets(): void {
    for (const target of this.targets) {
      this.worldLayer.removeChild(target.sprite);
      target.sprite.destroy({ children: true });
    }
    this.targets.length = 0;

    this.clearInnocentPeople();
  }

  // ---------- Level 2 civilians (innocent people) ----------

  private rebuildInnocentPeople(): void {
    this.clearInnocentPeople();

    const baseDiameter = this.getInnocentDiameter();
    const width = this.app.screen.width;
    const height = this.app.screen.height;

    for (const preset of LEVEL2_INNOCENT_PRESETS) {
      const personDiameter = baseDiameter * preset.sizeRatio;
      const innocent = this.createInnocentPerson(preset, personDiameter);

      innocent.container.position.set(width * preset.xRatio, height * preset.yRatio);
      this.innocentPeople.push(innocent);
      this.worldLayer.addChild(innocent.container);
    }
  }

  private clearInnocentPeople(): void {
    for (const innocent of this.innocentPeople) {
      this.worldLayer.removeChild(innocent.container);
      innocent.container.destroy({ children: true });
    }
    this.innocentPeople.length = 0;
  }

  private createInnocentPerson(preset: InnocentPreset, diameter: number): InnocentPerson {
    const container = new Container();
    if (this.innocentTexture) {
      const person = new Sprite(this.innocentTexture);

      person.anchor.set(0.5);

      const baseSize = Math.max(this.innocentTexture.width, this.innocentTexture.height, 1);
      const displayHeight = diameter * 3.15;
      const scale = displayHeight / baseSize;

      person.scale.set(scale);
      container.addChild(person);
    } else {
      const person = new Graphics();
      const unit = diameter * 0.25;

      person
        .circle(0, -unit * 2.2, unit * 0.75)
        .fill({ color: 0x7fc8ff, alpha: 0.95 })
        .roundRect(-unit * 0.95, -unit * 1.35, unit * 1.9, unit * 2.7, unit * 0.45)
        .fill({ color: 0x2f75bc, alpha: 0.92 })
        .roundRect(-unit * 1.65, -unit * 1.1, unit * 0.62, unit * 2, unit * 0.3)
        .fill({ color: 0x235f9a, alpha: 0.9 })
        .roundRect(unit * 1.03, -unit * 1.1, unit * 0.62, unit * 2, unit * 0.3)
        .fill({ color: 0x235f9a, alpha: 0.9 })
        .roundRect(-unit * 0.84, unit * 1.4, unit * 0.64, unit * 1.5, unit * 0.22)
        .fill({ color: 0x153757, alpha: 0.95 })
        .roundRect(unit * 0.2, unit * 1.4, unit * 0.64, unit * 1.5, unit * 0.22)
        .fill({ color: 0x153757, alpha: 0.95 });

      container.addChild(person);
    }

    return {
      container,
      preset,
      hitRadius: diameter * 0.5,
    };
  }

  // ---------- Input and shooting interaction ----------

  private createCrosshair(): void {
    this.crosshair
      .clear()
      .circle(0, 0, 14)
      .stroke({ width: 2, color: 0x7bf6ff, alpha: 0.95 })
      .moveTo(-24, 0)
      .lineTo(24, 0)
      .moveTo(0, -24)
      .lineTo(0, 24)
      .stroke({ width: 2, color: 0x7bf6ff, alpha: 0.75 });

    this.crosshair.position.set(this.app.screen.width / 2, this.app.screen.height / 2);
    this.hudLayer.addChild(this.crosshair);
  }

  private bindPointerControls(): void {
    const canvas = this.app.canvas;

    this.pointerMoveHandler = (event: PointerEvent) => {
      const point = this.toCanvasPoint(event);
      this.crosshair.position.set(point.x, point.y);
    };

    this.pointerDownHandler = (event: PointerEvent) => {
      const point = this.toCanvasPoint(event);
      this.handleShot(point.x, point.y, false);
    };

    canvas.addEventListener('pointermove', this.pointerMoveHandler);
    canvas.addEventListener('pointerdown', this.pointerDownHandler);
  }

  private handleShot(worldX: number, worldY: number, updateCrosshair: boolean): void {
    this.shots += 1;

    if (updateCrosshair) {
      this.crosshair.position.set(worldX, worldY);
    }

    if (!this.isPlayerInShootingArea) {
      this.points = 0;
      this.playAudio(this.shotFailSound);
      this.emitStats();
      return;
    }

    if (this.isLevel6(this.currentLevel)) {
      this.playAudio(this.shotSound);
      this.handleLevel6Shot(worldX, worldY);
      this.emitStats();
      return;
    }

    this.spawnWorldBulletMark(worldX, worldY);
    this.playAudio(this.shotSound);
    const innocentHit = this.findInnocentHit(worldX, worldY);

    if (innocentHit) {
      this.points = -innocentHit.penalty;
      this.score = Math.max(0, this.score - innocentHit.penalty);

      this.spawnScore(-innocentHit.penalty, worldX, worldY - 18);
      this.emitStats();
      this.stopSessionAfterInnocentHit();
      return;
    }

    const targetHit = this.findTargetHit(worldX, worldY);

    if (!targetHit) {
      this.points = 0;
      this.emitStats();
      return;
    }

    this.hits += 1;
    this.points = targetHit.score;
    this.score += targetHit.score;

    this.spawnScore(targetHit.score, worldX, worldY - 20);

    if (this.isWaveLevel(this.currentLevel)) {
      if (this.currentLevel === 3) {
        const accumulatedHits = (this.level3TargetHits.get(targetHit.target) ?? 0) + 1;

        this.level3TargetHits.set(targetHit.target, accumulatedHits);

        if (accumulatedHits >= 2) {
          this.removeTarget(targetHit.target);
          this.advanceWaveLevelIfNeeded();
        }
      } else {
        this.removeTarget(targetHit.target);
        this.advanceWaveLevelIfNeeded();
      }
    }

    this.emitStats();
  }

  // Civilian hit check for levels that include innocents.
  private findInnocentHit(x: number, y: number): { innocent: InnocentPerson; penalty: number } | undefined {
    if (!this.isInnocentLevel(this.currentLevel)) {
      return undefined;
    }

    for (let index = this.innocentPeople.length - 1; index >= 0; index -= 1) {
      const innocent = this.innocentPeople[index];
      const dx = x - innocent.container.x;
      const dy = y - innocent.container.y;
      const distance = Math.sqrt((dx * dx) + (dy * dy));

      if (distance <= innocent.hitRadius) {
        return {
          innocent,
          penalty: innocent.preset.penalty,
        };
      }
    }

    return undefined;
  }

  // Common hostile target hit check.
  private findTargetHit(x: number, y: number): { target: Target; score: ScoreValue } | undefined {
    for (let index = this.targets.length - 1; index >= 0; index -= 1) {
      const target = this.targets[index];
      const score = target.getHitScore(x, y);

      if (score !== null) {
        return { target, score };
      }
    }

    return undefined;
  }

  // Common world-space bullet mark used for every shot.
  private spawnWorldBulletMark(worldX: number, worldY: number): void {
    if (!this.bulletMarkTexture) {
      return;
    }

    const displayedDiameter = 16;

    const bulletMark = new BulletMark(
      this.bulletMarkTexture,
      worldX,
      worldY,
      displayedDiameter,
    );

    this.effectsLayer.addChild(bulletMark.sprite);
    this.bulletMarks.push(bulletMark);
  }

  // Common floating score popup.
  private spawnScore(value: ScoreValue, x: number, y: number): void {
    const scorePopup = new Score(value, x, y);

    this.effectsLayer.addChild(scorePopup.label);
    this.scorePopups.push(scorePopup);
  }

  // ---------- Level 6 single-image sequence ----------

  private handleLevel6Shot(worldX: number, worldY: number): void {
    const encounter = this.level6Encounter;

    if (!encounter || encounter.hit) {
      this.points = 0;
      return;
    }

    const spriteBounds = encounter.sprite.getBounds();

    if (
      worldX < spriteBounds.minX
      || worldX > spriteBounds.maxX
      || worldY < spriteBounds.minY
      || worldY > spriteBounds.maxY
    ) {
      this.points = 0;
      return;
    }

    this.hits += 1;

    const hitScore = encounter.actorType === 'terrorist' ? 50 : -50;

    this.points = hitScore;
    this.score += hitScore;
    this.spawnScore(hitScore, worldX, worldY - 20);

    this.attachLevel6HitMark(encounter, worldX, worldY);

    encounter.hit = true;
    encounter.fallElapsedMs = 0;
    encounter.fallVelocityPerMs = 0.2 + (Math.random() * 0.09);
    encounter.fallRotationPerMs = (Math.random() < 0.5 ? -1 : 1) * (0.002 + (Math.random() * 0.0014));
  }

  private attachLevel6HitMark(encounter: Level6Encounter, worldX: number, worldY: number): void {
    if (!this.bulletMarkTexture) {
      return;
    }

    this.removeLevel6HitMark(encounter);

    const localPoint = encounter.sprite.toLocal(new Point(worldX, worldY));
    const hitMarkDiameter = this.clamp(Math.max(encounter.sprite.width, encounter.sprite.height) * 0.09, 12, 34);
    const hitMark = new BulletMark(this.bulletMarkTexture, localPoint.x, localPoint.y, hitMarkDiameter);

    encounter.sprite.addChild(hitMark.sprite);
    encounter.hitMark = hitMark;
    encounter.hitMarkRemainingMs = LEVEL6_HIT_MARK_DURATION_MS;
  }

  private removeLevel6HitMark(encounter: Level6Encounter): void {
    if (!encounter.hitMark) {
      return;
    }

    encounter.sprite.removeChild(encounter.hitMark.sprite);
    encounter.hitMark.destroy();
    encounter.hitMark = undefined;
    encounter.hitMarkRemainingMs = 0;
  }

  private updateLevel6(deltaMs: number): void {
    if (!this.isLevel6(this.currentLevel)) {
      return;
    }

    if (!this.isPlayerInShootingArea) {
      this.clearLevel6Encounter();
      return;
    }

    const encounter = this.level6Encounter;

    if (encounter) {
      encounter.elapsedMs += deltaMs;

      if (encounter.hitMark) {
        encounter.hitMarkRemainingMs -= deltaMs;

        if (encounter.hitMarkRemainingMs <= 0) {
          this.removeLevel6HitMark(encounter);
        }
      }

      if (encounter.hit) {
        encounter.fallElapsedMs += deltaMs;
        encounter.container.y += encounter.fallVelocityPerMs * deltaMs;
        encounter.container.rotation += encounter.fallRotationPerMs * deltaMs;

        const fadeRatio = Math.min(encounter.fallElapsedMs / LEVEL6_FALL_DURATION_MS, 1);
        encounter.container.alpha = 1 - (fadeRatio * 0.45);

        if (encounter.fallElapsedMs >= LEVEL6_FALL_DURATION_MS) {
          this.clearLevel6Encounter();
          this.level6SpawnDelayMs = LEVEL6_NEXT_IMAGE_DELAY_MS;
        }

        return;
      }

      if (encounter.elapsedMs >= LEVEL6_IMAGE_DURATION_MS) {
        this.clearLevel6Encounter();
        this.level6SpawnDelayMs = LEVEL6_NEXT_IMAGE_DELAY_MS;
      }

      return;
    }

    if (this.level6SpawnDelayMs > 0) {
      this.level6SpawnDelayMs = Math.max(0, this.level6SpawnDelayMs - deltaMs);
      return;
    }

    if (this.level6ShownImages >= LEVEL6_MAX_IMAGES) {
      this.completeLevel6();
      return;
    }

    this.spawnLevel6Encounter();
  }

  private spawnLevel6Encounter(): void {
    if (!this.isLevel6(this.currentLevel) || !this.isPlayerInShootingArea) {
      return;
    }

    if (this.level6ShownImages >= LEVEL6_MAX_IMAGES) {
      return;
    }

    const actorType: Level6ActorType = Math.random() < 0.5 ? 'terrorist' : 'innocent';
    const actorTexture = actorType === 'terrorist' ? this.terroristTexture : this.innocentTexture;

    if (!actorTexture) {
      return;
    }

    const spawnPreset = this.pickLevel6SpawnPreset();
    const baseDiameter = this.getLevel6ActorDiameter();
    const displayDiameter = baseDiameter * spawnPreset.sizeRatio;
    const width = this.app.screen.width;
    const height = this.app.screen.height;

    const container = new Container();
    const sprite = new Sprite(actorTexture);
    const textureSize = Math.max(actorTexture.width, actorTexture.height, 1);
    const displayHeight = displayDiameter * (actorType === 'terrorist' ? 3.02 : 3.15);
    const scale = displayHeight / textureSize;

    sprite.anchor.set(0.5);
    sprite.scale.set(scale);

    container.position.set(width * spawnPreset.xRatio, height * spawnPreset.yRatio);
    container.addChild(sprite);

    this.worldLayer.addChild(container);
    this.level6Encounter = {
      container,
      sprite,
      actorType,
      elapsedMs: 0,
      hit: false,
      fallElapsedMs: 0,
      fallVelocityPerMs: 0,
      fallRotationPerMs: 0,
      hitMarkRemainingMs: 0,
    };

    this.level6ShownImages += 1;
  }

  private pickLevel6SpawnPreset(): Level6SpawnPreset {
    if (LEVEL6_SPAWN_PRESETS.length === 0) {
      return { xRatio: 0.5, yRatio: 0.6, sizeRatio: 1 };
    }

    let nextIndex = Math.floor(Math.random() * LEVEL6_SPAWN_PRESETS.length);

    if (LEVEL6_SPAWN_PRESETS.length > 1 && nextIndex === this.level6LastSpawnIndex) {
      nextIndex = (nextIndex + 1 + Math.floor(Math.random() * (LEVEL6_SPAWN_PRESETS.length - 1))) % LEVEL6_SPAWN_PRESETS.length;
    }

    this.level6LastSpawnIndex = nextIndex;

    return LEVEL6_SPAWN_PRESETS[nextIndex];
  }

  private clearLevel6Encounter(): void {
    if (!this.level6Encounter) {
      return;
    }

    this.worldLayer.removeChild(this.level6Encounter.container);
    this.level6Encounter.container.destroy({ children: true });
    this.level6Encounter = undefined;
  }

  private resetLevel6State(): void {
    this.clearLevel6Encounter();
    this.level6ShownImages = 0;
    this.level6SpawnDelayMs = 0;
    this.level6LastSpawnIndex = -1;
    this.level6Finished = false;
  }

  private getLevel6ActorDiameter(): number {
    const diameter = Math.min(this.app.screen.width, this.app.screen.height) * 0.145;

    return this.clamp(diameter, 90, 260);
  }

  private completeLevel6(): void {
    if (this.level6Finished || !this.isLevel6(this.currentLevel)) {
      return;
    }

    this.level6Finished = true;

    const completedLevel = this.currentLevel;

    this.isPlayerInShootingArea = false;
    this.options.onLevelComplete?.(completedLevel);
  }

  private readonly update = (ticker: Ticker): void => {
    this.syncLayout();

    const deltaMs = ticker.deltaMS;
    const deltaSeconds = deltaMs / 1000;

    for (const target of this.targets) {
      target.update(deltaSeconds);
    }

    this.updateLevel6(deltaMs);

    for (let index = this.scorePopups.length - 1; index >= 0; index -= 1) {
      const scorePopup = this.scorePopups[index];

      if (scorePopup.update(deltaMs)) {
        this.effectsLayer.removeChild(scorePopup.label);
        scorePopup.destroy();
        this.scorePopups.splice(index, 1);
      }
    }
  };

  // ---------- Responsive layout and scene drawing ----------

  private syncLayout(): void {
    const { width, height } = this.app.screen;

    if (width === this.previousWidth && height === this.previousHeight) {
      return;
    }

    this.previousWidth = width;
    this.previousHeight = height;

    this.drawArena();
    this.syncTargetsWithLayout();
    this.syncInnocentPeopleWithLayout();
  }

  private drawArena(): void {
    const width = this.app.screen.width;
    const height = this.app.screen.height;

    // Level-specific background selection.
    const selectedBackground = this.currentLevel === 1 || this.currentLevel === 3
      ? this.backgroundLevel1Texture
      : this.currentLevel === 2 || this.currentLevel === 4
        ? this.backgroundLevel2Texture
        : this.currentLevel === 6
          ? this.backgroundLevel6Texture
        : this.backgroundTexture;

    if (selectedBackground && selectedBackground.width > 0 && selectedBackground.height > 0) {
      const scale = Math.max(
        width / selectedBackground.width,
        height / selectedBackground.height,
      );

      this.backgroundSprite.visible = true;
      this.backgroundSprite.texture = selectedBackground;
      this.backgroundSprite.position.set(width / 2, height / 2);
      this.backgroundSprite.scale.set(scale);

      this.arenaBackground
        .clear()
        .rect(0, 0, width, height)
        .fill({ color: 0x000000, alpha: 0.14 });
      this.cityBackground.clear();
    } else if (this.currentLevel === 2 || this.currentLevel === 4) {
      this.backgroundSprite.visible = false;
      this.drawLevel2CityBackground(width, height);
    } else {
      this.backgroundSprite.visible = false;
      this.arenaBackground
        .clear()
        .rect(0, 0, width, height)
        .fill({ color: 0x86b5d8 })
        .rect(0, height * 0.56, width, height * 0.44)
        .fill({ color: 0x2d4053 });
      this.cityBackground.clear();
    }

    this.platform.clear();
    this.shootingArea.clear();
  }

  // Level 2 fallback background if background_level2 image is unavailable.
  private drawLevel2CityBackground(width: number, height: number): void {
    this.arenaBackground
      .clear()
      .rect(0, 0, width, height)
      .fill({ color: 0x4f7aa3 })
      .rect(0, height * 0.58, width, height * 0.42)
      .fill({ color: 0x1a2f44 });

    this.cityBackground.clear();

    const skylineStartY = height * 0.46;
    const buildingData = [
      { x: width * 0.04, w: width * 0.12, h: height * 0.22 },
      { x: width * 0.19, w: width * 0.09, h: height * 0.3 },
      { x: width * 0.32, w: width * 0.11, h: height * 0.2 },
      { x: width * 0.48, w: width * 0.1, h: height * 0.27 },
      { x: width * 0.62, w: width * 0.14, h: height * 0.24 },
      { x: width * 0.81, w: width * 0.11, h: height * 0.33 },
    ];

    for (const building of buildingData) {
      this.cityBackground
        .rect(building.x, skylineStartY - building.h, building.w, building.h)
        .fill({ color: 0x13263a, alpha: 0.96 });

      const windowRows = 4;
      const windowCols = 3;
      const windowWidth = building.w / 9;
      const windowHeight = building.h / 16;

      for (let row = 0; row < windowRows; row += 1) {
        for (let col = 0; col < windowCols; col += 1) {
          this.cityBackground
            .rect(
              building.x + (windowWidth * (1.5 + (col * 2.2))),
              (skylineStartY - building.h) + (windowHeight * (2 + (row * 3))),
              windowWidth,
              windowHeight,
            )
            .fill({ color: 0xffdc8a, alpha: 0.45 });
        }
      }
    }
  }

  // ---------- Level preferences and sizing ----------

  private syncTargetsWithLayout(): void {
    if (!this.targetTexture || this.targets.length === 0) {
      return;
    }

    const lanes = this.getLanes();
    if (lanes.length !== this.targets.length) {
      this.rebuildTargets();
      return;
    }

    const baseTargetDiameter = this.getTargetDiameter();

    this.targets.forEach((target, index) => {
      const lane = lanes[index];

      if (!lane) {
        return;
      }

      target.setDisplayDiameter(this.getTargetDiameterForIndex(index, baseTargetDiameter));
      target.setLane(lane);
    });
  }

  private syncInnocentPeopleWithLayout(): void {
    if (!this.isInnocentLevel(this.currentLevel)) {
      return;
    }

    this.rebuildInnocentPeople();
  }

  private getInnocentDiameter(): number {
    const diameter = Math.min(this.app.screen.width, this.app.screen.height) * 0.145;

    return this.clamp(diameter, 90, 260);
  }

  private getLanes(): TargetLane[] {
    const width = this.app.screen.width;
    const height = this.app.screen.height;
    const difficultyConfig = DIFFICULTY_CONFIG[this.difficulty];

    if (this.isLevel6(this.currentLevel)) {
      return [];
    }

    // Level 1: fixed targets only.
    if (this.currentLevel === 1) {
      return LEVEL1_TARGET_PRESETS.map((preset) => {
        const x = width * preset.xRatio;
        const y = height * preset.yRatio;

        return {
          startX: x,
          endX: x,
          y,
          travelTimeSeconds: 1,
        };
      });
    }

    // Level 2: one moving target + fixed dispersed targets.
    if (this.currentLevel === 2) {
      return LEVEL2_TARGET_PRESETS.map((preset) => {
        const startX = width * preset.startXRatio;
        const endX = width * preset.endXRatio;
        const isMovingTarget = this.isMovingLane(startX, endX);

        return {
          startX,
          endX,
          y: height * preset.yRatio,
          travelTimeSeconds: isMovingTarget
            ? preset.travelTimeSeconds / difficultyConfig.speedMultiplier
            : preset.travelTimeSeconds,
        };
      });
    }

    // Level 3: progressive fixed-target waves.
    if (this.currentLevel === 3 || this.currentLevel === 4) {
      const presets = this.currentLevel === 3 ? LEVEL3_TARGET_PRESETS : LEVEL4_TARGET_PRESETS;

      return presets
        .slice(0, this.waveLevelStep)
        .map((preset) => {
          const x = width * preset.xRatio;
          const y = height * preset.yRatio;

          return {
            startX: x,
            endX: x,
            y,
            travelTimeSeconds: 1,
          };
        });
    }

    // Common/default levels: back-and-forth moving targets.
    const startX = width * 0.2;
    const endX = width * 0.8;
    const firstY = height * 0.36;
    const gap = height * 0.14;
    const times = [9, 8.67, 8.34];

    return [0, 1, 2].map((index) => {
      const oddLane = index % 2 === 1;

      return {
        startX: oddLane ? endX : startX,
        endX: oddLane ? startX : endX,
        y: firstY + (index * gap),
        travelTimeSeconds: times[index] / difficultyConfig.speedMultiplier,
      };
    });
  }

  private getTargetDiameter(): number {
    // Level 1 diameter policy.
    if (this.currentLevel === 1) {
      const difficultyConfig = DIFFICULTY_CONFIG[this.difficulty];
      const diameter = Math.min(this.app.screen.width, this.app.screen.height) * 0.13 * difficultyConfig.sizeMultiplier;

      return this.clamp(diameter, 110, 210);
    }

    // Level 2 diameter policy.
    if (this.currentLevel === 2) {
      const difficultyConfig = DIFFICULTY_CONFIG[this.difficulty];
      const diameter = Math.min(this.app.screen.width, this.app.screen.height) * 0.145 * difficultyConfig.sizeMultiplier;

      return this.clamp(diameter, 90, 260);
    }

    // Level 3 diameter policy.
    if (this.currentLevel === 3) {
      const difficultyConfig = DIFFICULTY_CONFIG[this.difficulty];
      const diameter = Math.min(this.app.screen.width, this.app.screen.height) * 0.12 * difficultyConfig.sizeMultiplier;

      return this.clamp(diameter, 90, 220);
    }

    // Level 4 diameter policy.
    if (this.currentLevel === 4) {
      const difficultyConfig = DIFFICULTY_CONFIG[this.difficulty];
      const diameter = Math.min(this.app.screen.width, this.app.screen.height) * 0.12 * difficultyConfig.sizeMultiplier;

      return this.clamp(diameter, 90, 220);
    }

    // Common/default level diameter policy.
    const difficultyConfig = DIFFICULTY_CONFIG[this.difficulty];
    const diameter = Math.min(this.app.screen.width, this.app.screen.height) * 0.11 * difficultyConfig.sizeMultiplier;

    return this.clamp(diameter, 80, 240);
  }

  private getTargetDiameterForIndex(index: number, baseDiameter: number): number {
    // Level 1 per-target size presets.
    if (this.currentLevel === 1) {
      const preset = LEVEL1_TARGET_PRESETS[index];
      if (!preset) {
        return baseDiameter;
      }

      return baseDiameter * preset.sizeRatio;
    }

    // Level 2 per-target size presets.
    if (this.currentLevel === 2) {
      const preset = LEVEL2_TARGET_PRESETS[index];
      if (!preset) {
        return baseDiameter;
      }

      return baseDiameter * preset.sizeRatio;
    }

    // Level 3 per-target size presets.
    if (this.currentLevel === 3) {
      const preset = LEVEL3_TARGET_PRESETS[index];
      if (!preset) {
        return baseDiameter;
      }

      return baseDiameter * preset.sizeRatio;
    }

    // Level 4 per-target size presets.
    if (this.currentLevel === 4) {
      const preset = LEVEL4_TARGET_PRESETS[index];
      if (!preset) {
        return baseDiameter;
      }

      return baseDiameter * preset.sizeRatio;
    }

    // Common/default sizing.
    return baseDiameter;
  }

  // ---------- Common utility helpers ----------

  private toCanvasPoint(event: PointerEvent): { x: number; y: number } {
    const rect = this.app.canvas.getBoundingClientRect();

    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  }

  private playAudio(audio?: HTMLAudioElement): void {
    if (!audio) {
      return;
    }

    audio.currentTime = 0;
    void audio.play().catch(() => undefined);
  }

  private emitStats(): void {
    this.options.onStatsChange?.({
      shots: this.shots,
      hits: this.hits,
      score: this.score,
      points: this.points,
    });
  }

  private clamp(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, value));
  }

  private isMovingLane(startX: number, endX: number): boolean {
    return Math.abs(startX - endX) > 0.5;
  }

  private isInnocentLevel(level: number): boolean {
    return level === 2 || level === 4;
  }

  private isLevel6(level: number): boolean {
    return level === 6;
  }

  private removeTarget(target: Target): void {
    const index = this.targets.indexOf(target);

    if (index < 0) {
      return;
    }

    this.worldLayer.removeChild(target.sprite);
    target.sprite.destroy({ children: true });
    this.targets.splice(index, 1);
  }

  private stopSessionAfterInnocentHit(): void {
    this.setPlayerInShootingArea(false);
    this.options.onSessionStopped?.();
  }

  private advanceWaveLevelIfNeeded(): void {
    if (!this.isWaveLevel(this.currentLevel) || this.targets.length > 0) {
      return;
    }

    if (this.waveLevelStep < WAVE_MODE_FINAL_WAVE) {
      this.waveLevelStep += 1;
      this.rebuildTargets();
      return;
    }

    const completedLevel = this.currentLevel;

    this.waveLevelStep = 0;
    this.isPlayerInShootingArea = false;
    this.options.onLevelComplete?.(completedLevel);
  }

  private isWaveLevel(level: number): boolean {
    return level === 3 || level === 4;
  }
}
