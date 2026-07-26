import { Text } from 'pixi.js';

export type ScoreValue = number;

export class Score {
  readonly label: Text;

  private elapsedMs = 0;
  private readonly lifetimeMs = 900;

  constructor(value: ScoreValue, x: number, y: number) {
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

  update(deltaMs: number): boolean {
    this.elapsedMs += deltaMs;

    const lifeRatio = Math.min(this.elapsedMs / this.lifetimeMs, 1);
    this.label.y -= deltaMs * 0.08;
    this.label.alpha = 1 - lifeRatio;

    return this.elapsedMs >= this.lifetimeMs;
  }

  destroy(): void {
    this.label.destroy();
  }

  private resolveScoreColor(value: ScoreValue): number {
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
