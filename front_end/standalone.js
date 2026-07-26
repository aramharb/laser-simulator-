const { Application, Assets, Container, Graphics, Point, Sprite, Text } = PIXI;

const ASSET_PREFIX = 'public/';
const TARGET_TEXTURE_PATH = `${ASSET_PREFIX}assets/shooting-range/models/targetBoard_v2.png`;
const BULLET_MARK_TEXTURE_PATH = `${ASSET_PREFIX}assets/shooting-range/models/bulletMark.png`;
const INNOCENT_TEXTURE_PATH = `${ASSET_PREFIX}assets/shooting-range/models/innocent.png`;
const BACKGROUND_TEXTURE_PATH = `${ASSET_PREFIX}assets/shooting-range/background.png`;
const BACKGROUND_LEVEL1_TEXTURE_PATH = `${ASSET_PREFIX}assets/shooting-range/background_level1.png`;
const BACKGROUND_LEVEL2_TEXTURE_PATH = `${ASSET_PREFIX}assets/shooting-range/background_level_2.jpg`;
const BACKGROUND_LEVEL6_TEXTURE_PATH = `${ASSET_PREFIX}assets/shooting-range/background_level6.png`;
const TERRORIST_TEXTURE_PATH = `${ASSET_PREFIX}assets/shooting-range/terrorist.png`;
const SHOT_SOUND_PATH = `${ASSET_PREFIX}assets/shooting-range/sounds/shot.mp3`;
const SHOT_FAIL_SOUND_PATH = `${ASSET_PREFIX}assets/shooting-range/sounds/shotFail.mp3`;

const DIFFICULTY_CONFIG = {
  Easy: { speedMultiplier: 0.8, sizeMultiplier: 1.18 },
  Medium: { speedMultiplier: 1, sizeMultiplier: 1 },
  Hard: { speedMultiplier: 1.35, sizeMultiplier: 0.84 },
};

const LEVEL1_TARGET_PRESETS = [
  { xRatio: 0.16, yRatio: 0.27, sizeRatio: 5 },
  { xRatio: 0.33, yRatio: 0.55, sizeRatio: 3 },
  { xRatio: 0.52, yRatio: 0.31, sizeRatio: 3 },
  { xRatio: 0.72, yRatio: 0.22, sizeRatio: 2 },
  { xRatio: 0.79, yRatio: 0.6, sizeRatio: 6 },
];

const LEVEL2_TARGET_PRESETS = [
  { startXRatio: 0.08, endXRatio: 0.34, yRatio: 0.57, sizeRatio: 2.66, travelTimeSeconds: 5.2 },
  { startXRatio: 0.58, endXRatio: 0.58, yRatio: 0.64, sizeRatio: 2.86, travelTimeSeconds: 1 },
  { startXRatio: 0.27, endXRatio: 0.27, yRatio: 0.75, sizeRatio: 2.06, travelTimeSeconds: 1 },
];

const LEVEL2_INNOCENT_PRESETS = [
  { xRatio: 0.14, yRatio: 0.75, sizeRatio: 0.92, penalty: 30 },
  { xRatio: 0.47, yRatio: 0.7, sizeRatio: 0.72, penalty: 35 },
  { xRatio: 0.9, yRatio: 0.74, sizeRatio: 0.84, penalty: 40 },
];

const LEVEL3_TARGET_PRESETS = [
  { xRatio: 0.5, yRatio: 0.58, sizeRatio: 3.15 },
  { xRatio: 0.3, yRatio: 0.7, sizeRatio: 3 },
  { xRatio: 0.7, yRatio: 0.7, sizeRatio: 3 },
  { xRatio: 0.5, yRatio: 0.8, sizeRatio: 3 },
];

const LEVEL4_TARGET_PRESETS = [
  { xRatio: 0.5, yRatio: 0.56, sizeRatio: 3.05 },
  { xRatio: 0.28, yRatio: 0.68, sizeRatio: 2.9 },
  { xRatio: 0.74, yRatio: 0.69, sizeRatio: 2.95 },
  { xRatio: 0.5, yRatio: 0.79, sizeRatio: 2.95 },
];

const LEVEL6_SPAWN_PRESETS = [
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

const LEVEL_CONFIGS = {
  1: { objective: 'score', targetScore: 180, objectiveLabel: 'Target score: 180' },
  2: { objective: 'score', targetScore: 220, objectiveLabel: 'Target score: 220' },
  3: { objective: 'wave-clear', objectiveLabel: 'Objective: clear waves 1 to 4' },
  4: { objective: 'wave-clear', objectiveLabel: 'Objective: clear waves 1 to 4' },
  5: { objective: 'score', targetScore: 200, objectiveLabel: 'Target score: 200' },
  6: { objective: 'wave-clear', objectiveLabel: 'Objective: 20 random images, terrorist +50 / innocent -50' },
};

const TOTAL_LEVEL_OPTIONS = 10;
const EDITABLE_TARGET_SCORE_LEVELS = [1, 2];
const TARGET_SCORE_MIN = 50;
const TARGET_SCORE_MAX = 1000;
const TARGET_SCORE_STEP = 10;

function createDefaultLevelDifficulties() {
  const map = {};
  for (let index = 1; index <= TOTAL_LEVEL_OPTIONS; index += 1) {
    map[index] = 'Medium';
  }
  return map;
}

function createDefaultEditableTargetScores() {
  return {
    1: LEVEL_CONFIGS[1]?.targetScore ?? 180,
    2: LEVEL_CONFIGS[2]?.targetScore ?? 220,
  };
}

function createAudioClip(path, volume) {
  if (typeof Audio === 'undefined') {
    return undefined;
  }

  const clip = new Audio(path);
  clip.preload = 'auto';
  clip.volume = volume;
  return clip;
}

class BulletMark {
  constructor(texture, localX, localY, displayDiameter) {
    this.sprite = new Sprite(texture);
    this.sprite.anchor.set(0.5);
    this.sprite.position.set(localX, localY);
    this.sprite.rotation = Math.random() * Math.PI * 2;

    const baseDiameter = Math.max(texture.width, texture.height, 1);
    const scale = displayDiameter / baseDiameter;
    this.sprite.scale.set(scale);
  }

  destroy() {
    this.sprite.destroy();
  }
}

class Score {
  constructor(value, x, y) {
    this.elapsedMs = 0;
    this.lifetimeMs = 900;

    const color = this.resolveScoreColor(value);
    const absoluteValue = Math.abs(value);
    const fontSize = absoluteValue >= 100 ? 74 : absoluteValue >= 70 ? 66 : absoluteValue >= 50 ? 60 : 56;
    const scoreText = value > 0 ? `+${value}` : `${value}`;

    this.label = new Text({
      text: scoreText,
      style: {
        fill: color,
        fontFamily: 'Verdana',
        fontSize,
        fontWeight: '700',
      },
    });

    this.label.anchor.set(0.5);
    this.label.position.set(x, y);
  }

  update(deltaMs) {
    this.elapsedMs += deltaMs;
    const lifeRatio = Math.min(this.elapsedMs / this.lifetimeMs, 1);
    this.label.y -= deltaMs * 0.08;
    this.label.alpha = 1 - lifeRatio;
    return this.elapsedMs >= this.lifetimeMs;
  }

  destroy() {
    this.label.destroy();
  }

  resolveScoreColor(value) {
    if (value < 0) {
      return 0xff4d4d;
    }
    if (value >= 100) {
      return 0xff4d4d;
    }
    if (value >= 70) {
      return 0xff8d42;
    }
    if (value >= 50) {
      return 0x00c062;
    }
    if (value >= 25) {
      return 0xa6842b;
    }
    return 0x90a63d;
  }
}

const HEAD_ZONE = {
  centerX: 0.5,
  centerY: 0.241,
  outerRadius: 0.068,
  midRadius: 0.048,
  centerRadius: 0.031,
  outerScore: 50,
  midScore: 70,
  centerScore: 100,
};

const CHEST_ZONE = {
  centerX: 0.5,
  centerY: 0.51,
  outerRadius: 0.125,
  midRadius: 0.085,
  centerRadius: 0.052,
  outerScore: 10,
  midScore: 25,
  centerScore: 50,
};

class Target {
  constructor(texture, lane, displayDiameter) {
    this.lane = lane;
    this.progress = 0;
    this.direction = 1;

    this.sprite = new Sprite(texture);
    this.sprite.anchor.set(0.5);
    this.setDisplayDiameter(displayDiameter);
    this.sprite.position.set(lane.startX, lane.y);
  }

  update(deltaSeconds) {
    const duration = Math.max(this.lane.travelTimeSeconds, 0.1);
    this.progress += this.direction * (deltaSeconds / duration);

    if (this.progress >= 1) {
      this.progress = 1;
      this.direction = -1;
    } else if (this.progress <= 0) {
      this.progress = 0;
      this.direction = 1;
    }

    this.sprite.x = this.lerp(this.lane.startX, this.lane.endX, this.progress);
    this.sprite.y = this.lane.y;
  }

  setLane(lane) {
    this.lane = lane;
    this.sprite.x = this.lerp(this.lane.startX, this.lane.endX, this.progress);
    this.sprite.y = this.lane.y;
  }

  setDisplayDiameter(displayDiameter) {
    const baseDiameter = Math.max(this.sprite.texture.width, this.sprite.texture.height, 1);
    const scale = displayDiameter / baseDiameter;
    this.sprite.scale.set(scale);
  }

  getHitScore(worldX, worldY) {
    const normalizedPoint = this.toNormalizedCoordinates(worldX, worldY);
    if (!normalizedPoint) {
      return null;
    }

    const headScore = this.getZoneScore(normalizedPoint.x, normalizedPoint.y, HEAD_ZONE);
    if (headScore !== null) {
      return headScore;
    }

    return this.getZoneScore(normalizedPoint.x, normalizedPoint.y, CHEST_ZONE);
  }

  toLocalCoordinates(worldX, worldY) {
    const scaleX = this.sprite.scale.x || 1;
    const scaleY = this.sprite.scale.y || 1;

    return {
      x: (worldX - this.sprite.x) / scaleX,
      y: (worldY - this.sprite.y) / scaleY,
    };
  }

  toNormalizedCoordinates(worldX, worldY) {
    const localPoint = this.toLocalCoordinates(worldX, worldY);
    const textureWidth = this.sprite.texture.width;
    const textureHeight = this.sprite.texture.height;

    if (textureWidth <= 0 || textureHeight <= 0) {
      return null;
    }

    const pixelX = localPoint.x + (textureWidth * 0.5);
    const pixelY = localPoint.y + (textureHeight * 0.5);

    return {
      x: pixelX / textureWidth,
      y: pixelY / textureHeight,
    };
  }

  getZoneScore(x, y, zone) {
    const dx = x - zone.centerX;
    const dy = y - zone.centerY;
    const distance = Math.sqrt((dx * dx) + (dy * dy));

    if (distance <= zone.centerRadius) {
      return zone.centerScore;
    }
    if (distance <= zone.midRadius) {
      return zone.midScore;
    }
    if (distance <= zone.outerRadius) {
      return zone.outerScore;
    }

    return null;
  }

  lerp(start, end, amount) {
    return start + ((end - start) * amount);
  }
}

class ShootingRangeGame {
  constructor(options) {
    this.options = options;

    this.app = new Application();
    this.worldLayer = new Container();
    this.effectsLayer = new Container();
    this.hudLayer = new Container();

    this.backgroundSprite = new Sprite();
    this.arenaBackground = new Graphics();
    this.cityBackground = new Graphics();
    this.platform = new Graphics();
    this.shootingArea = new Graphics();
    this.crosshair = new Graphics();

    this.targets = [];
    this.innocentPeople = [];
    this.bulletMarks = [];
    this.scorePopups = [];
    this.level3TargetHits = new WeakMap();

    this.shotSound = createAudioClip(SHOT_SOUND_PATH, 0.6);
    this.shotFailSound = createAudioClip(SHOT_FAIL_SOUND_PATH, 0.5);

    this.currentLevel = 5;
    this.difficulty = 'Medium';
    this.waveLevelStep = 0;

    this.level6Encounter = undefined;
    this.level6ShownImages = 0;
    this.level6SpawnDelayMs = 0;
    this.level6LastSpawnIndex = -1;
    this.level6Finished = false;

    this.shots = 0;
    this.hits = 0;
    this.score = 0;
    this.points = 0;
    this.isPlayerInShootingArea = false;

    this.previousWidth = 0;
    this.previousHeight = 0;

    this.pointerMoveHandler = undefined;
    this.pointerDownHandler = undefined;

    this.update = (ticker) => {
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
  }

  async init() {
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

  destroy() {
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

  setPlayerInShootingArea(isInArea) {
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

  setDifficulty(level) {
    this.difficulty = level;
    this.rebuildTargets();
  }

  setLevel(level) {
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

  resetSession() {
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

  async loadAssets() {
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

    this.targetTexture = targetTexture;
    this.bulletMarkTexture = bulletMarkTexture;

    if (innocentTexture) {
      this.innocentTexture = innocentTexture;
    }

    if (backgroundTexture) {
      this.backgroundTexture = backgroundTexture;
      this.backgroundSprite.texture = this.backgroundTexture;
    }

    if (backgroundLevel1Texture) {
      this.backgroundLevel1Texture = backgroundLevel1Texture;
    }

    if (backgroundLevel2Texture) {
      this.backgroundLevel2Texture = backgroundLevel2Texture;
    }

    if (backgroundLevel6Texture) {
      this.backgroundLevel6Texture = backgroundLevel6Texture;
    }

    if (terroristTexture) {
      this.terroristTexture = terroristTexture;
    }
  }

  rebuildTargets() {
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
      const target = new Target(this.targetTexture, lane, targetDiameter);

      this.targets.push(target);
      this.worldLayer.addChild(target.sprite);
    });

    if (this.isInnocentLevel(this.currentLevel)) {
      this.rebuildInnocentPeople();
    }
  }

  clearTargets() {
    for (const target of this.targets) {
      this.worldLayer.removeChild(target.sprite);
      target.sprite.destroy({ children: true });
    }
    this.targets.length = 0;
    this.clearInnocentPeople();
  }

  rebuildInnocentPeople() {
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

  clearInnocentPeople() {
    for (const innocent of this.innocentPeople) {
      this.worldLayer.removeChild(innocent.container);
      innocent.container.destroy({ children: true });
    }
    this.innocentPeople.length = 0;
  }

  createInnocentPerson(preset, diameter) {
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

  createCrosshair() {
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

  bindPointerControls() {
    const canvas = this.app.canvas;

    this.pointerMoveHandler = (event) => {
      const point = this.toCanvasPoint(event);
      this.crosshair.position.set(point.x, point.y);
    };

    this.pointerDownHandler = (event) => {
      this.shots += 1;
      const point = this.toCanvasPoint(event);

      if (!this.isPlayerInShootingArea) {
        this.points = 0;
        this.playAudio(this.shotFailSound);
        this.emitStats();
        return;
      }

      if (this.isLevel6(this.currentLevel)) {
        this.playAudio(this.shotSound);
        this.handleLevel6Shot(point.x, point.y);
        this.emitStats();
        return;
      }

      this.spawnWorldBulletMark(point.x, point.y);
      this.playAudio(this.shotSound);

      const innocentHit = this.findInnocentHit(point.x, point.y);
      if (innocentHit) {
        this.points = -innocentHit.penalty;
        this.score = Math.max(0, this.score - innocentHit.penalty);
        this.spawnScore(-innocentHit.penalty, point.x, point.y - 18);
        this.emitStats();
        this.stopSessionAfterInnocentHit();
        return;
      }

      const targetHit = this.findTargetHit(point.x, point.y);
      if (!targetHit) {
        this.points = 0;
        this.emitStats();
        return;
      }

      this.hits += 1;
      this.points = targetHit.score;
      this.score += targetHit.score;

      this.spawnScore(targetHit.score, point.x, point.y - 20);

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
    };

    canvas.addEventListener('pointermove', this.pointerMoveHandler);
    canvas.addEventListener('pointerdown', this.pointerDownHandler);
  }

  findInnocentHit(x, y) {
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

  findTargetHit(x, y) {
    for (let index = this.targets.length - 1; index >= 0; index -= 1) {
      const target = this.targets[index];
      const score = target.getHitScore(x, y);

      if (score !== null) {
        return { target, score };
      }
    }

    return undefined;
  }

  spawnWorldBulletMark(worldX, worldY) {
    if (!this.bulletMarkTexture) {
      return;
    }

    const bulletMark = new BulletMark(this.bulletMarkTexture, worldX, worldY, 16);
    this.effectsLayer.addChild(bulletMark.sprite);
    this.bulletMarks.push(bulletMark);
  }

  spawnScore(value, x, y) {
    const scorePopup = new Score(value, x, y);
    this.effectsLayer.addChild(scorePopup.label);
    this.scorePopups.push(scorePopup);
  }

  handleLevel6Shot(worldX, worldY) {
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

  attachLevel6HitMark(encounter, worldX, worldY) {
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

  removeLevel6HitMark(encounter) {
    if (!encounter.hitMark) {
      return;
    }

    encounter.sprite.removeChild(encounter.hitMark.sprite);
    encounter.hitMark.destroy();
    encounter.hitMark = undefined;
    encounter.hitMarkRemainingMs = 0;
  }

  updateLevel6(deltaMs) {
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

  spawnLevel6Encounter() {
    if (!this.isLevel6(this.currentLevel) || !this.isPlayerInShootingArea) {
      return;
    }

    if (this.level6ShownImages >= LEVEL6_MAX_IMAGES) {
      return;
    }

    const actorType = Math.random() < 0.5 ? 'terrorist' : 'innocent';
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

  pickLevel6SpawnPreset() {
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

  clearLevel6Encounter() {
    if (!this.level6Encounter) {
      return;
    }

    this.worldLayer.removeChild(this.level6Encounter.container);
    this.level6Encounter.container.destroy({ children: true });
    this.level6Encounter = undefined;
  }

  resetLevel6State() {
    this.clearLevel6Encounter();
    this.level6ShownImages = 0;
    this.level6SpawnDelayMs = 0;
    this.level6LastSpawnIndex = -1;
    this.level6Finished = false;
  }

  getLevel6ActorDiameter() {
    const diameter = Math.min(this.app.screen.width, this.app.screen.height) * 0.145;
    return this.clamp(diameter, 90, 260);
  }

  completeLevel6() {
    if (this.level6Finished || !this.isLevel6(this.currentLevel)) {
      return;
    }

    this.level6Finished = true;

    const completedLevel = this.currentLevel;
    this.isPlayerInShootingArea = false;
    this.options.onLevelComplete?.(completedLevel);
  }

  syncLayout() {
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

  drawArena() {
    const width = this.app.screen.width;
    const height = this.app.screen.height;

    const selectedBackground = this.currentLevel === 1 || this.currentLevel === 3
      ? this.backgroundLevel1Texture
      : this.currentLevel === 2 || this.currentLevel === 4
        ? this.backgroundLevel2Texture
        : this.currentLevel === 6
          ? this.backgroundLevel6Texture
          : this.backgroundTexture;

    if (selectedBackground && selectedBackground.width > 0 && selectedBackground.height > 0) {
      const scale = Math.max(width / selectedBackground.width, height / selectedBackground.height);

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

  drawLevel2CityBackground(width, height) {
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

  syncTargetsWithLayout() {
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

  syncInnocentPeopleWithLayout() {
    if (!this.isInnocentLevel(this.currentLevel)) {
      return;
    }
    this.rebuildInnocentPeople();
  }

  getInnocentDiameter() {
    const diameter = Math.min(this.app.screen.width, this.app.screen.height) * 0.145;
    return this.clamp(diameter, 90, 260);
  }

  getLanes() {
    const width = this.app.screen.width;
    const height = this.app.screen.height;
    const difficultyConfig = DIFFICULTY_CONFIG[this.difficulty];

    if (this.isLevel6(this.currentLevel)) {
      return [];
    }

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

  getTargetDiameter() {
    if (this.currentLevel === 1) {
      const difficultyConfig = DIFFICULTY_CONFIG[this.difficulty];
      const diameter = Math.min(this.app.screen.width, this.app.screen.height) * 0.13 * difficultyConfig.sizeMultiplier;
      return this.clamp(diameter, 110, 210);
    }

    if (this.currentLevel === 2) {
      const difficultyConfig = DIFFICULTY_CONFIG[this.difficulty];
      const diameter = Math.min(this.app.screen.width, this.app.screen.height) * 0.145 * difficultyConfig.sizeMultiplier;
      return this.clamp(diameter, 90, 260);
    }

    if (this.currentLevel === 3 || this.currentLevel === 4) {
      const difficultyConfig = DIFFICULTY_CONFIG[this.difficulty];
      const diameter = Math.min(this.app.screen.width, this.app.screen.height) * 0.12 * difficultyConfig.sizeMultiplier;
      return this.clamp(diameter, 90, 220);
    }

    const difficultyConfig = DIFFICULTY_CONFIG[this.difficulty];
    const diameter = Math.min(this.app.screen.width, this.app.screen.height) * 0.11 * difficultyConfig.sizeMultiplier;
    return this.clamp(diameter, 80, 240);
  }

  getTargetDiameterForIndex(index, baseDiameter) {
    if (this.currentLevel === 1) {
      const preset = LEVEL1_TARGET_PRESETS[index];
      return preset ? baseDiameter * preset.sizeRatio : baseDiameter;
    }

    if (this.currentLevel === 2) {
      const preset = LEVEL2_TARGET_PRESETS[index];
      return preset ? baseDiameter * preset.sizeRatio : baseDiameter;
    }

    if (this.currentLevel === 3) {
      const preset = LEVEL3_TARGET_PRESETS[index];
      return preset ? baseDiameter * preset.sizeRatio : baseDiameter;
    }

    if (this.currentLevel === 4) {
      const preset = LEVEL4_TARGET_PRESETS[index];
      return preset ? baseDiameter * preset.sizeRatio : baseDiameter;
    }

    return baseDiameter;
  }

  toCanvasPoint(event) {
    const rect = this.app.canvas.getBoundingClientRect();
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  }

  playAudio(audio) {
    if (!audio) {
      return;
    }

    audio.currentTime = 0;
    void audio.play().catch(() => undefined);
  }

  emitStats() {
    this.options.onStatsChange?.({
      shots: this.shots,
      hits: this.hits,
      score: this.score,
      points: this.points,
    });
  }

  clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  isMovingLane(startX, endX) {
    return Math.abs(startX - endX) > 0.5;
  }

  isInnocentLevel(level) {
    return level === 2 || level === 4;
  }

  isLevel6(level) {
    return level === 6;
  }

  removeTarget(target) {
    const index = this.targets.indexOf(target);
    if (index < 0) {
      return;
    }

    this.worldLayer.removeChild(target.sprite);
    target.sprite.destroy({ children: true });
    this.targets.splice(index, 1);
  }

  stopSessionAfterInnocentHit() {
    this.setPlayerInShootingArea(false);
    this.options.onSessionStopped?.();
  }

  advanceWaveLevelIfNeeded() {
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

  isWaveLevel(level) {
    return level === 3 || level === 4;
  }
}

const state = {
  levelOptions: Array.from({ length: TOTAL_LEVEL_OPTIONS }, (_, index) => index + 1),
  difficultyOptions: ['Easy', 'Medium', 'Hard'],

  selectedDifficultyLevel: 1,
  isLevelsMenuOpen: false,
  levelDifficultyMap: createDefaultLevelDifficulties(),
  editableTargetScoreMap: createDefaultEditableTargetScores(),

  shots: 0,
  hits: 0,
  score: 0,
  points: 0,
  elapsedSeconds: 0,
  isSessionRunning: false,

  levelReport: undefined,
  isLevelReportVisible: false,

  sessionTimerId: undefined,
  hasPublishedCompletionForSession: false,

  game: undefined,
};

const ui = {
  pixiHost: document.getElementById('pixiHost'),
  difficultyControls: document.getElementById('difficultyControls'),
  startBtn: document.getElementById('startBtn'),
  restartBtn: document.getElementById('restartBtn'),
  timerLabel: document.getElementById('timerLabel'),
  sessionNote: document.getElementById('sessionNote'),
  scoreValue: document.getElementById('scoreValue'),
  accuracyValue: document.getElementById('accuracyValue'),
  hitsValue: document.getElementById('hitsValue'),
  pointsValue: document.getElementById('pointsValue'),
  levelsToggle: document.getElementById('levelsToggle'),
  currentLevelLabel: document.getElementById('currentLevelLabel'),
  levelsScroll: document.getElementById('levelsScroll'),
  targetScoreEditor: document.getElementById('targetScoreEditor'),
  targetScoreEditorLabel: document.getElementById('targetScoreEditorLabel'),
  targetScoreDecreaseBtn: document.getElementById('targetScoreDecreaseBtn'),
  targetScoreInput: document.getElementById('targetScoreInput'),
  targetScoreIncreaseBtn: document.getElementById('targetScoreIncreaseBtn'),
  levelReportBackdrop: document.getElementById('levelReportBackdrop'),
  reportOutcome: document.getElementById('reportOutcome'),
  reportCompletedAt: document.getElementById('reportCompletedAt'),
  reportCompletionLabel: document.getElementById('reportCompletionLabel'),
  reportObjective: document.getElementById('reportObjective'),
  reportDifficulty: document.getElementById('reportDifficulty'),
  reportTime: document.getElementById('reportTime'),
  reportScore: document.getElementById('reportScore'),
  reportAccuracy: document.getElementById('reportAccuracy'),
  reportShots: document.getElementById('reportShots'),
  reportHits: document.getElementById('reportHits'),
  reportMisses: document.getElementById('reportMisses'),
  reportPointsPerShot: document.getElementById('reportPointsPerShot'),
  reportHitsPerMinute: document.getElementById('reportHitsPerMinute'),
  reportCloseBtn: document.getElementById('reportCloseBtn'),
  nextLevelBtn: document.getElementById('nextLevelBtn'),
  retryBtn: document.getElementById('retryBtn'),
};

function canBootstrapPixi() {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return false;
  }

  const testCanvas = document.createElement('canvas');
  return Boolean(testCanvas.getContext('2d'));
}

function hasLevelConfiguration(level) {
  return Boolean(LEVEL_CONFIGS[level]);
}

function isEditableTargetScoreLevel(level) {
  return EDITABLE_TARGET_SCORE_LEVELS.includes(level);
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function roundToSingleDecimal(value) {
  return Math.round(value * 10) / 10;
}

function formatElapsedTime(totalSeconds) {
  const minutes = Math.floor(totalSeconds / 60).toString().padStart(2, '0');
  const seconds = (totalSeconds % 60).toString().padStart(2, '0');
  return `${minutes}:${seconds}`;
}

function resolveTargetScore(level) {
  const levelConfiguration = LEVEL_CONFIGS[level];

  if (!levelConfiguration || levelConfiguration.objective !== 'score') {
    return 0;
  }

  if (!isEditableTargetScoreLevel(level)) {
    return levelConfiguration.targetScore ?? 0;
  }

  return state.editableTargetScoreMap[level] ?? levelConfiguration.targetScore ?? 0;
}

function selectedLevelDifficulty() {
  return state.levelDifficultyMap[state.selectedDifficultyLevel] ?? 'Medium';
}

function objectiveLabel() {
  const selectedLevel = state.selectedDifficultyLevel;
  const levelConfiguration = LEVEL_CONFIGS[selectedLevel];

  if (!levelConfiguration) {
    return 'No objective';
  }

  if (levelConfiguration.objective === 'score') {
    return `Target score: ${resolveTargetScore(selectedLevel)}`;
  }

  return levelConfiguration.objectiveLabel;
}

function accuracy() {
  if (state.shots === 0) {
    return 0;
  }

  return Math.round((state.hits / state.shots) * 100);
}

function clearLevelReport() {
  state.hasPublishedCompletionForSession = false;
  state.levelReport = undefined;
  state.isLevelReportVisible = false;
}

function publishLevelReport(completionLabel, outcomeLabel) {
  const shots = state.shots;
  const hits = state.hits;
  const misses = Math.max(shots - hits, 0);
  const elapsedSeconds = state.elapsedSeconds;
  const finalScore = state.score;
  const objective = objectiveLabel();
  const pointsPerShot = shots > 0 ? finalScore / shots : 0;
  const hitsPerMinute = elapsedSeconds > 0 ? (hits * 60) / elapsedSeconds : 0;

  state.levelReport = {
    level: state.selectedDifficultyLevel,
    outcomeLabel,
    difficulty: selectedLevelDifficulty(),
    objective,
    completionLabel,
    completedAtLabel: new Date().toLocaleString(),
    elapsedTimeLabel: formatElapsedTime(elapsedSeconds),
    elapsedSeconds,
    finalScore,
    shots,
    hits,
    misses,
    accuracy: accuracy(),
    pointsPerShot: roundToSingleDecimal(pointsPerShot),
    hitsPerMinute: roundToSingleDecimal(hitsPerMinute),
  };

  state.isLevelReportVisible = true;
}

function completeCurrentLevel(completionLabel) {
  if (state.hasPublishedCompletionForSession) {
    return;
  }

  state.hasPublishedCompletionForSession = true;

  stopTimer();
  state.game?.setPlayerInShootingArea(false);
  publishLevelReport(completionLabel, 'Completed');
  render();
}

function findNextConfiguredLevel() {
  const currentLevel = state.selectedDifficultyLevel;
  for (let level = currentLevel + 1; level <= TOTAL_LEVEL_OPTIONS; level += 1) {
    if (hasLevelConfiguration(level)) {
      return level;
    }
  }
  return undefined;
}

function canGoToNextLevel() {
  return findNextConfiguredLevel() !== undefined;
}

function startTimer() {
  if (state.sessionTimerId !== undefined) {
    return;
  }

  state.isSessionRunning = true;

  state.sessionTimerId = window.setInterval(() => {
    state.elapsedSeconds += 1;
    ui.timerLabel.textContent = formatElapsedTime(state.elapsedSeconds);
  }, 1000);
}

function stopTimer() {
  if (state.sessionTimerId !== undefined) {
    window.clearInterval(state.sessionTimerId);
    state.sessionTimerId = undefined;
  }

  state.isSessionRunning = false;
}

function applySelectedLevelConfiguration() {
  state.game?.setLevel(state.selectedDifficultyLevel);
  state.game?.setDifficulty(selectedLevelDifficulty());
}

function setEditableTargetScore(level, value) {
  const clampedScore = clamp(Math.round(value), TARGET_SCORE_MIN, TARGET_SCORE_MAX);
  state.editableTargetScoreMap[level] = clampedScore;
}

function adjustSelectedLevelTargetScore(delta) {
  const selectedLevel = state.selectedDifficultyLevel;
  if (!isEditableTargetScoreLevel(selectedLevel)) {
    return;
  }

  setEditableTargetScore(selectedLevel, resolveTargetScore(selectedLevel) + delta);
  render();
}

function startSession() {
  if (!state.game || !hasLevelConfiguration(state.selectedDifficultyLevel) || state.isSessionRunning) {
    return;
  }

  clearLevelReport();
  state.game.setPlayerInShootingArea(true);
  startTimer();
  render();
}

function restartSession() {
  clearLevelReport();
  stopTimer();
  state.elapsedSeconds = 0;
  state.game?.setPlayerInShootingArea(false);
  state.game?.resetSession();
  applySelectedLevelConfiguration();
  render();
}

function closeLevelReport() {
  restartSession();
}

function goToNextLevel() {
  const nextLevel = findNextConfiguredLevel();

  if (!nextLevel) {
    closeLevelReport();
    return;
  }

  state.selectedDifficultyLevel = nextLevel;
  state.isLevelsMenuOpen = false;
  restartSession();
}

function chooseCurrentLevelDifficulty(difficulty) {
  const selectedLevel = state.selectedDifficultyLevel;
  state.levelDifficultyMap[selectedLevel] = difficulty;
  restartSession();
}

function chooseLevel(level) {
  state.selectedDifficultyLevel = level;
  state.isLevelsMenuOpen = false;
  restartSession();
}

function syncStats(stats) {
  state.shots = stats.shots;
  state.hits = stats.hits;
  state.score = stats.score;
  state.points = stats.points;

  const levelConfiguration = LEVEL_CONFIGS[state.selectedDifficultyLevel];
  if (!levelConfiguration || levelConfiguration.objective !== 'score') {
    render();
    return;
  }

  const targetScore = resolveTargetScore(state.selectedDifficultyLevel);
  if (targetScore > 0 && stats.score >= targetScore) {
    completeCurrentLevel('Target score reached');
    return;
  }

  render();
}

function handleLevelComplete(level) {
  if (level !== state.selectedDifficultyLevel) {
    return;
  }

  completeCurrentLevel('Objective completed');
}

function handleSessionStopped() {
  if (state.isSessionRunning) {
    stopTimer();
  }

  const currentLevel = state.selectedDifficultyLevel;
  const isAllyProtectionLevel = currentLevel === 2 || currentLevel === 4;

  if (!isAllyProtectionLevel || state.hasPublishedCompletionForSession) {
    render();
    return;
  }

  state.hasPublishedCompletionForSession = true;
  publishLevelReport('u fail u killed an ally', 'Failed');
  render();
}

function renderDifficultyButtons() {
  ui.difficultyControls.innerHTML = '';

  for (const difficulty of state.difficultyOptions) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'session-btn difficulty-btn';
    if (selectedLevelDifficulty() === difficulty) {
      button.classList.add('active');
    }
    button.textContent = difficulty;
    button.addEventListener('click', () => chooseCurrentLevelDifficulty(difficulty));
    ui.difficultyControls.appendChild(button);
  }
}

function renderLevelsMenu() {
  ui.levelsScroll.innerHTML = '';

  for (const level of state.levelOptions) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'level-btn';

    if (state.selectedDifficultyLevel === level) {
      button.classList.add('active');
    }

    if (!hasLevelConfiguration(level)) {
      button.classList.add('empty');
    }

    const left = document.createElement('span');
    left.textContent = `Level ${level}`;

    const right = document.createElement('small');
    right.textContent = `${hasLevelConfiguration(level) ? 'Ready' : 'Empty'} | ${state.levelDifficultyMap[level] ?? 'Medium'}`;

    button.appendChild(left);
    button.appendChild(right);

    button.addEventListener('click', () => chooseLevel(level));

    ui.levelsScroll.appendChild(button);
  }
}

function renderReport() {
  if (!state.isLevelReportVisible || !state.levelReport) {
    ui.levelReportBackdrop.classList.add('hidden');
    return;
  }

  const report = state.levelReport;

  ui.reportOutcome.textContent = `Level ${report.level} ${report.outcomeLabel}`;
  ui.reportCompletedAt.textContent = report.completedAtLabel;
  ui.reportCompletionLabel.textContent = report.completionLabel;
  ui.reportObjective.textContent = report.objective;
  ui.reportDifficulty.textContent = report.difficulty;
  ui.reportTime.textContent = report.elapsedTimeLabel;
  ui.reportScore.textContent = String(report.finalScore);
  ui.reportAccuracy.textContent = `${report.accuracy}%`;
  ui.reportShots.textContent = String(report.shots);
  ui.reportHits.textContent = String(report.hits);
  ui.reportMisses.textContent = String(report.misses);
  ui.reportPointsPerShot.textContent = String(report.pointsPerShot);
  ui.reportHitsPerMinute.textContent = String(report.hitsPerMinute);

  ui.nextLevelBtn.disabled = !canGoToNextLevel();
  ui.levelReportBackdrop.classList.remove('hidden');
}

function render() {
  const isSelectedDifficultyAvailable = hasLevelConfiguration(state.selectedDifficultyLevel);

  ui.currentLevelLabel.textContent = `Level ${state.selectedDifficultyLevel}`;
  ui.scoreValue.textContent = String(state.score);
  ui.hitsValue.textContent = String(state.hits);
  ui.pointsValue.textContent = String(state.points);
  ui.accuracyValue.textContent = `${accuracy()}%`;
  ui.timerLabel.textContent = formatElapsedTime(state.elapsedSeconds);

  ui.sessionNote.textContent = isSelectedDifficultyAvailable
    ? objectiveLabel()
    : `Level ${state.selectedDifficultyLevel} is empty for now`;
  ui.sessionNote.classList.toggle('empty', !isSelectedDifficultyAvailable);

  ui.startBtn.disabled = state.isSessionRunning || !isSelectedDifficultyAvailable;

  ui.levelsScroll.classList.toggle('hidden', !state.isLevelsMenuOpen);

  const showTargetEditor = isEditableTargetScoreLevel(state.selectedDifficultyLevel);
  ui.targetScoreEditor.classList.toggle('hidden', !showTargetEditor);

  if (showTargetEditor) {
    ui.targetScoreEditorLabel.textContent = `Target Score (Level ${state.selectedDifficultyLevel})`;
    ui.targetScoreInput.value = String(resolveTargetScore(state.selectedDifficultyLevel));
    ui.targetScoreDecreaseBtn.disabled = state.isSessionRunning;
    ui.targetScoreIncreaseBtn.disabled = state.isSessionRunning;
    ui.targetScoreInput.disabled = state.isSessionRunning;
  }

  renderDifficultyButtons();
  renderLevelsMenu();
  renderReport();
}

function bindUiEvents() {
  ui.levelsToggle.addEventListener('click', () => {
    state.isLevelsMenuOpen = !state.isLevelsMenuOpen;
    render();
  });

  ui.startBtn.addEventListener('click', startSession);
  ui.restartBtn.addEventListener('click', restartSession);

  ui.targetScoreDecreaseBtn.addEventListener('click', () => {
    adjustSelectedLevelTargetScore(-TARGET_SCORE_STEP);
  });

  ui.targetScoreIncreaseBtn.addEventListener('click', () => {
    adjustSelectedLevelTargetScore(TARGET_SCORE_STEP);
  });

  ui.targetScoreInput.addEventListener('input', (event) => {
    const selectedLevel = state.selectedDifficultyLevel;
    if (!isEditableTargetScoreLevel(selectedLevel)) {
      return;
    }

    const parsed = Number(event.target.value);
    if (!Number.isFinite(parsed)) {
      return;
    }

    setEditableTargetScore(selectedLevel, parsed);
    render();
  });

  ui.reportCloseBtn.addEventListener('click', closeLevelReport);
  ui.retryBtn.addEventListener('click', restartSession);
  ui.nextLevelBtn.addEventListener('click', goToNextLevel);

  window.addEventListener('beforeunload', () => {
    stopTimer();
    state.game?.destroy();
  });
}

async function boot() {
  bindUiEvents();
  render();

  if (!canBootstrapPixi()) {
    ui.sessionNote.textContent = 'Pixi initialization failed: this browser does not support canvas.';
    ui.sessionNote.classList.add('empty');
    return;
  }

  state.game = new ShootingRangeGame({
    host: ui.pixiHost,
    onStatsChange: syncStats,
    onLevelComplete: handleLevelComplete,
    onSessionStopped: handleSessionStopped,
  });

  await state.game.init();
  applySelectedLevelConfiguration();
  state.game.setPlayerInShootingArea(false);
  render();
}

void boot();
