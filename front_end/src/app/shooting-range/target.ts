import { Sprite, Texture } from 'pixi.js';

export interface TargetLane {
  startX: number;
  endX: number;
  y: number;
  travelTimeSeconds: number;
}

type HitScore = 10 | 25 | 50 | 70 | 100;

interface RingZone {
  centerX: number;
  centerY: number;
  outerRadius: number;
  midRadius: number;
  centerRadius: number;
  outerScore: HitScore;
  midScore: HitScore;
  centerScore: HitScore;
}

// Ring calibration for targetBoard_v2.png (1024x1536)
const HEAD_CENTER_X = 0.5;
const HEAD_CENTER_Y = 0.241;
const CHEST_CENTER_X = 0.5;
const CHEST_CENTER_Y = 0.51;

const HEAD_ZONE: RingZone = {
  centerX: HEAD_CENTER_X,
  centerY: HEAD_CENTER_Y,
  outerRadius: 0.068,
  midRadius: 0.048,
  centerRadius: 0.031,
  outerScore: 50,
  midScore: 70,
  centerScore: 100,
};

const CHEST_ZONE: RingZone = {
  centerX: CHEST_CENTER_X,
  centerY: CHEST_CENTER_Y,
  outerRadius: 0.125,
  midRadius: 0.085,
  centerRadius: 0.052,
  outerScore: 10,
  midScore: 25,
  centerScore: 50,
};

export class Target {
  readonly sprite: Sprite;

  private lane: TargetLane;
  private progress = 0;
  private direction = 1;

  constructor(texture: Texture, lane: TargetLane, displayDiameter: number) {
    this.lane = lane;
    this.sprite = new Sprite(texture);
    this.sprite.anchor.set(0.5);
    this.setDisplayDiameter(displayDiameter);
    this.sprite.position.set(lane.startX, lane.y);
  }

  update(deltaSeconds: number): void {
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

  setLane(lane: TargetLane): void {
    this.lane = lane;
    this.sprite.x = this.lerp(this.lane.startX, this.lane.endX, this.progress);
    this.sprite.y = this.lane.y;
  }

  setDisplayDiameter(displayDiameter: number): void {
    const baseDiameter = Math.max(this.sprite.texture.width, this.sprite.texture.height, 1);
    const scale = displayDiameter / baseDiameter;

    this.sprite.scale.set(scale);
  }

  getHitScore(worldX: number, worldY: number): HitScore | null {
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

  toLocalCoordinates(worldX: number, worldY: number): { x: number; y: number } {
    const scaleX = this.sprite.scale.x || 1;
    const scaleY = this.sprite.scale.y || 1;

    return {
      x: (worldX - this.sprite.x) / scaleX,
      y: (worldY - this.sprite.y) / scaleY,
    };
  }

  private toNormalizedCoordinates(worldX: number, worldY: number): { x: number; y: number } | null {
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

  private getZoneScore(x: number, y: number, zone: RingZone): HitScore | null {
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

  private lerp(start: number, end: number, amount: number): number {
    return start + ((end - start) * amount);
  }
}
